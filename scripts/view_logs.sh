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
#   ./scripts/view_logs.sh --host 192.168.1.50 --user root
#
# Options:
#   --host <hostname>       SSH host for Home Assistant (default: homeassistant.local)
#   --user <username>       SSH user (default: root)
#   --tail <n>              Show last n lines instead of live tail
#   --follow, -f            Tail logs in real-time (default behavior)
#   --pretty, -p            Format logs for better readability (removes date, thread info)
#   --help, -h              Show this help text

set -euo pipefail

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
}

HA_HOST="ha"
HA_USER=""
MODE="follow"
TAIL_LINES=20
PRETTY=false

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
    sed -E 's/^[0-9]{4}-[0-9]{2}-[0-9]{2} ([0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}) ([A-Z]+) \([^)]+\) \[[^]]+\] /\1 \2 /'
}

if [[ "$MODE" == "follow" ]]; then
    echo "Tailing live logs from $REMOTE_TARGET (filtering for 'frame_art')..."
    if [[ "$PRETTY" == "true" ]]; then
        echo "(pretty formatting enabled)"
    fi
    echo "Press Ctrl+C to exit"
    echo ""
    if [[ "$PRETTY" == "true" ]]; then
        ssh "$REMOTE_TARGET" "tail -f /config/home-assistant.log" | grep --line-buffered -i frame_art | pretty_format
    else
        ssh "$REMOTE_TARGET" "tail -f /config/home-assistant.log" | grep --line-buffered -i frame_art
    fi
else
    echo "Showing last $TAIL_LINES log lines from $REMOTE_TARGET (filtering for 'frame_art')..."
    if [[ "$PRETTY" == "true" ]]; then
        echo "(pretty formatting enabled)"
    fi
    echo ""
    if [[ "$PRETTY" == "true" ]]; then
        ssh "$REMOTE_TARGET" "grep -i 'frame_art' /config/home-assistant.log | tail -$TAIL_LINES" | pretty_format
    else
        ssh "$REMOTE_TARGET" "grep -i 'frame_art' /config/home-assistant.log | tail -$TAIL_LINES"
    fi
fi
