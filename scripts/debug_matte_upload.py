#!/usr/bin/env python3
"""Debug script for testing Samsung Frame TV matte upload functionality.

This script uses the REAL upload function from frame_tv.py (set_art_on_tv_deleteothers)
to test matte uploads, ensuring we test the actual code path.

Usage:
    # Test upload with no matte (baseline - should always work)
    python scripts/debug_matte_upload.py 192.168.1.249 ~/jz.jpg
    
    # Test upload with a specific matte
    python scripts/debug_matte_upload.py 192.168.1.249 ~/jz.jpg --matte modern_warm
    
    # List available mattes from TV
    python scripts/debug_matte_upload.py 192.168.1.249 --list-mattes
    
    # Show current artwork on TV
    python scripts/debug_matte_upload.py 192.168.1.249 --current
    
    # Verbose debug output
    python scripts/debug_matte_upload.py 192.168.1.249 ~/jz.jpg --matte modern_warm --debug
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

# Silence SSL certificate warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# Ensure we can import from the repo
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.frame_art_shuffler.samsungtvws.art import SamsungTVArt
from custom_components.frame_art_shuffler.frame_tv import (
    set_art_on_tv_deleteothers,
    FrameArtError,
    _token_path,  # Use the same token path function as frame_tv.py
)

TOKEN_DIR = REPO_ROOT / "custom_components" / "frame_art_shuffler" / "tokens"
CLIENT_NAME = "FrameArtShuffler"  # Must match frame_tv.py


def get_token_file(ip: str) -> Path:
    """Use same token path logic as frame_tv.py (underscores, not dots)."""
    return _token_path(ip)


def list_mattes(ip: str):
    """Query and display all available mattes from the TV."""
    print(f"\n{'='*60}")
    print(f"Querying mattes from {ip}...")
    print(f"{'='*60}\n")
    
    art = SamsungTVArt(ip, token_file=str(get_token_file(ip)), port=8002, timeout=15, name=CLIENT_NAME)
    art.open()
    
    try:
        matte_types, matte_colors = art.get_matte_list(include_colour=True)
        
        types = [m['matte_type'] for m in matte_types]
        colors = [c['color'] for c in matte_colors]
        
        print("MATTE TYPES:")
        for t in types:
            print(f"  - {t}")
        
        print(f"\nMATTE COLORS ({len(colors)} total):")
        for c in colors:
            print(f"  - {c}")
        
        print(f"\n{'='*60}")
        print("VALID MATTE_ID VALUES (format: type_color)")
        print(f"{'='*60}")
        print("  none")
        for t in types:
            if t == 'none':
                continue
            for c in colors:
                print(f"  {t}_{c}")
                
    finally:
        art.close()


def get_current_artwork(ip: str):
    """Get current artwork info."""
    art = SamsungTVArt(ip, token_file=str(get_token_file(ip)), port=8002, timeout=15, name=CLIENT_NAME)
    art.open()
    
    try:
        current = art.get_current()
        print(f"\nCurrent artwork on TV:")
        print(json.dumps(current, indent=2))
        return current
    finally:
        art.close()


def upload_with_matte(ip: str, artpath: str, matte: str | None, debug: bool = False):
    """
    Upload artwork using the REAL set_art_on_tv_deleteothers function.
    
    This tests the actual code path used by the integration.
    """
    print(f"\n{'='*60}")
    print(f"UPLOAD TEST")
    print(f"{'='*60}")
    print(f"  IP:     {ip}")
    print(f"  Image:  {artpath}")
    print(f"  Matte:  {matte or 'none (not specified)'}")
    print(f"  Debug:  {debug}")
    print(f"{'='*60}\n")
    
    try:
        content_id = set_art_on_tv_deleteothers(
            ip,
            artpath,
            delete_others=False,  # Don't delete other images during testing!
            ensure_art_mode=True,
            matte=matte,
            debug=debug,
        )
        print(f"\n✅ SUCCESS!")
        print(f"   Content ID: {content_id}")
        print(f"\n   >>> Check the TV now - does the image display correctly with matte '{matte or 'none'}'? <<<")
        return True
        
    except FrameArtError as err:
        print(f"\n❌ FAILED: {err}")
        return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Debug Samsung Frame TV matte upload functionality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Baseline test (no matte)
  python scripts/debug_matte_upload.py 192.168.1.249 ~/jz.jpg
  
  # Test with matte
  python scripts/debug_matte_upload.py 192.168.1.249 ~/jz.jpg --matte modern_warm
  
  # List available mattes
  python scripts/debug_matte_upload.py 192.168.1.249 --list-mattes
  
  # Check current artwork
  python scripts/debug_matte_upload.py 192.168.1.249 --current
"""
    )
    parser.add_argument("ip", help="IP address of the Frame TV")
    parser.add_argument("artpath", nargs="?", help="Path to artwork file")
    parser.add_argument("--matte", help="Matte ID (e.g., 'modern_warm', 'shadowbox_polar')")
    parser.add_argument("--list-mattes", action="store_true", help="List available mattes from TV")
    parser.add_argument("--current", action="store_true", help="Show current artwork on TV")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    
    # Configure logging
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG, 
            format='%(levelname)s %(name)s: %(message)s'
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format='%(message)s'
        )
    
    # Handle info commands
    if args.list_mattes:
        list_mattes(args.ip)
        return 0
    
    if args.current:
        get_current_artwork(args.ip)
        return 0
    
    # Upload command requires artpath
    if not args.artpath:
        print("ERROR: artpath is required for upload")
        print("       Use --list-mattes or --current for info commands")
        return 1
    
    # Do the upload
    success = upload_with_matte(args.ip, args.artpath, args.matte, args.debug)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
