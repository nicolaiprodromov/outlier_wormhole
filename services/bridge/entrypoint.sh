#!/bin/bash
set -e

python -u ws_proxy.py &
PROXY_PID=$!

python -u wormhole.py &
WORMHOLE_PID=$!

trap "echo '[Bridge] Shutting down...'; kill $PROXY_PID $WORMHOLE_PID 2>/dev/null; exit 0" SIGTERM SIGINT

wait $PROXY_PID $WORMHOLE_PID
