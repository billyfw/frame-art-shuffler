#!/bin/bash

# Frame Art Shuffler quick-deploy script
#
# This helper bumps the manifest version to a unique dev build, syncs the
# integration files to Home Assistant, and optionally reloads the config entry
# or restarts Home Assistant. It is intended for rapid iteration without
# publishing a release.
#
# Usage examples:
#   ./scripts/dev_deploy.sh                 # bump to <base>+devTIMESTAMP, copy, reload entry
#   ./scripts/dev_deploy.sh --no-bump       # keep manifest version, just copy and reload
#   ./scripts/dev_deploy.sh --version 0.1.0-dev1
#   ./scripts/dev_deploy.sh --restart       # copy and restart Home Assistant core
#   ./scripts/dev_deploy.sh --host 192.168.1.50 --user root
#
# Options:
#   --host <hostname>       SSH host for Home Assistant (default: homeassistant.local)
#   --user <username>       SSH user (default: root)
#   --path <path>           Remote path for the component
#                           (default: /config/custom_components/frame_art_shuffler)
#   --no-bump               Do not change manifest version
#   --version <value>       Force manifest version to a specific value
#   --restart               Run "ha core restart" after copying (implies --no-reload)
#   --no-reload             Skip attempting to reload the config entry via ha CLI
#   --help                  Show this help text

set -euo pipefail

usage() {
    grep '^#' "$0" | sed 's/^# \{0,1\}//'
}

HA_HOST="homeassistant.local"
HA_USER="root"
REMOTE_PATH="/config/custom_components/frame_art_shuffler"
BUMP_VERSION=true
CUSTOM_VERSION=""
RESTART_CORE=false
RELOAD_ENTRY=true

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
        --path)
            REMOTE_PATH="$2"
            shift 2
            ;;
        --no-bump)
            BUMP_VERSION=false
            shift
            ;;
        --version)
            CUSTOM_VERSION="$2"
            BUMP_VERSION=true
            shift 2
            ;;
        --restart)
            RESTART_CORE=true
            RELOAD_ENTRY=false
            shift
            ;;
        --no-reload)
            RELOAD_ENTRY=false
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPONENT_DIR="$REPO_ROOT/custom_components/frame_art_shuffler"
MANIFEST_JSON="$COMPONENT_DIR/manifest.json"

if [[ ! -f "$MANIFEST_JSON" ]]; then
    echo "manifest.json not found at $MANIFEST_JSON" >&2
    exit 1
fi

CURRENT_VERSION=$(MANIFEST_PATH="$MANIFEST_JSON" python3 - <<'PY'
import json
import os
import pathlib

manifest_path = pathlib.Path(os.environ["MANIFEST_PATH"])
data = json.loads(manifest_path.read_text())
print(data.get("version", "0.0.0"))
PY
)

NEW_VERSION="$CURRENT_VERSION"

if [[ "$BUMP_VERSION" == true ]]; then
    if [[ -n "$CUSTOM_VERSION" ]]; then
        NEW_VERSION="$CUSTOM_VERSION"
    MANIFEST_PATH="$MANIFEST_JSON" NEW_VERSION_VALUE="$CUSTOM_VERSION" python3 - <<'PY'
import json
import os
import pathlib

manifest_path = pathlib.Path(os.environ["MANIFEST_PATH"])
data = json.loads(manifest_path.read_text())
data["version"] = os.environ["NEW_VERSION_VALUE"]
manifest_path.write_text(json.dumps(data, indent=2) + "\n")
PY
    else
    NEW_VERSION=$(MANIFEST_PATH="$MANIFEST_JSON" python3 - <<'PY'
import datetime
import json
import os
import pathlib
import re

manifest_path = pathlib.Path(os.environ["MANIFEST_PATH"])
data = json.loads(manifest_path.read_text())
version = data.get("version", "0.0.0")
base = re.split(r"[+-]", version)[0] or "0.0.0"
timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
new_version = f"{base}+dev{timestamp}"
data["version"] = new_version
manifest_path.write_text(json.dumps(data, indent=2) + "\n")
print(new_version)
PY
)
    fi
fi

echo "Manifest version: $CURRENT_VERSION -> $NEW_VERSION"

REMOTE_PARENT="$(dirname "$REMOTE_PATH")"
COMPONENT_NAME="$(basename "$COMPONENT_DIR")"
REMOTE_TARGET="$HA_USER@$HA_HOST"

echo "Deploying to $REMOTE_TARGET:$REMOTE_PATH"

ssh -T "$REMOTE_TARGET" "mkdir -p '$REMOTE_PARENT' && rm -rf '$REMOTE_PATH'"

tar -C "$COMPONENT_DIR/.." \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.DS_Store' \
    -czf - "$COMPONENT_NAME" \
    | ssh -T "$REMOTE_TARGET" "tar -xzf - -C '$REMOTE_PARENT'"

echo "✅ Files synced"

if [[ "$RELOAD_ENTRY" == true ]]; then
    echo "Checking for existing config entry..."
    ssh -T "$REMOTE_TARGET" <<'ENDSSH'
set -e
CONFIG_ENTRIES_FILE="/config/.storage/core.config_entries"

if ! command -v jq >/dev/null 2>&1; then
    echo "jq not available on the host."
    echo "ℹ️  Reload the integration via Settings → Devices & Services → Frame Art Shuffler → ⋮ → Reload"
    echo "   or rerun with --restart to restart Home Assistant Core."
    exit 0
fi

if [ ! -f "$CONFIG_ENTRIES_FILE" ]; then
    echo "Config entries file not found; add the integration first."
    exit 0
fi

ENTRY_ID=$(jq -r '
    if (.data.entries? // empty) then
        .data.entries[] | select(.domain == "frame_art_shuffler") | .entry_id
    elif (type == "object" and (.data | type) == "array") then
        .data[] | select(.domain == "frame_art_shuffler") | .entry_id
    else empty end
' "$CONFIG_ENTRIES_FILE" 2>/dev/null | head -n 1)

if [ -z "$ENTRY_ID" ] || [ "$ENTRY_ID" = "null" ]; then
    echo "No frame_art_shuffler config entry found."
    echo "Add the integration via Settings → Devices & Services → Add Integration → Frame Art Shuffler"
    exit 0
fi

echo "✅ Found config entry: $ENTRY_ID"
echo ""
echo "To reload the integration:"
echo "  1. Open Settings → Devices & Services"
echo "  2. Find 'Frame Art Shuffler' card"
echo "  3. Click ⋮ (three dots) → Reload"
echo ""
echo "Or rerun this script with --restart to restart Home Assistant Core."
ENDSSH
fi

if [[ "$RESTART_CORE" == true ]]; then
    echo "Restarting Home Assistant core..."
    ssh -T "$REMOTE_TARGET" "ha core restart"
    echo "✅ Restart command sent (Core will be back online in ~30 seconds)"
fi

echo "Done."
