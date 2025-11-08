# Docker Compose Refactoring Plan

## Overview
Refactor the Outlier Wormhole project into a Docker Compose setup with 3 concurrent services that work together seamlessly.

## Current Architecture Analysis

### Service 1: Wormhole Server (`wormhole_server.py`)
- **Purpose**: WebSocket bridge server
- **Port**: 8765 (configurable via `wormhole_port`)
- **Dependencies**: websockets, dotenv
- **Function**: Manages connections between page clients and API senders

### Service 2: Wormhole Browser Bridge (`wormhole.py`)
- **Purpose**: Playwright-based browser automation with WebSocket injection
- **Ports**: 9222 (Chrome debug port)
- **Dependencies**: playwright, websockets, Chrome browser
- **Function**: Injects JavaScript into Outlier.ai pages, manages authentication
- **Critical Files**: `inject_wormhole.js`

### Service 3: Wormhole OpenAI Server (`wormhole-oai.py`)
- **Purpose**: OpenAI-compatible API server
- **Port**: 11434
- **Dependencies**: FastAPI, uvicorn, send.py, template_composer.py, agent_workflow.py
- **Function**: Exposes OpenAI & Ollama compatible endpoints

## Proposed Docker Compose Structure

```yaml
version: '3.8'

services:
  wormhole-server:
    # WebSocket bridge server
    ports:
      - "8765:8765"
    environment:
      - wormhole_port=8765
    networks:
      - wormhole-net

  wormhole-bridge:
    # Browser automation + injection
    ports:
      - "9222:9222"
    environment:
      - chrome_debug_port=9222
      - wormhole_port=8765
      - outlier_email=${OUTLIER_EMAIL}
      - outlier_password=${OUTLIER_PASSWORD}
    depends_on:
      - wormhole-server
    volumes:
      - ./inject_wormhole.js:/app/inject_wormhole.js:ro
      - chrome-data:/tmp/chrome-debug
    networks:
      - wormhole-net

  wormhole-oai:
    # OpenAI-compatible API server
    ports:
      - "11434:11434"
    environment:
      - wormhole_port=8765
    depends_on:
      - wormhole-server
      - wormhole-bridge
    volumes:
      - ./templates:/app/templates:ro
      - ./data:/app/data
      - ./agent_prompts.yaml:/app/agent_prompts.yaml:ro
    networks:
      - wormhole-net

networks:
  wormhole-net:
    driver: bridge

volumes:
  chrome-data:
```

## Key Refactoring Requirements

### 1. Service Communication
- All services must use `wormhole-server` as hostname instead of `localhost`
- WebSocket connections: `ws://wormhole-server:8765`
- HTTP endpoints remain on their respective ports

### 2. Configuration Changes
- Extract hardcoded `localhost` references
- Use environment variables for all inter-service communication
- Create `.env` file for secrets (credentials)
- Create `docker-compose.env` for service discovery

### 3. File Structure
```
/app
├── services/
│   ├── server/
│   │   ├── Dockerfile
│   │   └── wormhole_server.py
│   ├── bridge/
│   │   ├── Dockerfile
│   │   ├── wormhole.py
│   │   └── inject_wormhole.js
│   └── oai/
│       ├── Dockerfile
│       ├── wormhole-oai.py
│       ├── send.py
│       ├── agent_workflow.py
│       ├── template_composer.py
│       └── prompt_utils.py
├── shared/
│   ├── templates/
│   └── agent_prompts.yaml
├── docker-compose.yml
├── .env.example
└── README.md
```

### 4. Critical Code Changes

**wormhole_server.py:**
- Bind to `0.0.0.0` instead of `localhost`
- Add health check endpoint

**wormhole.py:**
- Replace `localhost:8765` with `os.getenv('WORMHOLE_SERVER_HOST', 'wormhole-server')`
- Make Chrome user-data-dir configurable
- Add retry logic for server connection

**wormhole-oai.py:**
- Update `send.py` to use service hostname
- Bind to `0.0.0.0:11434`
- Add dependency checks on startup

**inject_wormhole.js:**
- Make WebSocket URL configurable via script injection

### 5. Dockerfiles

**Base requirements:**
- Python 3.11+ slim images (Debian-based for best compatibility)
- Minimal layer caching
- Non-root user execution
- Health checks

**Image choices validated (2024/2025 research):**
- `python:3.11-slim` - Best balance of size (~125MB) and compatibility for server/OAI services
- `mcr.microsoft.com/playwright/python:v1.40.0-jammy` - Official Playwright image with pre-installed browsers
- Avoided `alpine` due to musl libc compatibility issues with Python packages

**Bridge service specific:**
- Playwright browsers pre-installed
- Chrome/Chromium dependencies
- Using `jammy` (Ubuntu 22.04 LTS) variant for stability

### 6. Network & Security
- Internal network for service communication
- Only expose necessary ports to host
- Secret management via `.env` (not committed)
- Volume mounts for persistent data and logs

## Implementation Priority

1. ~~**Phase 1**: Create base Dockerfiles for each service~~ ✅ **COMPLETED**
   - Created `services/server/Dockerfile` with websockets dependencies
   - Created `services/bridge/Dockerfile` with Playwright and Chromium
   - Created `services/oai/Dockerfile` with FastAPI and dependencies
   - All services use non-root users and include health checks
2. **Phase 2**: Update hardcoded connections to use service names
3. **Phase 3**: Create docker-compose.yml with proper dependencies
4. **Phase 4**: Add health checks and restart policies
5. **Phase 5**: Test end-to-end workflow
6. **Phase 6**: Document setup and usage

## Success Criteria

- All 3 services start concurrently via `docker-compose up`
- WebSocket connections establish between services
- Browser automation connects to WebSocket server
- OpenAI API server receives responses from browser bridge
- No hardcoded `localhost` references
- Configuration via environment variables
- Logs accessible via `docker-compose logs`
