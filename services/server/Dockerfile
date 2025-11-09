FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y openssl && rm -rf /var/lib/apt/lists/*

COPY services/server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/server/wormhole_server.py .

RUN useradd -m -u 1000 wormhole && chown -R wormhole:wormhole /app
USER wormhole

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.connect(('localhost', 8765)); s.close()" || exit 1

CMD ["python", "-u", "wormhole_server.py"]
