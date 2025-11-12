#!/bin/bash

set -euo pipefail

DATA_DIR="${DATA_DIR:-/app/data}"
ARCHIVE_DIR="${ARCHIVE_DIR:-/app/archives}"
MAX_DATA_SIZE_MB="${MAX_DATA_SIZE_MB:-1024}"
MAX_FILE_AGE_DAYS="${MAX_FILE_AGE_DAYS:-30}"
ARCHIVE_RETENTION_DAYS="${ARCHIVE_RETENTION_DAYS:-90}"
LOG_FILE="${LOG_FILE:-/var/log/janitor/cleanup.log}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

if [ ! -d "$DATA_DIR" ]; then
    log "ERROR: Data directory $DATA_DIR does not exist"
    exit 1
fi

mkdir -p "$ARCHIVE_DIR"

log "=========================================="
log "Starting cleanup process"
log "Data dir: $DATA_DIR"
log "Archive dir: $ARCHIVE_DIR"
log "Max size: ${MAX_DATA_SIZE_MB}MB"
log "Max age: ${MAX_FILE_AGE_DAYS} days"
log "Archive retention: ${ARCHIVE_RETENTION_DAYS} days"

get_dir_size_mb() {
    du -sm "$1" 2>/dev/null | cut -f1 || echo 0
}

archive_old_conversations() {
    log "Checking for old conversation directories..."

    local archived_count=0
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local archive_file="${ARCHIVE_DIR}/conversations_${timestamp}.tar.gz"

    while IFS= read -r -d '' conv_dir; do
        if [ -d "$conv_dir" ] && [ "$(basename "$conv_dir")" != "raw_dumps" ]; then
            local mod_time=$(stat -c %Y "$conv_dir" 2>/dev/null || stat -f %m "$conv_dir" 2>/dev/null || echo 0)
            local current_time=$(date +%s)
            local age_days=$(( (current_time - mod_time) / 86400 ))

            if [ "$age_days" -gt "$MAX_FILE_AGE_DAYS" ]; then
                log "Found old conversation: $(basename "$conv_dir") (${age_days} days old)"

                tar -czf "$archive_file" -C "$DATA_DIR" "$(basename "$conv_dir")" 2>/dev/null || \
                tar -rf "${archive_file%.gz}" -C "$DATA_DIR" "$(basename "$conv_dir")" 2>/dev/null

                if [ $? -eq 0 ]; then
                    rm -rf "$conv_dir"
                    archived_count=$((archived_count + 1))
                    log "Archived and removed: $(basename "$conv_dir")"
                else
                    log "WARNING: Failed to archive $(basename "$conv_dir")"
                fi
            fi
        fi
    done < <(find "$DATA_DIR" -maxdepth 1 -type d -print0 2>/dev/null)

    if [ -f "${archive_file%.gz}" ] && [ ! -f "$archive_file" ]; then
        gzip "${archive_file%.gz}"
    fi

    log "Archived $archived_count old conversation(s)"
}

cleanup_raw_dumps() {
    log "Cleaning up old raw dumps..."

    local raw_dumps_dir="${DATA_DIR}/raw_dumps"

    if [ ! -d "$raw_dumps_dir" ]; then
        log "No raw_dumps directory found, skipping"
        return
    fi

    local deleted_count=0

    while IFS= read -r -d '' file; do
        local mod_time=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null || echo 0)
        local current_time=$(date +%s)
        local age_days=$(( (current_time - mod_time) / 86400 ))

        if [ "$age_days" -gt "$MAX_FILE_AGE_DAYS" ]; then
            rm -f "$file"
            deleted_count=$((deleted_count + 1))
        fi
    done < <(find "$raw_dumps_dir" -type f -name "*.md" -print0 2>/dev/null)

    log "Deleted $deleted_count old raw dump file(s)"
}

enforce_size_limit() {
    log "Checking data directory size..."

    local current_size=$(get_dir_size_mb "$DATA_DIR")
    log "Current data size: ${current_size}MB / ${MAX_DATA_SIZE_MB}MB"

    if [ "$current_size" -le "$MAX_DATA_SIZE_MB" ]; then
        log "Data size within limits"
        return
    fi

    log "WARNING: Data size exceeds limit, removing oldest conversations..."

    local removed_count=0
    while [ "$(get_dir_size_mb "$DATA_DIR")" -gt "$MAX_DATA_SIZE_MB" ]; do
        local oldest_dir=$(find "$DATA_DIR" -maxdepth 1 -type d ! -name "raw_dumps" ! -path "$DATA_DIR" -printf '%T+ %p\n' 2>/dev/null | \
                          sort | head -n 1 | cut -d' ' -f2-)

        if [ -z "$oldest_dir" ] || [ ! -d "$oldest_dir" ]; then
            log "No more conversation directories to remove"
            break
        fi

        local dir_name=$(basename "$oldest_dir")
        log "Removing oldest conversation: $dir_name"

        local timestamp=$(date +%Y%m%d_%H%M%S)
        tar -czf "${ARCHIVE_DIR}/emergency_${dir_name}_${timestamp}.tar.gz" -C "$DATA_DIR" "$dir_name" 2>/dev/null || true

        rm -rf "$oldest_dir"
        removed_count=$((removed_count + 1))
    done

    log "Removed $removed_count conversation(s) to enforce size limit"
    log "New data size: $(get_dir_size_mb "$DATA_DIR")MB"
}

cleanup_old_archives() {
    log "Cleaning up old archives..."

    if [ ! -d "$ARCHIVE_DIR" ]; then
        log "No archive directory found, skipping"
        return
    fi

    local deleted_count=0

    while IFS= read -r -d '' archive; do
        local mod_time=$(stat -c %Y "$archive" 2>/dev/null || stat -f %m "$archive" 2>/dev/null || echo 0)
        local current_time=$(date +%s)
        local age_days=$(( (current_time - mod_time) / 86400 ))

        if [ "$age_days" -gt "$ARCHIVE_RETENTION_DAYS" ]; then
            log "Deleting old archive: $(basename "$archive") (${age_days} days old)"
            rm -f "$archive"
            deleted_count=$((deleted_count + 1))
        fi
    done < <(find "$ARCHIVE_DIR" -type f -name "*.tar.gz" -print0 2>/dev/null)

    log "Deleted $deleted_count old archive(s)"
}

generate_report() {
    log "=========================================="
    log "Cleanup Report:"
    log "Data directory size: $(get_dir_size_mb "$DATA_DIR")MB"
    log "Archive directory size: $(get_dir_size_mb "$ARCHIVE_DIR")MB"

    local conv_count=$(find "$DATA_DIR" -maxdepth 1 -type d ! -path "$DATA_DIR" ! -name "raw_dumps" 2>/dev/null | wc -l)
    log "Active conversations: $conv_count"

    local archive_count=$(find "$ARCHIVE_DIR" -type f -name "*.tar.gz" 2>/dev/null | wc -l)
    log "Archived files: $archive_count"

    log "=========================================="
}

main() {
    log "Janitor cleanup script started"

    if command -v logrotate >/dev/null 2>&1; then
        log "Running logrotate..."
        logrotate -f /etc/logrotate.d/outlier-data 2>&1 | tee -a "$LOG_FILE" || log "Logrotate completed with warnings"
    fi

    archive_old_conversations

    cleanup_raw_dumps

    enforce_size_limit

    cleanup_old_archives

    generate_report

    log "Cleanup process completed successfully"
}

main
