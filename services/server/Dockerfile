# Dockerfile for Wormhole Server
# WebSocket bridge server that connects page clients and API senders

FROM python:3.11-slim

# Set environment variables for proper logging
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set working directory
WORKDIR /app

# Install openssl for certificate generation
RUN apt-get update && apt-get install -y openssl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY services/server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY services/server/wormhole_server.py .

# Create non-root user
RUN useradd -m -u 1000 wormhole && chown -R wormhole:wormhole /app
USER wormhole

# Expose WebSocket port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.connect(('localhost', 8765)); s.close()" || exit 1

# Run server with unbuffered output
CMD ["python", "-u", "wormhole_server.py"]
