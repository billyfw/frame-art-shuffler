#!/usr/bin/env python3
"""
Quick script to check token file status
"""
import os

TOKEN_FILE = "frame_tv_token.txt"
script_dir = os.path.dirname(os.path.abspath(__file__))
token_file_path = os.path.join(script_dir, TOKEN_FILE)

print("Token File Status Check")
print("=" * 60)
print(f"Looking for: {token_file_path}")
print()

if os.path.exists(token_file_path):
    print("✓ Token file EXISTS")
    
    # Check file size
    size = os.path.getsize(token_file_path)
    print(f"  File size: {size} bytes")
    
    # Read content
    with open(token_file_path, 'r') as f:
        content = f.read()
    
    if content.strip():
        print(f"  Token length: {len(content.strip())} characters")
        print(f"  Token preview: {content.strip()[:20]}...{content.strip()[-10:] if len(content.strip()) > 30 else ''}")
    else:
        print("  ⚠️  WARNING: File is EMPTY!")
else:
    print("✗ Token file DOES NOT EXIST")
    print("  This means the connection was never successfully authenticated,")
    print("  or the token file couldn't be created.")

print("=" * 60)
