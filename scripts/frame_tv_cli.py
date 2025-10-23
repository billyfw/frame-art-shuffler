#!/usr/bin/env python3
"""Command-line helper for Samsung Frame TV actions."""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

# Silence SSL certificate warnings from urllib3 (Samsung TVs use self-signed certs)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# Ensure we can import the integration helper when executed from repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.frame_art_shuffler.frame_tv import (  # noqa: E402
    FrameArtError,
    set_art_on_tv_deleteothers,
    set_tv_brightness,
    is_art_mode_enabled,
    is_screen_on,
    is_tv_on,  # Keep for backwards compatibility
    tv_on,
    tv_off,
    set_art_mode,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Samsung Frame TV helper commands (art-focused control)",
        epilog="This CLI provides standalone art management for Frame TVs. "
               "Power commands (on/off) control screen state while staying in art mode."
    )
    parser.add_argument("ip", help="IP address of the Frame TV")

    subparsers = parser.add_subparsers(dest="command", required=True)

    upload = subparsers.add_parser(
        "upload", 
        help="Upload artwork and optionally delete others",
        description="Upload artwork to Frame TV. Example: %(prog)s upload /path/to/art.jpg --delete-others --brightness 5"
    )
    upload.add_argument("artpath", help="Path to the artwork file (.jpg/.png)")
    upload.add_argument("--delete-others", action="store_true", help="Delete other artworks after upload (default: keep existing)")
    upload.add_argument("--matte", help="Optional matte identifier (e.g., 'shadowbox_black')")
    upload.add_argument("--skip-ensure-art", action="store_true", help="Skip enabling art mode before upload")
    upload.add_argument("--brightness", type=int, help="Set brightness after upload (1-10 for standard, 50 for max)")
    upload.add_argument("--debug", action="store_true", help="Enable verbose debug logging")

    subparsers.add_parser("on", help="Turn screen on (stays in art mode)")
    subparsers.add_parser("off", help="Turn screen off (stays in art mode - holds KEY_POWER for 3s)")
    subparsers.add_parser("art-mode", help="Switch TV to art mode (if currently in TV mode)")
    subparsers.add_parser("status", help="Check if art mode is enabled")
    subparsers.add_parser("screen-status", help="Check if screen is on (displaying content)")

    brightness = subparsers.add_parser("brightness", help="Set art-mode brightness (1-10 or 50)")
    brightness.add_argument("value", type=int, help="Brightness level")

    if len(sys.argv) == 1:
        parser.print_help()
        parser.exit()

    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    ip = args.ip

    try:
        if args.command == "upload":
            content_id = set_art_on_tv_deleteothers(
                ip,i still 
                args.artpath,
                delete_others=args.delete_others,
                ensure_art_mode=not args.skip_ensure_art,
                matte=args.matte,
                brightness=args.brightness,
                debug=args.debug,
            )
            print(f"Uploaded artwork. Content ID: {content_id}")
            return 0

        if args.command == "on":
            tv_on(ip)
            print("Screen on (command sent if screen was off)")
            return 0

        if args.command == "off":
            tv_off(ip)
            print("Screen off (KEY_POWER hold sent)")
            return 0

        if args.command == "art-mode":
            set_art_mode(ip)
            print("TV switched to art mode")
            return 0

        if args.command == "status":
            if is_art_mode_enabled(ip):
                print("Art mode is enabled")
                return 0
            print("Art mode is not enabled")
            return 1

        if args.command == "screen-status":
            if is_screen_on(ip):
                print("Screen is on (displaying content)")
                return 0
            print("Screen is off (standby/power saving)")
            return 1

        if args.command == "brightness":
            set_tv_brightness(ip, args.value)
            print(f"Brightness set to {args.value}")
            return 0

    except FrameArtError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
