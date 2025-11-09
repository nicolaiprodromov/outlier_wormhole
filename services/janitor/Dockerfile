FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    logrotate \
    tzdata \
    findutils \
    coreutils \
    gzip \
    tar \
    && rm -rf /var/cache/apk/*

RUN adduser -D -u 1002 -h /home/janitor janitor

WORKDIR /app

COPY cleanup.sh /app/cleanup.sh
COPY logrotate.conf /etc/logrotate.d/outlier-data
COPY entrypoint.sh /app/entrypoint.sh

RUN mkdir -p /app/data /app/archives /var/log/janitor \
    && chown -R janitor:janitor /app /var/log/janitor \
    && chmod +x /app/cleanup.sh /app/entrypoint.sh \
    && chmod 644 /etc/logrotate.d/outlier-data \
    && sed -i 's/\r$//' /app/cleanup.sh \
    && sed -i 's/\r$//' /app/entrypoint.sh

USER janitor

ENV CLEANUP_INTERVAL_HOURS=24 \
    MAX_DATA_SIZE_MB=1024 \
    MAX_FILE_AGE_DAYS=30 \
    ARCHIVE_RETENTION_DAYS=90 \
    TZ=UTC

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD test -f /app/cleanup.sh && test -x /app/cleanup.sh || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
