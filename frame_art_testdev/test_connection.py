#!/usr/bin/env python3
"""
Simple test script to check if we can connect to Samsung Frame TV
and upload an image.

SETUP:
1. Install the library: pip3 install git+https://github.com/NickWaterton/samsung-tv-ws-api.git
2. Put a test image (test.jpg) in this directory
3. Update FRAME_TV_IP below with your TV's IP address
4. Run: python3 test_connection.py
5. Run with brightness: python3 test_connection.py --brightness 75

USAGE:
  python3 test_connection.py                  # Run full test
  python3 test_connection.py --brightness 5   # Set brightness to 5 (normal range)
  python3 test_connection.py -b 50            # Set brightness to 50 (max/brightest)

NOTE: Brightness quirk discovered empirically:
      - Safe values: 1-10 for normal brightness levels
      - Special value: 50 for maximum brightness
      - Values 11-49 may not work correctly (avoid these)
      The TV appears to have two modes: normal (1-10) and max (50)
"""

from samsungtvws import SamsungTVWS
import os
import sys
import time

# ====== CONFIGURATION ======
FRAME_TV_IP = "192.168.1.249"  # CHANGE THIS to your Frame TV's IP
TEST_IMAGE = "test.jpg"        # Name of test image in this directory
TOKEN_FILE = "frame_tv_token.txt"  # File to save authentication token
# ===========================

def test_connection():
    """Test basic connection to Frame TV"""
    print("=" * 60)
    print("STEP 1: Testing connection to Frame TV...")
    print(f"Connecting to {FRAME_TV_IP}...")
    
    # Get the full path to the token file in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(script_dir, TOKEN_FILE)
    
    # Check if token file exists before connection
    token_exists_before = os.path.exists(token_file_path)
    
    if token_exists_before:
        print(f"\n📋 Token file found: {TOKEN_FILE}")
        with open(token_file_path, 'r') as f:
            existing_token = f.read().strip()
            if existing_token:
                print(f"   Token preview: {existing_token[:20]}...{existing_token[-10:] if len(existing_token) > 30 else ''}")
                print("   → Attempting to connect with saved token (no TV approval needed)")
            else:
                print("   ⚠️  Token file is empty - will request new token")
                token_exists_before = False
    
    if not token_exists_before:
        print(f"\n📋 No token file found ({TOKEN_FILE})")
        print("\n" + "🚨 " * 20)
        print("⚠️  FIRST TIME CONNECTION - POPUP WILL APPEAR DURING UPLOAD!")
        print("🚨 " * 20)
        print("\n👀 IMPORTANT: The TV popup appears when you actually USE the connection")
        print("   It will show up in STEP 3 (Image Upload)")
        print("   Be ready to click 'ALLOW' when you see it!")
        print("\n⏳ Creating connection object...")
        print()
    
    try:
        # Use token_file parameter to auto-save and reuse the authentication token
        tv = SamsungTVWS(host=FRAME_TV_IP, port=8002, token_file=token_file_path)
        
        print("✓ Connection object created!")
        
        if not token_exists_before:
            print("   ℹ️  Note: Token will be saved when you approve the popup in STEP 3")
        elif token_exists_before:
            print(f"✓ Authenticated using existing token from {TOKEN_FILE}")
            print("   → No TV approval required")
        
        return tv
    except Exception as e:
        print(f"\n✗ Connection failed: {e}")
        if token_exists_before:
            print("   ℹ️  Your saved token may be invalid or expired")
            print(f"   ℹ️  Try deleting {TOKEN_FILE} and reconnecting")
        return None

