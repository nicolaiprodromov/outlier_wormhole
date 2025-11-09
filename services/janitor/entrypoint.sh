#!/bin/bash

###########################################
# Janitor Service Entrypoint
# Sets up cron and monitoring for cleanup tasks
###########################################

set -e

# Configuration
LOG_DIR="/var/log/janitor"
CLEANUP_SCRIPT="/app/cleanup.sh"
DATA_DIR="${DATA_DIR:-/app/data}"
ARCHIVE_DIR="${ARCHIVE_DIR:-/app/archives}"
CLEANUP_INTERVAL_HOURS="${CLEANUP_INTERVAL_HOURS:-24}"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Log startup
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Janitor service starting..." | tee -a "$LOG_DIR/janitor.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuration:" | tee -a "$LOG_DIR/janitor.log"
echo "  - Data directory: $DATA_DIR" | tee -a "$LOG_DIR/janitor.log"
echo "  - Archive directory: $ARCHIVE_DIR" | tee -a "$LOG_DIR/janitor.log"
echo "  - Cleanup interval: ${CLEANUP_INTERVAL_HOURS}h" | tee -a "$LOG_DIR/janitor.log"
echo "  - Max data size: ${MAX_DATA_SIZE_MB:-1024}MB" | tee -a "$LOG_DIR/janitor.log"
echo "  - Max file age: ${MAX_FILE_AGE_DAYS:-30} days" | tee -a "$LOG_DIR/janitor.log"
echo "  - Archive retention: ${ARCHIVE_RETENTION_DAYS:-90} days" | tee -a "$LOG_DIR/janitor.log"

# Create data and archive directories if they don't exist
mkdir -p "$DATA_DIR" "$ARCHIVE_DIR"

# Verify cleanup script exists and is executable
if [ ! -f "$CLEANUP_SCRIPT" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Cleanup script not found at $CLEANUP_SCRIPT" | tee -a "$LOG_DIR/janitor.log"
    exit 1
fi

if [ ! -x "$CLEANUP_SCRIPT" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Cleanup script is not executable" | tee -a "$LOG_DIR/janitor.log"
    exit 1
fi

# Calculate cron schedule
# Format: minute hour * * *
# Default: run once every 24 hours at 2 AM
CLEANUP_HOUR=2
CLEANUP_MINUTE=0

# If interval is less than 24 hours, calculate hourly schedule
if [ "$CLEANUP_INTERVAL_HOURS" -lt 24 ]; then
    CRON_SCHEDULE="0 */${CLEANUP_INTERVAL_HOURS} * * *"
else
    # For 24+ hours, run daily at 2 AM
    CRON_SCHEDULE="${CLEANUP_MINUTE} ${CLEANUP_HOUR} * * *"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron schedule: $CRON_SCHEDULE" | tee -a "$LOG_DIR/janitor.log"

# Create temporary crontab file
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

# Run initial cleanup on startup (optional, can be controlled by env var)
if [ "${RUN_ON_STARTUP:-true}" = "true" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running initial cleanup..." | tee -a "$LOG_DIR/janitor.log"
    "$CLEANUP_SCRIPT" || echo "[$(date '+%Y-%m-%d %H:%M:%S')] Initial cleanup completed with warnings" | tee -a "$LOG_DIR/janitor.log"
fi

# Setup monitoring loop that runs the cleanup script
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting monitoring loop..." | tee -a "$LOG_DIR/janitor.log"

# Convert hours to seconds
INTERVAL_SECONDS=$((CLEANUP_INTERVAL_HOURS * 3600))

# Main monitoring loop
while true; do
    # Run the cleanup script
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running scheduled cleanup..." | tee -a "$LOG_DIR/janitor.log"

    if "$CLEANUP_SCRIPT"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup completed successfully" | tee -a "$LOG_DIR/janitor.log"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup completed with errors" | tee -a "$LOG_DIR/janitor.log"
    fi

    # Update heartbeat
    touch "$LOG_DIR/heartbeat"

    # Wait for next interval
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Next cleanup in ${CLEANUP_INTERVAL_HOURS} hours" | tee -a "$LOG_DIR/janitor.log"
    sleep "$INTERVAL_SECONDS"
done
