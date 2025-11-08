# Dockerfile for Wormhole Bridge
# Playwright-based browser automation with WebSocket injection

FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set environment variables for proper logging
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set working directory
WORKDIR /app

# Install dependencies
COPY services/bridge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy bridge code and injection script
COPY services/bridge/wormhole.py .
COPY services/bridge/inject_wormhole.js .
COPY services/bridge/ws_proxy.py .

# Create directory for Chrome user data
RUN mkdir -p /tmp/chrome-debug && chmod 777 /tmp/chrome-debug

# Use existing pwuser (UID 1000) from Playwright image or create if needed
RUN id -u pwuser >/dev/null 2>&1 && usermod -l wormhole pwuser || useradd -m -u 1001 wormhole
RUN chown -R $(id -u wormhole):$(id -g wormhole) /app
USER wormhole

# Expose Chrome debug port and WebSocket proxy port
EXPOSE 9222 8766

# Health check - verify Chrome debug port is accessible
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9222/json/version || exit 1

# Run both proxy and bridge with unbuffered output
CMD python -u ws_proxy.py & python -u wormhole.py
