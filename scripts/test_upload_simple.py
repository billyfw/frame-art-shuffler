#!/usr/bin/env python3
"""Simple standalone test script - no HA dependencies."""

import sys
from pathlib import Path

# Add samsungtvws to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'custom_components' / 'frame_art_shuffler'))

from samsungtvws.art import SamsungTVArt

# EXACT settings that work with HA integration
IP = '192.168.1.249'
TOKEN_DIR = Path(__file__).parent.parent / 'custom_components' / 'frame_art_shuffler' / 'tokens'
TOKEN_FILE = TOKEN_DIR / '192_168_1_249.token'  # UNDERSCORES not dots!
CLIENT_NAME = 'FrameArtShuffler'  # MUST match HA integration

print(f'Token file: {TOKEN_FILE}')
print(f'Token exists: {TOKEN_FILE.exists()}')
if TOKEN_FILE.exists():
    print(f'Token value: {TOKEN_FILE.read_text().strip()}')

print(f'\nConnecting to {IP}...')
art = SamsungTVArt(IP, token_file=str(TOKEN_FILE), port=8002, timeout=30, name=CLIENT_NAME)
art.open()
print('Connected!')

# Read image
image_path = Path.home() / 'jz.jpg'
print(f'\nReading {image_path}...')
with open(image_path, 'rb') as f:
    data = f.read()
print(f'Read {len(data)} bytes')

# Upload with NO matte
print('\nUploading with matte=none...')
content_id = art.upload(data, matte='none', portrait_matte='none', file_type='jpg')
print(f'SUCCESS! content_id = {content_id}')

art.close()
