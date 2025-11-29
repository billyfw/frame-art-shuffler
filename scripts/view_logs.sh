#!/bin/bash

# Frame Art Shuffler log viewer script
#
# This helper tails the Home Assistant logs and filters for frame_art_shuffler entries.
#
# Usage examples:
#   ./scripts/view_logs.sh              # tail live logs (default)
#   ./scripts/view_logs.sh --tail 50    # show last 50 lines
#   ./scripts/view_logs.sh --follow     # tail live logs (explicit)
#   ./scripts/view_logs.sh --pretty     # format logs for readability
#   ./scripts/view_logs.sh --level INFO # show only INFO, WARNING, ERROR
#   ./scripts/view_logs.sh --truncate 200 # truncate lines to 200 chars
#   ./scripts/view_logs.sh --host 192.168.1.50 --user root
#
# Options:
#   --host <hostname>       SSH host for Home Assistant (default: ha)
#   --user <username>       SSH user (default: root)
#   --tail <n>              Show last n lines instead of live tail
#   --follow, -f            Tail logs in real-time (default behavior)
#   --pretty, -p            Format logs for better readability (removes date, thread info)
#   --level <level>         Filter by log level (DEBUG, INFO, WARNING, ERROR)
#   --truncate <n>          Truncate lines to n characters
#   --help, -h              Show this help text

set -euo pipefail

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
}

HA_HOST="ha"
HA_USER=""
MODE="follow"
TAIL_LINES=20
PRETTY=true
LOG_LEVEL="INFO"
TRUNCATE_WIDTH=200

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            HA_HOST="$2"
            shift 2
            ;;
        --user)
            HA_USER="$2"
            shift 2
            ;;
        --tail)
            MODE="tail"
            TAIL_LINES="$2"
            shift 2
            ;;
        --follow|-f)
            MODE="follow"
            shift
            ;;
        --pretty|-p)
            PRETTY=true
            shift
            ;;
        --level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        --truncate)
            TRUNCATE_WIDTH="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo
            usage
            exit 1
            ;;
    esac
done

if [[ -n "$HA_USER" ]]; then
    REMOTE_TARGET="$HA_USER@$HA_HOST"
else
    REMOTE_TARGET="$HA_HOST"
fi

# Pretty formatting function that removes date and thread info
# Transforms: 2025-11-03 09:44:40.049 WARNING (SyncWorker_16) [custom_components.frame_art_shuffler.button] Message
# Into:       09:44:40.049 WARNING Message
pretty_format() {
    # Use perl for consistent line buffering across platforms ($|=1)
    perl -pe '$|=1; s/^[0-9]{4}-[0-9]{2}-[0-9]{2} ([0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}) ([A-Z]+) \([^)]+\) \[[^]]+\] /$1 $2 /'
}

# Construct the filter pipeline
build_pipeline() {
    local pipeline="cat"
    
    # 1. Filter for frame_art
    pipeline="$pipeline | grep --line-buffered -i frame_art"
    
    # 2. Filter by level if requested
    if [[ -n "$LOG_LEVEL" ]]; then
        case "$(echo "$LOG_LEVEL" | tr '[:lower:]' '[:upper:]')" in
            INFO)
                pipeline="$pipeline | grep --line-buffered -E 'INFO|WARNING|ERROR|CRITICAL'"
                ;;
            WARN|WARNING)
                pipeline="$pipeline | grep --line-buffered -E 'WARNING|ERROR|CRITICAL'"
                ;;
            ERROR)
                pipeline="$pipeline | grep --line-buffered -E 'ERROR|CRITICAL'"
                ;;
            DEBUG)
                # No extra filtering needed
                ;;
            *)
                echo "Warning: Unknown log level '$LOG_LEVEL', ignoring." >&2
                ;;
        esac
    fi
    
    # 3. Pretty print if requested
    if [[ "$PRETTY" == "true" ]]; then
        pipeline="$pipeline | pretty_format"
    fi
    
    # 4. Truncate if requested
    if [[ "$TRUNCATE_WIDTH" -gt 0 ]]; then
        # Use awk with fflush() to prevent buffering issues that cut might have
        pipeline="$pipeline | awk '{print substr(\$0, 1, ${TRUNCATE_WIDTH}); fflush()}'"
    fi
    
    echo "$pipeline"
}

PIPELINE_CMD=$(build_pipeline)

if [[ "$MODE" == "follow" ]]; then
    echo "Tailing live logs from $REMOTE_TARGET..."
    echo "  Filter: frame_art"
    [[ -n "$LOG_LEVEL" ]] && echo "  Level: $LOG_LEVEL+"
    [[ "$PRETTY" == "true" ]] && echo "  Format: Pretty"
    [[ "$TRUNCATE_WIDTH" -gt 0 ]] && echo "  Truncate: ${TRUNCATE_WIDTH} chars"
    echo "Press Ctrl+C to exit"
    echo ""
    
    # We execute the pipeline locally on the output of ssh
    ssh "$REMOTE_TARGET" "tail -f /config/home-assistant.log" | eval "$PIPELINE_CMD"
else
    echo "Showing last $TAIL_LINES log lines from $REMOTE_TARGET..."
    echo ""
    
    # For tail mode, we grep on the server side first to ensure we get relevant lines
    # then apply formatting/truncation locally
    ssh "$REMOTE_TARGET" "grep -i 'frame_art' /config/home-assistant.log | tail -$TAIL_LINES" | \
    eval "$(echo "$PIPELINE_CMD" | sed 's/grep --line-buffered -i frame_art/cat/')" 
    # Note: removed the first grep from pipeline since we did it on server
fi
