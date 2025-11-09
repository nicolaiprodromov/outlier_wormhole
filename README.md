![Outlier Logo](https://app.outlier.ai/assets/logo.svg)

get _0$ 24/7_ sota models API via an **OpenAI/Ollama-compatible server**.

![Outlier Logo](https://app.outlier.ai/assets/llm-icons/claude-sonnet-4-5-20250929.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/claude-opus-4-1-20250805.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/gpt-5-2025-08-07.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/gemini-2.5-pro-preview-06-05.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/deepseek-r1-0528.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/Grok%203.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/Llama%204%20Maverick.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/qwen3-235b-a22b-2507-v1.svg)

```text
┌─────────────────────────────────────────────────────────────┐
│                       Client (VS Code)                      │
│                  `http://localhost:11434`                   │
└────────────────────────────── ▲ ────────────────────────────┘
                                │
┌────────────────────────────── ▼ ────────────────────────────┐
│                      OAI service `:11434`                   │
├─────────────────────────────────────────────────────────────┤
│  • OpenAI-compatible API (/v1/chat/completions)             │
│  • handles conversation tracking & template composition     │
│  • logs all prompts/responses to `data/`                    │
└────────────────────────────── ▲ ────────────────────────────┘
                                │
┌────────────────────────────── ▼ ────────────────────────────┐
│                    wormhole server `:8765`                  │
├─────────────────────────────────────────────────────────────┤
│  • websocket relay between services                         │
│  • routes commands from OAI to bridge                       │
│  • returns responses back to OAI                            │
└────────────────────────────── ▲ ────────────────────────────┘
                                │
┌────────────────────────────── ▼ ────────────────────────────┐
│                     bridge service `:8766`                  │
├─────────────────────────────────────────────────────────────┤
│  • headless chromium with `app.outlier.ai` login            │
│  • injects js to open websocket wormhole                    │
│  • send conversation/message data via websocket             │
│  • exposes devtools over :9222*                             │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

> [!IMPORTANT]
>
> you need go through the annoying process of making an outlier/scaleai account to use the _outlier playground_

**Prerequisites:**

- Docker (running)

1. **Create a new directory and add these two files:**

   `docker-compose.yml`:

   ```yaml
   name: ow
   services:
     server:
       image: nicolaiprodromov/ow-server:latest
       container_name: server
       ports:
         - "8765:8765"
       environment:
         - wormhole_port=8765
         - wormhole_host=0.0.0.0
       networks:
         - ow-net
       healthcheck:
         test:
           [
             "CMD",
             "python",
             "-c",
             "import socket; s = socket.socket(); s.connect(('localhost', 8765)); s.close()",
           ]
         interval: 10s
         timeout: 5s
         retries: 5
       restart: unless-stopped

     bridge:
       image: nicolaiprodromov/ow-bridge:latest
       container_name: bridge
       ports:
         - "9222:9222"
         - "8766:8766"
       environment:
         - chrome_debug_port=9222
         - chrome_user_data_dir=/tmp/chrome-debug
         - wormhole_server_host=server
         - wormhole_port=8765
         - proxy_port=8766
         - outlier_email=${OUTLIER_EMAIL}
         - outlier_password=${OUTLIER_PASSWORD}
       depends_on:
         server:
           condition: service_healthy
       volumes:
         - chrome-data:/tmp/chrome-debug
       networks:
         - ow-net
       restart: unless-stopped
       shm_size: 2gb

     oai:
       image: nicolaiprodromov/ow-oai:latest
       container_name: oai
       ports:
         - "11434:11434"
       environment:
         - oai_host=0.0.0.0
         - oai_port=11434
         - wormhole_server_host=server
         - wormhole_port=8765
       depends_on:
         server:
           condition: service_healthy
         bridge:
           condition: service_started
       volumes:
         - ./data:/app/data
       networks:
         - ow-net
       healthcheck:
         test:
           [
             "CMD",
             "python",
             "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:11434/api/version').read()",
           ]
         interval: 15s
         timeout: 5s
         retries: 3
       restart: unless-stopped

   networks:
     ow-net:
       driver: bridge

   volumes:
     chrome-data:
       driver: local
   ```

   `.env`:

   ```env
   outlier_email="your@email"
   outlier_password="yourpassword"

   wormhole_port=8765
   chrome_debug_port=9222
   proxy_port=8766
   oai_port=11434
   ```

2. **Start the services:**

   ```bash
   docker compose up -d
   ```

3. **Point any OpenAI-compatible client to `http://localhost:11434`**

## Use with IDE

### VS Code

- **Download [johnny-zhao.oai-compatible-copilot](https://marketplace.visualstudio.com/items?itemName=johnny-zhao.oai-compatible-copilot) and add these to `.vscode/settings.json`:**

  ```json
  "oaicopilot.baseUrl": "http://localhost:11434",
    "oaicopilot.retry": {
      "enabled": true,
      "max_attempts": 3,
      "interval_ms": 1000
    },
    "oaicopilot.models": [
      {
        // all the models from outlier
        "id": "gpt-5-chat",
        "name": "GPT-5 Chat",
        "owned_by": "openai"
      },
      // ... rest of the models
    ]
  ```

### Cursor

- **In Cursor settings, configure the API endpoint:**
  1. Open Settings (`Cmd/Ctrl + ,`)
  2. Go to `Cursor Settings` > `Models`
  3. In the OpenAI API Key section, click **"Override OpenAI Base URL (when using key)"**
  4. Toggle it ON and enter: `http://localhost:11434/v1`
  5. Add your OpenAI API key (can be any non-empty string, e.g., `outlier`)
  6. The model picker will automatically show available models from your endpoint

### Windsurf

- **Windsurf does not currently support custom OpenAI-compatible API endpoints.**
  1. Install the **OpenAI Chat** extension from the Windsurf marketplace
  2. Configure the extension with:
     - API Base URL: `http://localhost:11434/v1`
     - API Key: Any non-empty string (e.g., `outlier`)
     - Custom model name: Any Outlier model ID

## Commands

```bash
docker compose up -d              # Start services
docker compose start              # Start services
docker compose stop               # Stop services
docker compose down               # Stop services and delete containers
docker compose restart            # Restart services
docker compose ps                 # Check status
docker compose logs -f [service]  # View logs
```

## Containers

### Server (`services/server/`)

- WebSocket relay server that connects OAI and Bridge services. Manages request/response routing and maintains client connections:
  - **Port:** 8765

### Bridge (`services/bridge/`)

- Automated Chrome browser that logs into Outlier.ai and injects control scripts. Acts as the interface between the wormhole system and Outlier's web app.
  - **Ports:** 8766 (proxy), 9222 (chrome debug)

### OAI (`services/oai/`)

- FastAPI server providing OpenAI-compatible endpoints. Transforms requests into Outlier commands, manages conversation state, and logs all interactions.
  - **Port:** 11434