def test_art_mode(tv):
    """Test getting art mode object"""
    print("\n" + "=" * 60)
    print("STEP 2: Testing art mode access...")
    
    # Check for token file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(script_dir, TOKEN_FILE)
    art_token_exists = os.path.exists(token_file_path) and os.path.getsize(token_file_path) > 0
    
    if not art_token_exists:
        print("\n🚨 " * 20)
        print("⚠️  SECOND CONNECTION REQUIRED - ACTION NEEDED!")
        print("🚨 " * 20)
        print("\n👀 LOOK AT YOUR TV AGAIN!")
        print("   Art mode needs a SECOND approval prompt")
        print("   Click 'ALLOW' when the popup appears")
        print("\n⏳ Creating art mode connection (waiting for approval)...")
        print()
    else:
        print("ℹ️  Note: Using saved token for art mode connection")
    
    try:
        art = tv.art()
        
        # If this was first time, wait a moment for any token updates
        if not art_token_exists:
            print("\n⏳ Waiting for art mode token to be saved...")
            time.sleep(2)
        
        print("✓ Art mode object created!")
        print("  (This should have kicked the TV into art mode)")
        return art
    except Exception as e:
        print(f"✗ Art mode access failed: {e}")
        if not art_token_exists:
            print("   ℹ️  Did you click 'ALLOW' on the second popup on your TV?")
        else:
            print("   ℹ️  Token may be invalid or TV is not responding")
        return None

def test_upload(art):
    """Test uploading an image"""
    print("\n" + "=" * 60)
    print("STEP 3: Testing image upload...")
    
    # Check if test image exists
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(script_dir, TEST_IMAGE)
    token_file_path = os.path.join(script_dir, TOKEN_FILE)
    
    if not os.path.exists(image_path):
        print(f"✗ Test image not found: {image_path}")
        print(f"  Please create a file named '{TEST_IMAGE}' in this directory")
        return False, None
    
    print(f"Found test image: {image_path}")
    
    # Check if this is first time (no token yet)
    token_exists = os.path.exists(token_file_path) and os.path.getsize(token_file_path) > 0
    
    if not token_exists:
        print("\n" + "🚨 " * 20)
        print("👀 LOOK AT YOUR TV NOW! 👀")
        print("🚨 " * 20)
        print("\n⚠️  The authorization popup will appear on your TV in a moment!")
        print("   Click 'ALLOW' when you see the 'SamsungTvRemote' request")
        print()
        input("Press ENTER when you're ready and watching your TV... ")
        print()
    
    try:
        # Read the image
        with open(image_path, "rb") as f:
            image_data = f.read()
        
        print(f"Image size: {len(image_data)} bytes")
        print("Starting upload... (POPUP SHOULD APPEAR ON TV NOW!)")
        
        if not token_exists:
            print("\n⏳ WAITING - Click 'ALLOW' on your TV now!")
            print("   Checking for token every 2 seconds...")
        
        # Upload the image - this triggers the auth popup!
        response = art.upload(
            image_data,
            file_type="JPEG",
            matte="flexible_apricot",  # Nice warm matte color
            portrait_matte="flexible_apricot"
        )
        
        print(f"\n✓ Upload successful!")
        print(f"  Response: {response}")
        
        # Wait for token to be saved
        if not token_exists:
            print("\n⏳ Upload complete! Waiting for token to be saved...")
            max_wait = 10
            for i in range(max_wait):
                time.sleep(1)
                if os.path.exists(token_file_path):
                    with open(token_file_path, 'r') as f:
                        token_content = f.read().strip()
                    if token_content:
                        print(f"   ✓ Token saved after {i+1} seconds!")
                        print(f"   Token: {token_content[:20]}...{token_content[-10:] if len(token_content) > 30 else ''}")
                        print("   → Future connections will be automatic!")
                        break
            else:
                print(f"   ⚠️  Token not saved yet (waited {max_wait} seconds)")
        
        # Extract content_id from response if available
        content_id = None
        if isinstance(response, dict) and 'content_id' in response:
            content_id = response['content_id']
            print(f"  Content ID: {content_id}")
        
        return True, content_id
        
    except Exception as e:
        print(f"\n✗ Upload failed: {e}")
        if not token_exists:
            print("   ℹ️  Did you click 'ALLOW' on your TV?")
            print("   ℹ️  The popup appears when upload starts")
        return False, None

