#!/usr/bin/env python3
"""
Debug script to investigate portrait matte support on Samsung Frame TV.
"""

import sys
import os
import json
import logging

# Add the custom_components path so we can import from it
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'custom_components', 'frame_art_shuffler'))

from samsungtvws import SamsungTVWS

# Enable logging to see API traffic
logging.basicConfig(level=logging.INFO)

# TV connection settings
TV_IP = "192.168.1.249"
TOKEN_FILE = os.path.join(os.path.dirname(__file__), '..', 'custom_components', 'frame_art_shuffler', 'tokens', '192.168.1.249.token')
CLIENT_NAME = "FrameArtShuffler"

def main():
    print(f"Connecting to TV at {TV_IP}...")
    print(f"Token file: {TOKEN_FILE}")
    
    tv = SamsungTVWS(host=TV_IP, port=8002, token_file=TOKEN_FILE, name=CLIENT_NAME)
    art = tv.art()
    
    # Get all images and examine their matte fields
    print("\n" + "="*80)
    print("LISTING ALL IMAGES AND THEIR MATTE FIELDS")
    print("="*80)
    
    images = art.available()
    
    # Find portrait and landscape images to compare
    print(f"\nFound {len(images)} images. Examining matte fields...\n")
    
    for img in images:
        content_id = img.get('content_id', 'unknown')
        # Print all fields related to matte
        matte_fields = {k: v for k, v in img.items() if 'matte' in k.lower()}
        width = img.get('width', '?')
        height = img.get('height', '?')
        
        # Determine orientation
        try:
            w = int(width) if width != '?' else 0
            h = int(height) if height != '?' else 0
            orientation = "PORTRAIT" if h > w else "LANDSCAPE"
        except:
            orientation = "UNKNOWN"
        
        print(f"Content ID: {content_id}")
        print(f"  Dimensions: {width}x{height} ({orientation})")
        print(f"  Matte fields: {matte_fields}")
        print()
    
    # Now let's try to find a portrait image and experiment
    print("\n" + "="*80)
    print("SEARCHING FOR PORTRAIT IMAGES")
    print("="*80)
    
    portrait_images = []
    landscape_images = []
    
    for img in images:
        try:
            w = int(img.get('width', 0))
            h = int(img.get('height', 0))
            if h > w:
                portrait_images.append(img)
            else:
                landscape_images.append(img)
        except:
            pass
    
    print(f"\nFound {len(portrait_images)} portrait images")
    print(f"Found {len(landscape_images)} landscape images")
    
    if portrait_images:
        print("\n" + "-"*40)
        print("TESTING change_matte ON A PORTRAIT IMAGE")
        print("-"*40)
        
        test_img = portrait_images[0]
        content_id = test_img.get('content_id')
        print(f"\nUsing portrait image: {content_id}")
        print(f"Current matte fields: {json.dumps({k: v for k, v in test_img.items() if 'matte' in k.lower()}, indent=2)}")
        
        # Try setting portrait_matte_id instead of matte_id
        print("\n>>> Trying: change_matte with BOTH matte_id AND portrait_matte")
        print("    art.change_matte(content_id, matte_id='none', portrait_matte='flexible_apricot')")
        try:
            art.change_matte(content_id, matte_id='none', portrait_matte='flexible_apricot')
            print("    SUCCESS!")
        except Exception as e:
            print(f"    FAILED: {e}")
        
        # Check what the image looks like now
        print("\n>>> Checking updated image state...")
        updated_images = art.available()
        for img in updated_images:
            if img.get('content_id') == content_id:
                print(f"Updated matte fields: {json.dumps({k: v for k, v in img.items() if 'matte' in k.lower()}, indent=2)}")
                break
    
    # Let's also try directly constructing a change_matte request with portrait_matte_id
    if portrait_images:
        print("\n" + "-"*40)
        print("TESTING DIRECT API REQUEST WITH portrait_matte_id")
        print("-"*40)
        
        test_img = portrait_images[0]
        content_id = test_img.get('content_id')
        
        print(f"\nTrying direct request with portrait_matte_id field...")
        print("Request: change_matte with portrait_matte_id='shadowbox_polar'")
        
        try:
            # Access the internal method to send raw request
            art._send_art_request({
                "request": "change_matte",
                "content_id": content_id,
                "portrait_matte_id": "shadowbox_polar",
            })
            print("    SUCCESS!")
        except Exception as e:
            print(f"    FAILED: {e}")
    
    # Let's also check if there's a way to query which mattes support portrait
    print("\n" + "="*80)
    print("CHECKING MATTE LIST FOR PORTRAIT INFO")
    print("="*80)
    
    matte_list = art.get_matte_list(include_colour=True)
    print(f"\nMatte types (raw): {json.dumps(matte_list, indent=2)}")

if __name__ == "__main__":
    main()
