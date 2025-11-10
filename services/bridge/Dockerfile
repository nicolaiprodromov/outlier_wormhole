
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY services/bridge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy standalone Chrome and pre-authenticated profile from get_session
COPY scripts/get_session/chrome_standalone /app/chrome_standalone
COPY scripts/get_session/chrome_profile /app/chrome_profile

COPY services/bridge/wormhole.py .
COPY services/bridge/inject_wormhole.js .
COPY services/bridge/ws_proxy.py .
COPY services/bridge/entrypoint.sh .

RUN chmod +x entrypoint.sh

# Make Chrome executable
RUN chmod +x /app/chrome_standalone/opt/google/chrome/chrome

RUN mkdir -p /tmp/chrome-debug && chmod 777 /tmp/chrome-debug

RUN id -u pwuser >/dev/null 2>&1 && usermod -l wormhole pwuser || useradd -m -u 1001 wormhole
RUN chown -R $(id -u wormhole):$(id -g wormhole) /app
USER wormhole

EXPOSE ${chrome_debug_port:-9222} ${proxy_port:-8766}

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${chrome_debug_port:-9222}/json/version || exit 1

CMD ["./entrypoint.sh"]
