# [weblm](https://app.outlier.ai) wormhole

get 0$ sota llm models API via an **OpenAI/Ollama-compatible server**.

![Outlier Logo](https://app.outlier.ai/assets/llm-icons/claude-sonnet-4-5-20250929.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/claude-opus-4-1-20250805.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/gpt-5-2025-08-07.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/gemini-2.5-pro-preview-06-05.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/deepseek-r1-0528.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/Grok%203.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/Llama%204%20Maverick.svg)
![Outlier Logo](https://app.outlier.ai/assets/llm-icons/qwen3-235b-a22b-2507-v1.svg)

```
┌─────────────────────────────────────────────────────────────┐
├──────────────────────────── Client ─────────────────────────┤
└────────────────────────────── ▲ ────────────────────────────┘
                                │
┌────────────────────────────── ▼ ────────────────────────────┐
│                      OAI service `:11434`                   │
├─────────────────────────────────────────────────────────────┤
│  • openAI-compatible API (/v1/chat/completions)             │
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

## "quick" start

> [!IMPORTANT]
>
> you need go through the annoying process of making an outlier/scaleai account to use the _outlier playground_.

**prerequisites:**

- [docker](https://www.docker.com/get-started) (running)
- [just](https://github.com/casey/just) (optional)

---

you have two options to get started, cloning the repo is easier, but first option is more lightweight:

### easy:

1. make a `docker-compose.yml` file (copy [docker-compose.public.yml](./docker-compose.public.yml) content) and modify the volume paths to point to your local chrome executable, chrome profile and data directories:

2. make a `.env` file:

   ```env
   # security
   OAI_API_KEY=

   # ports
   wormhole_port=8765
   chrome_debug_port=9222
   proxy_port=8766
   oai_port=11434
   ```

3. run your local chrome, login to outlier and exit, after that run chrome in headless mode to convert your profile and exit:

> `/path/to/chrome --user-data-dir=/path/to/chrome-profile --headless --remote-debugging-port=9222`

4. point the docker-compose file to the chrome executable and copy (recommended) the profile folder to the location you specified in the `docker-compose.yml`.

5. start the services:

   ```bash
   docker compose up --build -d
   ```

### a bit more involved (for development):

1. **clone this repository & rename `.env.example` to `.env` & replace the content of `.env` with your data**

2. **run `get_session` to log into Outlier and store your session:**

- with `python` (activate the venv before or install dependencies):
  1. run `python3 scripts/get_session.py --headful` and login to Outlier.ai when the browser opens than close it.
  2. run `python3 scripts/get_session.py --headless` to convert your session
- with `just`:
  1. run `just get_session --headful` and login to Outlier.ai when the browser opens than close it.
  2. run `just get_session --headless` to convert your session data to headless mode.

2. **start the services:**

   ```just
   just build
   just start
   ```

3. **point any OpenAI-compatible client to `http://localhost:11434`**

## use with your IDE

### vscode

- **download [johnny-zhao.oai-compatible-copilot](https://marketplace.visualstudio.com/items?itemName=johnny-zhao.oai-compatible-copilot) and add these to `.vscode/settings.json`:**

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

### cursor

- **in Cursor settings, configure the API endpoint:**
  1. open Settings (`Cmd/Ctrl + ,`)
  2. go to `Cursor Settings` > `Models`
  3. in the OpenAI API Key section, click **"Override OpenAI Base URL (when using key)"**
  4. toggle it ON and enter: `http://localhost:11434/v1`
  5. add your openai API key (can be any non-empty string, e.g., `outlier`)
  6. the model picker will automatically show available models from your endpoint

## commands

```bash
docker compose up -d              # Start services
docker compose start              # Start services
docker compose stop               # Stop services
docker compose down               # Stop services and delete containers
docker compose restart            # Restart services
docker compose ps                 # Check status
docker compose logs -f [service]  # View logs
```

## containers

### server (`services/server/`)

- webSocket relay server that connects OAI and bridge services. manages request/response routing and maintains persistent client connections:
  - **Port:** 8765

### bridge (`services/bridge/`)

- automated Chrome browser that logs into outlier webpage and injects control scripts. acts as the interface between the wormhole system and Outlier's web app.
  - **ports:** 8766 (proxy), 9222 (chrome debug)

### OAI (`services/oai/`)

- fastAPI server providing OpenAI-compatible endpoints. transforms requests into outlier api calls, manages conversation state, and logs all interactions.
  - **port:** 11434

### janitor (`services/janitor/`) - optional

- a clean-up service to keep the logs size in check, fully configurable.

## roadmap

> the end goal here is to create a plug-n-play solution to hijack as many llm providers as possible and get as many free powerful llm agents as we can.

> right now only outlier is supported and no account rotation is even feasable, but in the future i will keep adding more providers and proxy/account rotation features to maximize free agent use.

> stop serfing the bigweb and enjoy the wildwest of post-truth AI-induced collective coma we're in.

- - [x] OpenAI-compatible API
- - [x] Ollama-compatible API
- - [x] template-based prompt injection
- - [ ] support for file uploads
- - [ ] support for streaming responses
- - [ ] support for more platforms
- - [ ] proxy rotation
- - [ ] account rotation

<div align="center" width="120px">

<img width="100px" src="https://app.outlier.ai/assets/logo.svg"/>

</div>
