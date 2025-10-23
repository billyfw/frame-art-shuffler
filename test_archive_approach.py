#!/usr/bin/env python3
"""Test upload using the exact archive script approach"""

from samsungtvws import SamsungTVWS
import time
from pathlib import Path

# Use our working token
TOKEN_FILE = "custom_components/frame_art_shuffler/tokens/192.168.1.249.token"
TV_IP = "192.168.1.249"
IMAGE_PATH = Path("~/kgtest2.jpeg").expanduser()

print("Testing upload with archive approach...")
print(f"Token file: {TOKEN_FILE}")
print(f"Image: {IMAGE_PATH}")

# Create connection (archive doesn't call .open() explicitly)
tv = SamsungTVWS(host=TV_IP, port=8002, token_file=TOKEN_FILE, name="SamsungTvRemote")
print("✓ TV object created")

# Get art object
art = tv.art()
print("✓ Art object created")

# Load image
payload = IMAGE_PATH.read_bytes()
print(f"✓ Image loaded: {len(payload)} bytes ({len(payload)/1024/1024:.2f} MB)")

# Try upload with retry logic (same as archive)
max_retries = 3
for attempt in range(max_retries):
    try:
        if attempt > 0:
            print(f"   Retry {attempt}/{max_retries-1}...")
            time.sleep(2)
        
        print(f"   Upload attempt {attempt + 1}...")
        response = art.upload(payload, file_type="JPEG")
        
        print(f"✓ Upload successful!")
        print(f"   Response: {response}")
        break
        
    except Exception as e:
        error_msg = str(e)
        print(f"   ✗ Upload failed: {error_msg}")
        
        if attempt < max_retries - 1:
            print(f"   Will retry...")
        else:
            print(f"\n✗ All {max_retries} attempts failed")
            print("This confirms the TV's upload API is not responding")

tv.close()
print("\nTest complete")
