#!/usr/bin/env python3
"""
ULTRA SIMPLE test - just try to get ANY response from TV
This will help diagnose if the TV is even reachable
"""

import socket
import sys

FRAME_TV_IP = "192.168.1.249"
PORTS_TO_CHECK = [8001, 8002, 8080]

print("=" * 70)
print("TV CONNECTIVITY TEST")
print("=" * 70)
print(f"\nTesting connection to: {FRAME_TV_IP}")

for port in PORTS_TO_CHECK:
    print(f"\nTrying port {port}...", end=" ")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((FRAME_TV_IP, port))
        sock.close()
        
        if result == 0:
            print("✓ OPEN (TV is listening)")
        else:
            print("✗ CLOSED (not responding)")
    except Exception as e:
        print(f"✗ ERROR: {e}")

print("\n" + "=" * 70)
print("\nWhat this means:")
print("  - Port 8001: Standard WebSocket (older TVs, unencrypted)")
print("  - Port 8002: SSL WebSocket (newer TVs, encrypted)")  
print("  - Port 8080: REST API / Auth")
print("\nIf all ports are CLOSED:")
print("  - TV might be off or in standby")
print("  - Wrong IP address")
print("  - Network/firewall issue")
print("\nIf port 8002 is OPEN: Your TV should work with our scripts!")
print("=" * 70)