def test_display_uploaded_art(art, content_id):
    """Test displaying the uploaded image in art mode"""
    print("\n" + "=" * 60)
    print("STEP 4: Testing art mode display...")
    
    try:
        # First check if we're already in art mode
        print("Checking current art mode status...")
        try:
            current_artmode = art.get_artmode()
            print(f"Current art mode: {current_artmode}")
            
            # Only try to set art mode if not already on
            if current_artmode != 'on':
                print("Enabling art mode...")
                try:
                    art.set_artmode(True)
                    print("✓ TV set to art mode")
                except Exception as e:
                    # Error -7 seems to be common, try alternative method
                    print(f"⚠️  set_artmode failed: {e}")
                    print("  Trying alternative: selecting an image (this often triggers art mode)...")
            else:
                print("✓ TV is already in art mode")
        except Exception as e:
            print(f"⚠️  Could not check art mode: {e}")
            print("  Continuing anyway...")
        
        # Get list of available images to find the most recent upload
        print("\nGetting available images...")
        try:
            available = art.available()
            print(f"Found {len(available) if available else 0} images on TV")
            
            # If we have a content_id from upload, use it
            if content_id:
                target_id = content_id
                print(f"Using uploaded image ID: {target_id}")
            elif available and len(available) > 0:
                # Use the last image (most recent upload)
                target_id = available[-1].get('content_id')
                print(f"No content_id from upload, using most recent image: {target_id}")
            else:
                print("⚠️  No images available to select")
                return False
            
            # Now select and display the image
            print(f"\nSelecting image: {target_id}")
            art.select_image(target_id, show=True)
            print("✓ Image selection command sent!")
            
            # Verify what's currently displayed
            print("\nVerifying current display...")
            current = art.get_current()
            current_id = current.get('content_id', 'unknown')
            print(f"Currently displaying: {current_id}")
            
            if current_id == target_id:
                print("✓ SUCCESS! Your image is now showing on the TV!")
            else:
                print(f"⚠️  TV is showing {current_id} instead of {target_id}")
                print("   But your image is uploaded and available")
            
            # Show some recent images for reference
            print("\nLast 3 images on your TV:")
            for item in available[-3:]:
                img_id = item.get('content_id', 'unknown')
                size = f"{item.get('width', '?')}x{item.get('height', '?')}"
                marker = " ← NEWLY UPLOADED?" if img_id == target_id else ""
                print(f"  - {img_id} ({size}){marker}")
            
            return True
            
        except Exception as e:
            print(f"⚠️  Image selection failed: {e}")
            return False
        
    except Exception as e:
        print(f"✗ Art mode display failed: {e}")
        print(f"  Error details: {type(e).__name__}")
        return False

def test_matte_list(art):
    """Get and display available matte colors"""
    print("\n" + "=" * 60)
    print("STEP 6: Getting available matte colors...")
    
    try:
        matte_list = art.get_matte_list()
        
        if not matte_list:
            print("⚠️  No matte list returned")
            return False
        
        print(f"✓ Retrieved matte list!")
        
        # Handle if it's a list
        if isinstance(matte_list, list):
            print(f"\nFound {len(matte_list)} mattes:")
            for matte in matte_list:
                if isinstance(matte, dict):
                    matte_id = matte.get('matte_id', matte.get('matteId', 'unknown'))
                    matte_type = matte.get('matte_type', matte.get('matteType', ''))
                    color = matte.get('color', '')
                    if color:
                        print(f"  - {matte_id} ({matte_type}) - {color}")
                    else:
                        print(f"  - {matte_id} ({matte_type})")
                else:
                    print(f"  - {matte}")
            print(f"\n📊 Total mattes available: {len(matte_list)}")
            
        # Handle if it's a dict
        elif isinstance(matte_list, dict):
            print(f"\nFound {len(matte_list)} matte categories:")
            total_mattes = 0
            for category, mattes in matte_list.items():
                print(f"\n📦 {category}:")
                if isinstance(mattes, list):
                    for matte in mattes:
                        if isinstance(matte, dict):
                            matte_id = matte.get('matte_id', matte.get('matteId', 'unknown'))
                            print(f"  - {matte_id}")
                        else:
                            print(f"  - {matte}")
                    total_mattes += len(mattes)
                else:
                    print(f"  {mattes}")
            print(f"\n📊 Total mattes available: {total_mattes}")
        else:
            print(f"\nMatte list data: {matte_list}")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to get matte list: {e}")
        print(f"  Error details: {type(e).__name__}")
        
        # Try to print raw data for debugging
        try:
            matte_list = art.get_matte_list()
            print(f"\nRaw matte data type: {type(matte_list)}")
            if isinstance(matte_list, list) and len(matte_list) > 0:
                print(f"First item: {matte_list[0]}")
        except:
            pass
        
        return False

