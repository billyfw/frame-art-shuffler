#!/bin/bash

# Frame Art Shuffler log viewer script
#
# This helper tails the Home Assistant logs and filters for frame_art_shuffler entries.
#
# Usage examples:
#   ./scripts/view_logs.sh              # tail live logs (default)
#   ./scripts/view_logs.sh --tail 50    # show last 50 lines
#   ./scripts/view_logs.sh --follow     # tail live logs (explicit)
#   ./scripts/view_logs.sh --host 192.168.1.50 --user root
#
# Options:
#   --host <hostname>       SSH host for Home Assistant (default: homeassistant.local)
#   --user <username>       SSH user (default: root)
#   --tail <n>              Show last n lines instead of live tail
#   --follow, -f            Tail logs in real-time (default behavior)
#   --help, -h              Show this help text

set -euo pipefail

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
}

HA_HOST="homeassistant.local"
HA_USER="root"
MODE="follow"
TAIL_LINES=20

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

REMOTE_TARGET="$HA_USER@$HA_HOST"

if [[ "$MODE" == "follow" ]]; then
    echo "Tailing live logs from $REMOTE_TARGET (filtering for 'frame_art')..."
    echo "Press Ctrl+C to exit"
    echo ""
    ssh "$REMOTE_TARGET" "tail -f /config/home-assistant.log" | grep --line-buffered -i frame_art
else
    echo "Showing last $TAIL_LINES log lines from $REMOTE_TARGET (filtering for 'frame_art')..."
    echo ""
    ssh "$REMOTE_TARGET" "grep -i 'frame_art' /config/home-assistant.log | tail -$TAIL_LINES"
fi
