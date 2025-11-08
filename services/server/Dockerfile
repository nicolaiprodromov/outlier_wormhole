# Dockerfile for Wormhole Server
# WebSocket bridge server that connects page clients and API senders

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY wormhole_server.py .

# Create non-root user
RUN useradd -m -u 1000 wormhole && chown -R wormhole:wormhole /app
USER wormhole

# Expose WebSocket port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.connect(('localhost', 8765)); s.close()" || exit 1

# Run server
CMD ["python", "wormhole_server.py"]
