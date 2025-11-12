FROM alpine:latest

RUN apk add --no-cache curl ca-certificates && \
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && \
    chmod +x /usr/local/bin/cloudflared && \
    apk del curl

COPY start_tunnel.sh /start_tunnel.sh
RUN chmod +x /start_tunnel.sh

CMD ["/start_tunnel.sh"]