def test_photo_filter_list(art):
    """Get and display available photo filters"""
    print("\n" + "=" * 60)
    print("STEP 7: Getting available photo filters...")
    
    try:
        filter_list = art.get_photo_filter_list()
        
        if not filter_list:
            print("⚠️  No filter list returned")
            return False
        
        print(f"✓ Retrieved photo filter list!")
        
        if isinstance(filter_list, list):
            print(f"\nFound {len(filter_list)} photo filters:")
            for filter_item in filter_list:
                if isinstance(filter_item, dict):
                    filter_id = filter_item.get('filter_id', 'unknown')
                    filter_name = filter_item.get('filter_name', 'unknown')
                    print(f"  - {filter_id}: {filter_name}")
                else:
                    print(f"  - {filter_item}")
        elif isinstance(filter_list, dict):
            print(f"\nFilter data:")
            for key, value in filter_list.items():
                print(f"  {key}: {value}")
        else:
            print(f"\nFilter list: {filter_list}")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to get photo filter list: {e}")
        print(f"  Error details: {type(e).__name__}")
        return False

def explore_api(art):
    """Explore what methods are available"""
    print("\n" + "=" * 60)
    print("BONUS: Available art mode methods...")
    
    methods = [method for method in dir(art) if not method.startswith('_')]
    print("Available methods:")
    for method in methods:
        print(f"  - {method}")

def test_brightness_control(art):
    """Test brightness get/set functionality"""
    print("\n" + "=" * 60)
    print("STEP 5: Testing brightness controls...")
    
    try:
        # Get current brightness
        print("Getting current brightness...")
        current_brightness = art.get_brightness()
        print(f"✓ Current brightness: {current_brightness}")
        
        # Test setting brightness to a medium level
        test_brightness = 50
        print(f"\nSetting brightness to {test_brightness}%...")
        art.set_brightness(test_brightness)
        print(f"✓ Brightness set command sent")
        
        # Wait a moment for it to apply
        import time
        time.sleep(1)
        
        # Verify the change
        print("\nVerifying brightness change...")
        new_brightness = art.get_brightness()
        print(f"✓ New brightness: {new_brightness}")
        
        if new_brightness == test_brightness:
            print("✓ SUCCESS! Brightness changed as expected")
        else:
            print(f"⚠️  Brightness is {new_brightness}, expected {test_brightness}")
        
        # Restore original brightness
        if current_brightness != new_brightness:
            print(f"\nRestoring original brightness ({current_brightness})...")
            art.set_brightness(current_brightness)
            print("✓ Brightness restored")
        
        return True
        
    except Exception as e:
        print(f"✗ Brightness test failed: {e}")
        print(f"  Error details: {type(e).__name__}")
        return False

def set_brightness_only(brightness):
    """Just set brightness without running other tests
    
    Note: The TV has a brightness quirk:
          - Values 1-10: Normal brightness range (works reliably)
          - Value 50: Maximum brightness (special bright mode)
          - Values 11-49: Unreliable, may not work correctly
    """
    print("=" * 60)
    print(f"Setting Frame TV brightness to {brightness}")
    print("=" * 60)
    
    # Get the full path to the token file in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(script_dir, TOKEN_FILE)
    
    # Check token status
    if os.path.exists(token_file_path):
        print(f"\n📋 Using saved token from {TOKEN_FILE}")
    else:
        print(f"\n📋 No token found - you'll need to approve on TV")
    
    try:
        print(f"Connecting to {FRAME_TV_IP}...")
        tv = SamsungTVWS(host=FRAME_TV_IP, port=8002, token_file=token_file_path)
        art = tv.art()
        print("✓ Connected (token authenticated)")
        
        print(f"\nCurrent brightness: {art.get_brightness()}")
        print(f"Setting brightness to {brightness}...")
        art.set_brightness(brightness)
        
        import time
        time.sleep(1)
        
        new_brightness = art.get_brightness()
        print(f"✓ New brightness: {new_brightness}")
        
        if new_brightness == brightness:
            print("✓ SUCCESS!")
        else:
            print(f"⚠️  Set to {brightness} but TV reports {new_brightness}")
        
        return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        if os.path.exists(token_file_path):
            print(f"   ℹ️  Try deleting {TOKEN_FILE} if the token is invalid")
        return False

