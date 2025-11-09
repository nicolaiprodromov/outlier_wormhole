# Outlier Wormhole

![Outlier Logo](https://app.outlier.ai/assets/logo.svg)

A system that proxies AI model requests through Outlier.ai, exposing them via OpenAI-compatible API.

```text
┌─────────────────────────────────────────────────────────────────┐
│                         Client (VS Code)                        │
│                    http://localhost:11434                       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       OAI Service :11434                        │
│  • OpenAI-compatible API (/v1/chat/completions)                 │
│  • Handles conversation tracking & template composition         │
│  • Logs all prompts/responses to data/                          │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Wormhole Server :8765                        │
│  • WebSocket relay between services                             │
│  • Routes commands from OAI to Bridge                           │
│  • Returns responses back to OAI                                │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Bridge Service :8766                       │
│  • Headless Chrome with Outlier.ai login                        │
│  • Injects JavaScript to control Outlier interface              │
│  • Creates conversations and sends messages via WebSocket       │
│  • Exposes Chrome DevTools on :9222                             │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

**Prerequisites:** Docker

**Step 1:** Create a new directory and add these two files:

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
# Outlier.ai Credentials (REQUIRED)
OUTLIER_EMAIL=your-email@example.com
OUTLIER_PASSWORD=your-password

# Service Ports (Optional - defaults shown)
wormhole_port=8765
wormhole_proxy=8766
chrome_debug_port=9222
oai_port=11434
```

**Step 2:** Start the services:

```bash
docker compose up -d
```

**Step 3:** Point any OpenAI-compatible client to `http://localhost:11434`

## Commands

```bash
docker compose up -d          # Start all services
docker compose down           # Stop all services
docker compose logs -f [service]  # View logs
docker compose ps             # Check status
docker compose restart        # Restart services
```

---

### Server (`services/server/`)

WebSocket relay server that connects OAI and Bridge services. Manages request/response routing and maintains client connections.

**Port:** 8765

### Bridge (`services/bridge/`)

Automated Chrome browser that logs into Outlier.ai and injects control scripts. Acts as the interface between the wormhole system and Outlier's web app.

**Ports:** 8766 (proxy), 9222 (chrome debug)

### OAI (`services/oai/`)

FastAPI server providing OpenAI-compatible endpoints. Transforms requests into Outlier commands, manages conversation state, and logs all interactions.

**Port:** 11434
