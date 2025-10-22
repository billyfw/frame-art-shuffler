#!/usr/bin/env python3
"""
List available mattes and photo filters from Samsung Frame TV
"""

from samsungtvws import SamsungTVWS
import os
import sys

# ====== CONFIGURATION ======
FRAME_TV_IP = "192.168.1.249"
TOKEN_FILE = "frame_tv_token.txt"
# ===========================

def main():
    print("=" * 70)
    print("SAMSUNG FRAME TV - MATTES & FILTERS")
    print("=" * 70)
    
    # Get token file path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(script_dir, TOKEN_FILE)
    
    # Check for token
    if not os.path.exists(token_file_path):
        print(f"\n✗ No token file found: {TOKEN_FILE}")
        print("  Run simple_token_test.py first to get authenticated")
        sys.exit(1)
    
    print(f"\n📋 Using token from: {TOKEN_FILE}")
    
    try:
        # Connect
        print(f"⏳ Connecting to {FRAME_TV_IP}...")
        tv = SamsungTVWS(host=FRAME_TV_IP, port=8002, token_file=token_file_path)
        art = tv.art()
        print("✓ Connected!\n")
        
        # Get Matte List
        print("=" * 70)
        print("AVAILABLE MATTE TYPES")
        print("=" * 70)
        
        try:
            matte_list = art.get_matte_list()
            
            if isinstance(matte_list, list):
                print(f"\nFound {len(matte_list)} matte styles:\n")
                
                for i, matte in enumerate(matte_list, 1):
                    if isinstance(matte, dict):
                        matte_type = matte.get('matte_type', matte.get('matteType', 'unknown'))
                        matte_id = matte.get('matte_id', matte.get('matteId', 'N/A'))
                        color = matte.get('color', matte.get('matteColor', ''))
                        
                        print(f"{i:2}. {matte_type:15} ", end="")
                        if color:
                            print(f"(color: {color})", end="")
                        if matte_id and matte_id != 'N/A':
                            print(f" [ID: {matte_id}]", end="")
                        print()
                    else:
                        print(f"{i:2}. {matte}")
                
                print("\n💡 Usage in upload():")
                print('   art.upload(data, file_type="JPEG", matte="modern")')
                print('   art.upload(data, file_type="JPEG", matte="flexible")')
                
            else:
                print(f"Matte data: {matte_list}")
                
        except Exception as e:
            print(f"✗ Could not retrieve matte list: {e}")
        
        # Get Photo Filter List
        print("\n" + "=" * 70)
        print("AVAILABLE PHOTO FILTERS")
        print("=" * 70)
        
        try:
            filter_list = art.get_photo_filter_list()
            
            if isinstance(filter_list, list):
                print(f"\nFound {len(filter_list)} photo filters:\n")
                
                for i, filter_item in enumerate(filter_list, 1):
                    if isinstance(filter_item, dict):
                        filter_id = filter_item.get('filter_id', filter_item.get('filterId', 'unknown'))
                        filter_name = filter_item.get('filter_name', filter_item.get('filterName', 'N/A'))
                        
                        print(f"{i:2}. {filter_id:15}", end="")
                        if filter_name and filter_name != 'N/A':
                            print(f" ({filter_name})", end="")
                        print()
                    else:
                        print(f"{i:2}. {filter_item}")
                
                print("\n💡 Usage:")
                print('   art.set_photo_filter(content_id, "Aqua")')
                print('   art.set_photo_filter(content_id, "Pastel")')
                print('   art.set_photo_filter(content_id, "None")  # Remove filter')
                
            else:
                print(f"Filter data: {filter_list}")
                
        except Exception as e:
            print(f"✗ Could not retrieve filter list: {e}")
        
        print("\n" + "=" * 70)
        print("✓ Done!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n✗ Connection failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