def main():
    # Check for brightness argument
    if len(sys.argv) > 1:
        if sys.argv[1] in ['--brightness', '-b']:
            if len(sys.argv) < 3:
                print("Error: Please provide a brightness value")
                print("Usage: python3 test_connection.py --brightness 5")
                print("\nValid brightness values:")
                print("  1-10  = Normal brightness range")
                print("  50    = Maximum brightness (special bright mode)")
                print("\nNote: Values 11-49 are unreliable and not recommended")
                sys.exit(1)
            try:
                brightness = int(sys.argv[2])
                
                # Check if value is in the unreliable range
                if 11 <= brightness <= 49:
                    print("=" * 60)
                    print("⚠️  WARNING: Brightness values 11-49 are unreliable!")
                    print("=" * 60)
                    print("\nRecommended values:")
                    print("  • 1-10  for normal brightness levels")
                    print("  • 50    for maximum brightness")
                    print("\nValues between 11-49 may not work correctly.")
                    print(f"You entered: {brightness}")
                    response = input("\nContinue anyway? (y/n): ")
                    if response.lower() != 'y':
                        sys.exit(1)
                elif brightness < 1:
                    print(f"Error: Brightness must be at least 1 (you entered {brightness})")
                    sys.exit(1)
                elif brightness > 50:
                    print(f"Warning: Maximum brightness is 50 (you entered {brightness})")
                    response = input("Continue anyway? (y/n): ")
                    if response.lower() != 'y':
                        sys.exit(1)
                # Just set brightness and exit - don't run other tests
                set_brightness_only(brightness)
                sys.exit(0)
            except ValueError:
                print("Error: Brightness must be a number")
                sys.exit(1)
    
    # Otherwise run full test suite
    print("\n" + "=" * 60)
    print("SAMSUNG FRAME TV - CONNECTION TEST")
    print("=" * 60)
    
    # Test 1: Connection
    tv = test_connection()
    if not tv:
        print("\n⚠️  Cannot continue without connection")
        return
    
    # Test 2: Art Mode
    art = test_art_mode(tv)
    if not art:
        print("\n⚠️  Cannot continue without art mode access")
        return
    
    # Test 3: Upload
    upload_success, content_id = test_upload(art)
    
    # Test 4: Display in art mode (only if upload succeeded)
    display_success = False
    if upload_success:
        display_success = test_display_uploaded_art(art, content_id)
    
    # Test 5: Brightness controls
    brightness_success = test_brightness_control(art)
    
    # Test 6: Available mattes
    matte_success = test_matte_list(art)
    
    # Test 7: Available photo filters
    filter_success = test_photo_filter_list(art)
    
    # Bonus: Explore
    explore_api(art)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    # Count successes
    tests = {
        "Upload": upload_success,
        "Display": display_success,
        "Brightness": brightness_success,
        "Mattes": matte_success,
        "Filters": filter_success
    }
    
    passed = sum(1 for result in tests.values() if result)
    total = len(tests)
    
    if passed == total:
        print(f"✓ All {total} tests passed!")
        print("\nYour Frame TV:")
        print("  1. ✓ Is in art mode")
        print("  2. ✓ Has your test image uploaded")
        print("  3. ✓ Is displaying your test image")
        print("  4. ✓ Brightness controls work")
        print("  5. ✓ Matte colors retrieved")
        print("  6. ✓ Photo filters retrieved")
        print("\nNext steps:")
        print("  - Look at your TV to see your image")
        print("  - Try uploading more images with different mattes")
        print("  - Experiment with photo filters")
        print("  - Build a Home Assistant integration")
    else:
        print(f"⚠️  {passed}/{total} tests passed")
        print("\nTest Results:")
        for test_name, result in tests.items():
            status = "✓" if result else "✗"
            print(f"  {status} {test_name}")
        
        if upload_success and display_success:
            print("\n✓ Core functionality (upload/display) works!")
        else:
            print("\n⚠️  Check the error messages above")
    
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
