#!/bin/bash
set -e

LOG_DIR="/var/log/janitor"
CLEANUP_SCRIPT="/app/cleanup.sh"
DATA_DIR="${DATA_DIR:-/app/data}"
ARCHIVE_DIR="${ARCHIVE_DIR:-/app/archives}"
CLEANUP_INTERVAL_HOURS="${CLEANUP_INTERVAL_HOURS:-24}"

mkdir -p "$LOG_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Janitor service starting..." | tee -a "$LOG_DIR/janitor.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuration:" | tee -a "$LOG_DIR/janitor.log"
echo "  - Data directory: $DATA_DIR" | tee -a "$LOG_DIR/janitor.log"
echo "  - Archive directory: $ARCHIVE_DIR" | tee -a "$LOG_DIR/janitor.log"
echo "  - Cleanup interval: ${CLEANUP_INTERVAL_HOURS}h" | tee -a "$LOG_DIR/janitor.log"
echo "  - Max data size: ${MAX_DATA_SIZE_MB:-1024}MB" | tee -a "$LOG_DIR/janitor.log"
echo "  - Max file age: ${MAX_FILE_AGE_DAYS:-30} days" | tee -a "$LOG_DIR/janitor.log"
echo "  - Archive retention: ${ARCHIVE_RETENTION_DAYS:-90} days" | tee -a "$LOG_DIR/janitor.log"

mkdir -p "$DATA_DIR" "$ARCHIVE_DIR"

if [ ! -f "$CLEANUP_SCRIPT" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Cleanup script not found at $CLEANUP_SCRIPT" | tee -a "$LOG_DIR/janitor.log"
    exit 1
fi

if [ ! -x "$CLEANUP_SCRIPT" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Cleanup script is not executable" | tee -a "$LOG_DIR/janitor.log"
    exit 1
fi

CLEANUP_HOUR=2
CLEANUP_MINUTE=0

if [ "$CLEANUP_INTERVAL_HOURS" -lt 24 ]; then
    CRON_SCHEDULE="0 */${CLEANUP_INTERVAL_HOURS} * * *"
else
    CRON_SCHEDULE="${CLEANUP_MINUTE} ${CLEANUP_HOUR} * * *"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron schedule: $CRON_SCHEDULE" | tee -a "$LOG_DIR/janitor.log"

CRON_FILE="/tmp/janitor-cron"
cat > "$CRON_FILE" <<EOF
# Janitor cleanup cron job
# Runs cleanup script at configured interval
${CRON_SCHEDULE} /app/cleanup.sh >> ${LOG_DIR}/cleanup.log 2>&1

# Logrotate runs daily at 3 AM
0 3 * * * /usr/sbin/logrotate -f /etc/logrotate.d/outlier-data >> ${LOG_DIR}/logrotate.log 2>&1

# Health check - touch a file every 5 minutes to show service is alive
*/5 * * * * touch ${LOG_DIR}/heartbeat && echo "[$(date '+%Y-%m-%d %H:%M:%S')] Heartbeat" >> ${LOG_DIR}/heartbeat.log

EOF

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Crontab configuration:" | tee -a "$LOG_DIR/janitor.log"
cat "$CRON_FILE" | tee -a "$LOG_DIR/janitor.log"

if [ "${RUN_ON_STARTUP:-true}" = "true" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running initial cleanup..." | tee -a "$LOG_DIR/janitor.log"
    "$CLEANUP_SCRIPT" || echo "[$(date '+%Y-%m-%d %H:%M:%S')] Initial cleanup completed with warnings" | tee -a "$LOG_DIR/janitor.log"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting monitoring loop..." | tee -a "$LOG_DIR/janitor.log"

INTERVAL_SECONDS=$((CLEANUP_INTERVAL_HOURS * 3600))

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running scheduled cleanup..." | tee -a "$LOG_DIR/janitor.log"

    if "$CLEANUP_SCRIPT"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup completed successfully" | tee -a "$LOG_DIR/janitor.log"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup completed with errors" | tee -a "$LOG_DIR/janitor.log"
    fi

    touch "$LOG_DIR/heartbeat"

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Next cleanup in ${CLEANUP_INTERVAL_HOURS} hours" | tee -a "$LOG_DIR/janitor.log"
    sleep "$INTERVAL_SECONDS"
done
