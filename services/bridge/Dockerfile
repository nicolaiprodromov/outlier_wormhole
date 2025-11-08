# Dockerfile for Wormhole Bridge
# Playwright-based browser automation with WebSocket injection

FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy bridge code and injection script
COPY wormhole.py .
COPY inject_wormhole.js .

# Create directory for Chrome user data
RUN mkdir -p /tmp/chrome-debug && chmod 777 /tmp/chrome-debug

# Create non-root user
RUN useradd -m -u 1000 wormhole && chown -R wormhole:wormhole /app
USER wormhole

# Expose Chrome debug port
EXPOSE 9222

# Health check - verify Chrome debug port is accessible
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9222/json/version || exit 1

# Run bridge
CMD ["python", "wormhole.py"]
