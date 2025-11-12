#!/bin/sh

URL_FILE="/app/data/tunnel_url.txt"

echo "Starting Cloudflare tunnel..."

cloudflared tunnel --url http://oai:${oai_port:-11434} --no-autoupdate 2>&1 | tee /tmp/tunnel.log &

TUNNEL_PID=$!

sleep 5

TUNNEL_URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' /tmp/tunnel.log | head -1)

if [ -z "$TUNNEL_URL" ]; then
    echo "Waiting longer for tunnel URL..."
    sleep 10
    TUNNEL_URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' /tmp/tunnel.log | head -1)
fi

if [ -n "$TUNNEL_URL" ]; then
    echo "$TUNNEL_URL" > "$URL_FILE"
    echo "Tunnel URL: $TUNNEL_URL"
    echo "URL saved to $URL_FILE"
else
    echo "ERROR: Could not extract tunnel URL"
    cat /tmp/tunnel.log
    exit 1
fi

wait $TUNNEL_PID
