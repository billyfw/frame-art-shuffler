#!/usr/bin/env python3
"""
Example script demonstrating matte and filter usage on Samsung Frame TV
"""

from samsungtvws import SamsungTVWS
import os
import sys
import time

# ====== CONFIGURATION ======
FRAME_TV_IP = "192.168.1.249"
TOKEN_FILE = "frame_tv_token.txt"
TEST_IMAGE = "test.jpg"
# ===========================

def demo_mattes_and_filters():
    """
    Upload an image and demonstrate different mattes and filters.
    """
    print("=" * 70)
    print("MATTE & FILTER DEMO - Samsung Frame TV")
    print("=" * 70)
    
    # Get paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(script_dir, TOKEN_FILE)
    image_path = os.path.join(script_dir, TEST_IMAGE)
    
    # Check files
    if not os.path.exists(token_file_path):
        print(f"\n✗ No token file found: {TOKEN_FILE}")
        sys.exit(1)
    
    if not os.path.exists(image_path):
        print(f"\n✗ Test image not found: {TEST_IMAGE}")
        sys.exit(1)
    
    try:
        # Connect
        print(f"\n⏳ Connecting to {FRAME_TV_IP}...")
        tv = SamsungTVWS(host=FRAME_TV_IP, port=8002, token_file=token_file_path)
        art = tv.art()
        print("✓ Connected!\n")
        
        # Read image
        with open(image_path, "rb") as f:
            image_data = f.read()
        print(f"📷 Loaded test image: {len(image_data)} bytes\n")
        
        # Demo 1: Upload with different mattes
        print("=" * 70)
        print("DEMO 1: Uploading images with different mattes")
        print("=" * 70)
        
        mattes_to_try = ["none", "modern", "flexible", "shadowbox"]
        uploaded_ids = []
        
        for matte in mattes_to_try:
            print(f"\n⏳ Uploading with matte: '{matte}'...")
            try:
                content_id = art.upload(
                    image_data,
                    file_type="JPEG",
                    matte=matte,
                    portrait_matte=matte
                )
                print(f"   ✓ Uploaded as: {content_id}")
                uploaded_ids.append((content_id, matte))
                time.sleep(1)
            except Exception as e:
                print(f"   ✗ Upload failed: {e}")
        
        # Demo 2: Apply filters to uploaded images
        if uploaded_ids:
            print("\n" + "=" * 70)
            print("DEMO 2: Applying filters to uploaded images")
            print("=" * 70)
            
            filters_to_try = ["None", "Aqua", "Pastel", "Ink"]
            
            # Use first uploaded image for filter demo
            test_id, test_matte = uploaded_ids[0]
            print(f"\n📷 Using image: {test_id} (matte: {test_matte})")
            
            for filter_name in filters_to_try:
                print(f"\n⏳ Applying filter: '{filter_name}'...")
                try:
                    art.set_photo_filter(test_id, filter_name)
                    print(f"   ✓ Filter applied!")
                    
                    # Display it
                    art.select_image(test_id, show=True)
                    print(f"   📺 Displaying on TV (look at your screen!)")
                    time.sleep(3)  # Show for 3 seconds
                    
                except Exception as e:
                    print(f"   ✗ Filter application failed: {e}")
        
        # Demo 3: Change matte on existing image
        if uploaded_ids:
            print("\n" + "=" * 70)
            print("DEMO 3: Changing matte on existing image")
            print("=" * 70)
            
            test_id, original_matte = uploaded_ids[0]
            new_mattes = ["modernwide", "triptych"]
            
            print(f"\n📷 Image: {test_id}")
            print(f"   Original matte: {original_matte}")
            
            for new_matte in new_mattes:
                print(f"\n⏳ Changing to matte: '{new_matte}'...")
                try:
                    art.change_matte(test_id, new_matte)
                    print(f"   ✓ Matte changed!")
                    
                    # Display it
                    art.select_image(test_id, show=True)
                    print(f"   📺 Displaying on TV (check the matte style!)")
                    time.sleep(3)
                    
                except Exception as e:
                    print(f"   ✗ Matte change failed: {e}")
        
        # Summary
        print("\n" + "=" * 70)
        print("DEMO COMPLETE!")
        print("=" * 70)
        print(f"\n✓ Uploaded {len(uploaded_ids)} images with different mattes")
        print("✓ Demonstrated multiple filters")
        print("✓ Changed mattes on existing images")
        
        print("\n📊 Uploaded Images:")
        for content_id, matte in uploaded_ids:
            print(f"  - {content_id} (matte: {matte})")
        
        print("\n💡 You can now:")
        print("  - View these images in your TV's art gallery")
        print("  - Apply any filter using art.set_photo_filter()")
        print("  - Change mattes using art.change_matte()")
        print("  - Delete them using art.delete_list()")
        
        print("\n" + "=" * 70)
        
    except Exception as e:
        print(f"\n✗ Demo failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("\nThis demo will:")
    print("  1. Upload test image with different mattes")
    print("  2. Apply various filters")
    print("  3. Change mattes on existing images")
    print("\nThe TV will switch between images during the demo.")
    print("Make sure you can see your TV screen!\n")
    
    response = input("Continue? (y/n): ")
    if response.lower() == 'y':
        demo_mattes_and_filters()
    else:
        print("Demo cancelled.")
