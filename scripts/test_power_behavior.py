#!/usr/bin/env python3
"""Test script to understand Frame TV power and art mode behavior.

This script helps test what actually happens with different commands.
Run each test manually and observe the TV behavior.
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.frame_art_shuffler.frame_tv import (
    is_art_mode_enabled,
    is_screen_on,
    tv_on,
    tv_off,
    set_art_mode,
)


def check_state(ip: str, label: str = "Current state"):
    """Check and print current TV state."""
    print(f"\n{'='*60}")
    print(f"{label}:")
    print(f"{'='*60}")
    
    try:
        art_mode = is_art_mode_enabled(ip)
        print(f"  Art mode: {'ENABLED' if art_mode else 'DISABLED'}")
    except Exception as e:
        print(f"  Art mode: ERROR - {e}")
    
    try:
        screen = is_screen_on(ip)
        print(f"  Screen:   {'ON' if screen else 'OFF'}")
    except Exception as e:
        print(f"  Screen:   ERROR - {e}")
    
    print(f"{'='*60}\n")


def test_tv_off_from_tv_mode(ip: str):
    """Test what happens when we call tv_off() while watching TV."""
    print("\n" + "="*60)
    print("TEST: tv_off() from TV mode")
    print("="*60)
    print("\nMANUAL STEP REQUIRED:")
    print("1. Use your TV remote to switch to watching TV (not art mode)")
    print("2. Make sure TV is showing content (channel, app, etc.)")
    print("3. Press Enter when ready...")
    input()
    
    check_state(ip, "BEFORE tv_off()")
    
    print("Calling tv_off() (holding KEY_POWER for 3 seconds)...")
    tv_off(ip)
    print("Command sent.")
    
    print("\nWaiting 5 seconds for TV to respond...")
    time.sleep(5)
    
    check_state(ip, "AFTER tv_off()")
    
    print("\nDid the screen turn off? [y/n]: ", end='')
    screen_off = input().lower() == 'y'
    
    print("\nObservation: Screen turned off" if screen_off else "Observation: Screen stayed on")


def test_tv_off_from_art_mode(ip: str):
    """Test what happens when we call tv_off() while already in art mode."""
    print("\n" + "="*60)
    print("TEST: tv_off() from art mode")
    print("="*60)
    print("\nMANUAL STEP REQUIRED:")
    print("1. Ensure TV is in art mode (showing artwork)")
    print("2. Press Enter when ready...")
    input()
    
    check_state(ip, "BEFORE tv_off()")
    
    print("Calling tv_off() (holding KEY_POWER for 3 seconds)...")
    tv_off(ip)
    print("Command sent.")
    
    print("\nWaiting 5 seconds for TV to respond...")
    time.sleep(5)
    
    check_state(ip, "AFTER tv_off()")


def test_set_art_mode_from_tv_mode(ip: str):
    """Test what happens when we call set_art_mode() while watching TV."""
    print("\n" + "="*60)
    print("TEST: set_art_mode() from TV mode")
    print("="*60)
    print("\nMANUAL STEP REQUIRED:")
    print("1. Use your TV remote to switch to watching TV (not art mode)")
    print("2. Make sure TV is showing content (channel, app, etc.)")
    print("3. Press Enter when ready...")
    input()
    
    check_state(ip, "BEFORE set_art_mode()")
    
    print("Calling set_art_mode()...")
    try:
        set_art_mode(ip)
        print("Success!")
    except Exception as e:
        print(f"ERROR: {e}")
    
    print("\nWaiting 3 seconds...")
    time.sleep(3)
    
    check_state(ip, "AFTER set_art_mode()")


def test_set_art_mode_from_home_screen(ip: str):
    """Test what happens when we call set_art_mode() from home screen."""
    print("\n" + "="*60)
    print("TEST: set_art_mode() from home screen")
    print("="*60)
    print("\nMANUAL STEP REQUIRED:")
    print("1. Use your TV remote to press HOME button")
    print("2. Make sure you're on the home screen (not watching content)")
    print("3. Press Enter when ready...")
    input()
    
    check_state(ip, "BEFORE set_art_mode()")
    
    print("Calling set_art_mode()...")
    try:
        set_art_mode(ip)
        print("Success!")
    except Exception as e:
        print(f"ERROR: {e}")
    
    print("\nWaiting 3 seconds...")
    time.sleep(3)
    
    check_state(ip, "AFTER set_art_mode()")


def main():
    if len(sys.argv) != 3:
        print("Usage: python test_power_behavior.py <IP> <test_number>")
        print("\nAvailable tests:")
        print("  1 - Test tv_off() from TV mode")
        print("  2 - Test tv_off() from art mode")
        print("  3 - Test set_art_mode() from TV mode")
        print("  4 - Test set_art_mode() from home screen")
        return 1
    
    ip = sys.argv[1]
    test_num = sys.argv[2]
    
    tests = {
        '1': test_tv_off_from_tv_mode,
        '2': test_tv_off_from_art_mode,
        '3': test_set_art_mode_from_tv_mode,
        '4': test_set_art_mode_from_home_screen,
    }
    
    if test_num not in tests:
        print(f"Invalid test number: {test_num}")
        return 1
    
    tests[test_num](ip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
