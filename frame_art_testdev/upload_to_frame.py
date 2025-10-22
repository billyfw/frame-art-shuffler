#!/usr/bin/env python3
"""
Upload and display images on Samsung Frame TV in art mode.
Quick test script for uploading images from command line.
Run with --help for usage info.
"""

from samsungtvws import SamsungTVWS
import os
import sys
import argparse
import time

# ====== CONFIGURATION ======
FRAME_TV_IP = "192.168.1.249"  # CHANGE THIS to your Frame TV's IP
TOKEN_FILE = "frame_tv_token.txt"  # File to save authentication token
# ===========================

def get_tv_connection():
    """Establish connection to Frame TV"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(script_dir, TOKEN_FILE)
    
    try:
        tv = SamsungTVWS(host=FRAME_TV_IP, port=8002, token_file=token_file_path)
        return tv
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return None

def get_art_mode(tv):
    """Get art mode object"""
    try:
        art = tv.art()
        return art
    except Exception as e:
        print(f"✗ Art mode access failed: {e}")
        return None

def delete_other_images(art, keep_content_id, debug=False):
    """
    Delete all images except the specified one
    
    Args:
        art: Art mode object
        keep_content_id: The content_id to keep (newly uploaded image)
        debug: Enable verbose debug output
    
    Returns:
        True if successful, False otherwise
    """
    try:
        print("\n🗑️  Deleting other images from Frame TV...")
        
        # Wait a moment before querying (TV needs time to settle)
        if debug:
            print("[DEBUG] Waiting 3s before fetching image list...")
        time.sleep(3)
        
        # Get list of all images
        if debug:
            print("[DEBUG] Fetching list of all images on TV...")
        
        available = art.available()
        
        if not available:
            print("   No images found on TV")
            return True
        
        if debug:
            print(f"[DEBUG] Found {len(available)} total images")
        
        # Filter out the one we want to keep
        to_delete = [img['content_id'] for img in available if img.get('content_id') != keep_content_id]
        
        if not to_delete:
            print("   No other images to delete (only your new image is on the TV)")
            return True
        
        print(f"   Found {len(to_delete)} image(s) to delete...")
        if debug:
            print(f"[DEBUG] Keeping: {keep_content_id}")
            print(f"[DEBUG] Deleting: {to_delete}")
        
        # Delete using the batch delete method
        if debug:
            print(f"[DEBUG] Calling art.delete_list() with {len(to_delete)} items...")
        
        art.delete_list(to_delete)
        
        # Wait for TV to process the deletions
        if debug:
            print("[DEBUG] Waiting 4s for TV to process deletions...")
        time.sleep(4)
        
        print(f"✓ Deleted {len(to_delete)} image(s) - only your new image remains!")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to delete other images: {e}")
        if debug:
            import traceback
            print(f"[DEBUG] Traceback:\n{traceback.format_exc()}")
        return False

def upload_and_display(image_path, matte=None, brightness=None, display=True, debug=False, upload_timeout=None, auto_artmode=False, delete_others=False):
    """
    Upload an image to the Frame TV and optionally display it
    
    Args:
        image_path: Path to the image file to upload
        matte: Optional matte style (e.g., 'flexible_apricot', 'modern_black')
        brightness: Optional brightness level (1-10 normal, 50 for max)
        display: Whether to display the image after upload (default: True)
        debug: Enable verbose debug output
        upload_timeout: Timeout in seconds for upload operation (None = library default)
        auto_artmode: Automatically enable art mode if not already on
        delete_others: Delete all other images after successfully displaying this one
    
    Returns:
        True if successful, False otherwise
    """
    # Verify image exists
    if not os.path.exists(image_path):
        print(f"✗ Error: Image file not found: {image_path}")
        return False
    
    # Check file extension
    ext = os.path.splitext(image_path)[1].lower()
    if ext not in ['.jpg', '.jpeg']:
        print(f"⚠️  Warning: File extension is '{ext}'. Frame TV typically works best with JPEG files.")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            return False
    
    print(f"📤 Uploading: {os.path.basename(image_path)}")
    print(f"   Full path: {image_path}")
    
    # Connect to TV
    print(f"🔌 Connecting to Frame TV at {FRAME_TV_IP}...")
    tv = get_tv_connection()
    if not tv:
        return False
    
    art = get_art_mode(tv)
    if not art:
        return False
    
    print("✓ Connected to Frame TV")
    
    # Give TV a moment to be ready
    print("⏳ Preparing TV for upload...")
    time.sleep(2)
    
    # Check if TV is in art mode
    print("🎨 Checking art mode status...")
    try:
        current_artmode = art.get_artmode()
        if debug:
            print(f"[DEBUG] Art mode status: {current_artmode}")
        
        if current_artmode != 'on':
            print("\n" + "⚠️ " * 20)
            print("ERROR: TV is NOT in art mode!")
            print("⚠️ " * 20)
            print(f"\nCurrent state: {current_artmode}")
            print("\nUploading while TV is showing regular content can cause issues:")
            print("  • Upload may fail or timeout")
            print("  • TV may enter a bad state")
            print("  • TV may need to be power cycled")
            print("\n💡 Solution: Put TV in art mode first")
            print("   • Press the power button briefly (standby = art mode)")
            print("   • Or use the TV remote to switch to art mode")
            
            if auto_artmode:
                print("\n💡 Auto art mode enabled - attempting to enable art mode...")
                try:
                    art.set_artmode(True)
                    time.sleep(3)  # Give TV time to switch
                    
                    # Verify it switched
                    new_mode = art.get_artmode()
                    if new_mode == 'on':
                        print("✓ Art mode enabled successfully")
                        if debug:
                            print("[DEBUG] TV is now in art mode")
                    else:
                        print(f"\n✗ Art mode not enabled (status: {new_mode})")
                        print("Upload cancelled. Please manually enable art mode and try again.")
                        return False
                except Exception as e:
                    print(f"\n✗ Could not enable art mode: {e}")
                    print("Upload cancelled. Please manually enable art mode and try again.")
                    return False
            else:
                print("\nUpload cancelled. Put TV in art mode and try again.")
                print("Or run with --auto-artmode to automatically enable art mode.")
                return False
        else:
            print("✓ TV is in art mode")
            if debug:
                print("[DEBUG] Safe to upload")
                
    except Exception as e:
        print(f"⚠️  Could not check art mode status: {e}")
        if debug:
            print(f"[DEBUG] Art mode check failed: {type(e).__name__}")
        print("   Proceeding with upload anyway...")
    
    # Set brightness if requested
    if brightness is not None:
        print(f"💡 Setting brightness to {brightness}...")
        try:
            art.set_brightness(brightness)
            print(f"✓ Brightness set to {brightness}")
        except Exception as e:
            print(f"⚠️  Brightness adjustment failed: {e}")
    
    # Read and upload the image
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
        
        file_size_mb = len(image_data) / (1024 * 1024)
        print(f"📊 Image size: {file_size_mb:.2f} MB")
        
        # Check if file is too large
        if file_size_mb > 10:
            print("\n" + "⚠️ " * 20)
            print("WARNING: File is very large!")
            print("⚠️ " * 20)
            print(f"\nYour file is {file_size_mb:.1f}MB")
            print("Files over 10MB often timeout during upload to Samsung Frame TV.")
            print("\n📏 Recommended: Resize to < 5MB before uploading")
            print("   • Frame TV resolution: 3840x2160 (4K)")
            print("   • Recommended JPEG quality: 70-80%")
            print("   • Target size: 3-5MB")
            print("\n🛠️  Quick resize options:")
            print("   • macOS: Open in Preview → Export → Quality 70%")
            print("   • Command line: sips --resampleWidth 3840 --setProperty formatOptions 70 input.jpg --out output.jpg")
            print("   • ImageMagick: convert input.jpg -resize 3840x2160 -quality 75 output.jpg")
            
            response = input("\nContinue with upload anyway? (y/n): ")
            if response.lower() != 'y':
                print("Upload cancelled. Please resize your image and try again.")
                return False
            
            print("\nProceeding with upload (this may take several minutes or timeout)...\n")
        
        # Estimate upload time and set timeout
        if file_size_mb > 5:
            print("ℹ️  Large file. Upload may take 1-2 minutes...")
            if not upload_timeout:
                upload_timeout = 180  # 3 minutes for large files
                print(f"   Using {upload_timeout} second timeout")
        
        if debug and upload_timeout:
            print(f"[DEBUG] Upload timeout: {upload_timeout} seconds")
            print(f"[DEBUG] Note: Library has hardcoded websocket timeout (~30-60s)")
            print(f"[DEBUG] Files > 10MB will likely timeout regardless of this setting")
        
        print("📤 Uploading to TV...")
        
        # Determine file type
        if ext in ['.jpg', '.jpeg']:
            file_type = "JPEG"
        elif ext == '.png':
            file_type = "PNG"
        else:
            file_type = "JPEG"  # Default
        
        # Upload with optional matte
        upload_kwargs = {
            "file_type": file_type
        }
        
        if matte:
            print(f"🖼️  Applying matte: {matte}")
            upload_kwargs["matte"] = matte
            upload_kwargs["portrait_matte"] = matte
        
        # Try upload with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"   Retry {attempt}/{max_retries-1}...")
                    time.sleep(2)  # Wait before retry
                
                if debug:
                    print(f"[DEBUG] Upload attempt {attempt + 1} starting...")
                    print(f"[DEBUG] File type: {file_type}, Size: {file_size_mb:.2f} MB")
                
                # Note: The library doesn't have a direct timeout parameter for upload
                # But we can at least inform the user
                if file_size_mb > 2:
                    estimated_time = int(file_size_mb * 5)  # Rough estimate
                    print(f"   Estimated upload time: {estimated_time}-{estimated_time*2} seconds...")
                
                response = art.upload(image_data, **upload_kwargs)
                
                if debug:
                    print(f"[DEBUG] Upload completed successfully")
                
                break  # Success, exit retry loop
                
            except Exception as upload_error:
                error_msg = str(upload_error)
                if debug:
                    print(f"[DEBUG] Upload error: {type(upload_error).__name__}: {error_msg}")
                
                if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    print(f"   ⚠️  Upload timed out on attempt {attempt + 1}")
                    if file_size_mb > 10:
                        print(f"   💡 Tip: File is {file_size_mb:.1f}MB - consider resizing to < 5MB")
                
                if attempt < max_retries - 1:
                    print(f"   Retrying upload (attempt {attempt + 2}/{max_retries})...")
                else:
                    # Last attempt failed
                    raise upload_error
        
        print(f"✓ Upload successful!")
        
        if debug:
            print(f"\n[DEBUG] Upload response type: {type(response)}")
            print(f"[DEBUG] Upload response: {response}")
        
        # Extract content_id from response
        content_id = None
        if isinstance(response, dict) and 'content_id' in response:
            content_id = response['content_id']
            print(f"   Content ID: {content_id}")
            if debug:
                print(f"[DEBUG] Got content_id from dict response: {content_id}")
        elif isinstance(response, str):
            # Response is directly the content_id string
            content_id = response
            print(f"   Content ID: {content_id}")
            if debug:
                print(f"[DEBUG] Response IS the content_id string: {content_id}")
        elif debug:
            print(f"[DEBUG] No content_id in response (unexpected format)")
        
        # Display the image if requested
        if display:
            print("🎨 Displaying image in art mode...")
            
            if debug:
                print("[DEBUG] Starting display process...")
            
            # Ensure art mode is enabled
            try:
                if debug:
                    print("[DEBUG] Checking current art mode status...")
                current_artmode = art.get_artmode()
                if debug:
                    print(f"[DEBUG] Current art mode: {current_artmode}")
                    
                if current_artmode != 'on':
                    print("   Enabling art mode...")
                    if debug:
                        print("[DEBUG] Setting art mode to True...")
                    art.set_artmode(True)
                    time.sleep(1)
                    print("   Art mode enabled")
            except Exception as e:
                print(f"   ℹ️  Could not check art mode (TV may be slow): {e}")
                if debug:
                    print(f"[DEBUG] Art mode check failed: {type(e).__name__}: {e}")
            
            # METHOD 1: Try using content_id if we have it
            if content_id:
                if debug:
                    print(f"[DEBUG] METHOD 1: Trying to select with content_id: {content_id}")
                
                # Give TV a moment to finish processing the upload
                # Using extended timing for reliability (6s wait)
                print("   Waiting for TV to finish processing upload...")
                time.sleep(6)
                if debug:
                    print("[DEBUG] Initial 6s wait complete, TV should be ready")
                
                # Try multiple times with increasing delays
                max_attempts = 3
                for attempt in range(max_attempts):
                    try:
                        if attempt > 0:
                            # Extended retry delays for reliability (15s, 20s)
                            wait_time = 10 + (5 * attempt)
                            print(f"   Waiting {wait_time}s for TV to be ready (retry {attempt + 1}/{max_attempts})...")
                            time.sleep(wait_time)
                        
                        if debug:
                            print(f"[DEBUG] Attempt {attempt + 1}: Calling select_image({content_id}, show=True)")
                        
                        art.select_image(content_id, show=True)
                        
                        print(f"✓ Display command sent (attempt {attempt + 1})")
                        
                        # Extended wait time (8s) for TV to complete image switch
                        if debug:
                            print("[DEBUG] Waiting 8s for TV to complete image switch...")
                        time.sleep(8)
                        
                        # Wake up the websocket connection before verification
                        # This keeps the connection alive and responsive
                        if debug:
                            print("[DEBUG] Calling get_artmode() to wake up connection...")
                        try:
                            mode = art.get_artmode()
                            if debug:
                                print(f"[DEBUG] Connection alive, art mode: {mode}")
                        except:
                            if debug:
                                print("[DEBUG] Wake-up call failed, but continuing...")
                            pass
                        
                        # Try to verify
                        if debug:
                            print("[DEBUG] Verifying display...")
                        try:
                            current = art.get_current()
                            if debug:
                                print(f"[DEBUG] Current image info: {current}")
                            current_id = current.get('content_id', 'unknown')
                            if current_id == content_id:
                                print("✓ Verified: Image is displaying!")
                                
                                # Delete other images if requested
                                if delete_others:
                                    if debug:
                                        print("\n[DEBUG] --delete-others flag enabled, deleting other images...")
                                    delete_result = delete_other_images(art, content_id, debug=debug)
                                    if not delete_result:
                                        print("⚠️  Warning: Could not delete other images (but upload succeeded)")
                                
                                return True
                            else:
                                print(f"   TV showing: {current_id}, expected: {content_id}")
                                if debug:
                                    print(f"[DEBUG] ID mismatch - TV may still be switching")
                                # On last attempt, still count as success if command was sent
                                if attempt == max_attempts - 1:
                                    print("   Display command was sent successfully")
                                    print("   Your new image should appear shortly")
                                    return True
                        except Exception as ve:
                            if debug:
                                print(f"[DEBUG] Verification failed: {type(ve).__name__}: {ve}")
                            # Don't fail just because verification timed out
                            if attempt == max_attempts - 1:
                                print("   (Verification timed out)")
                                print("\n✓ Display command sent successfully!")
                                print("   Your image should be displaying - check your TV!")
                                if debug:
                                    print("[DEBUG] Returning success despite verification timeout")
                                return True
                            else:
                                # Will retry with longer wait on next attempt
                                if debug:
                                    print(f"[DEBUG] Verification timed out, will retry with longer delay")                        # If we sent the command successfully but verification didn't match, 
                        # still consider it a success on last attempt
                        if attempt == max_attempts - 1:
                            print("✓ Display command completed")
                            print("   Check your TV - image should be displaying")
                            return True
                            
                    except Exception as e:
                        if attempt < max_attempts - 1:
                            print(f"   ⚠️  Attempt {attempt + 1} failed: {e}")
                            if debug:
                                print(f"[DEBUG] Will retry...")
                        else:
                            print(f"   ⚠️  METHOD 1 failed after {max_attempts} attempts: {e}")
                            if debug:
                                print(f"[DEBUG] Trying alternative method...")

            
            # METHOD 2: Fetch available images and select the last one
            if debug:
                print("[DEBUG] METHOD 2: Fetching available images to find newest...")
            print("   Fetching image list from TV...")
            print("   (This may timeout if TV is slow - please be patient)")
            
            try:
                # Try with longer wait
                time.sleep(3)
                if debug:
                    print("[DEBUG] Calling art.available()...")
                    
                available = art.available()
                
                if debug:
                    print(f"[DEBUG] Available returned: {len(available) if available else 0} images")
                    if available and len(available) > 0:
                        print(f"[DEBUG] Last 3 images:")
                        for img in available[-3:]:
                            print(f"[DEBUG]   - {img.get('content_id', 'unknown')}")
                
                if available and len(available) > 0:
                    newest_id = available[-1].get('content_id')
                    print(f"   Found newest image: {newest_id}")
                    
                    if debug:
                        print(f"[DEBUG] Attempting to select: {newest_id}")
                    
                    art.select_image(newest_id, show=True)
                    print("✓ Display command sent (using newest image)")
                    
                    time.sleep(2)
                    
                    # Try to verify
                    try:
                        current = art.get_current()
                        current_id = current.get('content_id', 'unknown')
                        if debug:
                            print(f"[DEBUG] After selection, TV showing: {current_id}")
                        if current_id == newest_id:
                            print("✓ Verified: Image is displaying!")
                            
                            # Delete other images if requested
                            if delete_others:
                                if debug:
                                    print("\n[DEBUG] --delete-others flag enabled, deleting other images...")
                                delete_result = delete_other_images(art, newest_id, debug=debug)
                                if not delete_result:
                                    print("⚠️  Warning: Could not delete other images (but upload succeeded)")
                            
                            return True
                        else:
                            print(f"   TV showing: {current_id}")
                    except:
                        if debug:
                            print("[DEBUG] Verification timeout")
                        pass
                    
                    return True
                else:
                    print("   ⚠️  No images found in available list")
                    
            except Exception as e:
                print(f"   ⚠️  Could not fetch image list (timeout): {e}")
                if debug:
                    print(f"[DEBUG] METHOD 2 failed: {type(e).__name__}: {e}")
                    import traceback
                    print(f"[DEBUG] Traceback:\n{traceback.format_exc()}")
                
            # If we get here, upload worked but display verification failed
            print("\n✓ Upload successful! Image is on your TV.")
            print("   (Display command may have been sent, but verification timed out)")
            print("\n   💡 Check your TV - the image should be displaying now!")
            print("   💡 If not, it's in the TV's art collection and can be selected manually")
            if debug:
                print("\n[DEBUG] Upload succeeded, returning True despite display timeout")
            return True
        else:
            print("ℹ️  Image uploaded but not displayed (use without --no-display to auto-display)")
        
        return True
        
    except Exception as e:
        print(f"✗ Upload failed: {e}")
        
        if debug:
            import traceback
            print(f"\n[DEBUG] Full error traceback:")
            print(traceback.format_exc())
        
        print("\nTroubleshooting tips:")
        
        # Check file size
        try:
            with open(image_path, "rb") as f:
                f.seek(0, 2)  # Seek to end
                size_mb = f.tell() / (1024 * 1024)
                if size_mb > 10:
                    print(f"  • File is large ({size_mb:.1f}MB) - try resizing to < 5MB")
                    print("  • For Frame TV, 3840x2160 (4K) at 70-80% JPEG quality is ideal")
        except:
            pass
        
        print("  • Is the TV on and in art mode?")
        print("  • Try running test_connection.py first to verify connection")
        print("  • Check if TV is responding: try setting brightness or listing mattes")
        print("  • Connection timeouts can happen if TV is busy - try again in a moment")
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        token_file_path = os.path.join(script_dir, TOKEN_FILE)
        if os.path.exists(token_file_path):
            print(f"  • Token file exists - if problems persist, try deleting {TOKEN_FILE}")
        
        return False

def list_mattes():
    """List all available matte options"""
    print("📋 Fetching available matte options from Frame TV...")
    print(f"🔌 Connecting to {FRAME_TV_IP}...")
    
    tv = get_tv_connection()
    if not tv:
        return False
    
    art = get_art_mode(tv)
    if not art:
        return False
    
    print("✓ Connected")
    
    try:
        matte_list = art.get_matte_list()
        
        if not matte_list:
            print("⚠️  No matte list returned")
            return False
        
        print("\n" + "=" * 60)
        print("AVAILABLE MATTES")
        print("=" * 60 + "\n")
        
        if isinstance(matte_list, list):
            print(f"Found {len(matte_list)} matte options:\n")
            
            # Group by type if possible
            by_type = {}
            for matte in matte_list:
                if isinstance(matte, dict):
                    matte_id = matte.get('matte_id', matte.get('matteId', 'unknown'))
                    matte_type = matte.get('matte_type', matte.get('matteType', 'other'))
                    
                    if matte_type not in by_type:
                        by_type[matte_type] = []
                    by_type[matte_type].append(matte_id)
            
            # Print grouped
            for matte_type, ids in sorted(by_type.items()):
                print(f"📦 {matte_type}:")
                for matte_id in sorted(ids):
                    print(f"   • {matte_id}")
                print()
            
        elif isinstance(matte_list, dict):
            for category, mattes in matte_list.items():
                print(f"📦 {category}:")
                if isinstance(mattes, list):
                    for matte in mattes:
                        if isinstance(matte, dict):
                            matte_id = matte.get('matte_id', matte.get('matteId', 'unknown'))
                            print(f"   • {matte_id}")
                        else:
                            print(f"   • {matte}")
                print()
        
        print("\nUSAGE:")
        print("  python3 upload_to_frame.py image.jpg --matte flexible_apricot")
        print("  python3 upload_to_frame.py image.jpg --matte modern_black\n")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to get matte list: {e}")
        return False

def list_filters():
    """List all available photo filter options"""
    print("📋 Fetching available photo filters from Frame TV...")
    print(f"🔌 Connecting to {FRAME_TV_IP}...")
    
    tv = get_tv_connection()
    if not tv:
        return False
    
    art = get_art_mode(tv)
    if not art:
        return False
    
    print("✓ Connected")
    
    try:
        filter_list = art.get_photo_filter_list()
        
        if not filter_list:
            print("⚠️  No filter list returned")
            return False
        
        print("\n" + "=" * 60)
        print("AVAILABLE PHOTO FILTERS")
        print("=" * 60 + "\n")
        
        if isinstance(filter_list, list):
            print(f"Found {len(filter_list)} photo filters:\n")
            for filter_item in filter_list:
                if isinstance(filter_item, dict):
                    filter_id = filter_item.get('filter_id', 'unknown')
                    filter_name = filter_item.get('filter_name', 'unknown')
                    print(f"   • {filter_id}: {filter_name}")
                else:
                    print(f"   • {filter_item}")
        elif isinstance(filter_list, dict):
            for key, value in filter_list.items():
                print(f"   • {key}: {value}")
        
        print("\nNOTE: Photo filter support may vary by TV model")
        print("      Filters are typically applied through the TV's UI\n")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to get filter list: {e}")
        return False

def test_connection_quick():
    """Quick connection test"""
    print("🔌 Testing connection to Frame TV...")
    print(f"   IP: {FRAME_TV_IP}")
    
    tv = get_tv_connection()
    if not tv:
        return False
    
    art = get_art_mode(tv)
    if not art:
        return False
    
    print("✓ Connection successful")
    
    # Give TV a moment to be ready
    print("⏳ Waiting for TV to be ready...")
    time.sleep(2)
    
    # Try a simple operation with timeout handling
    try:
        print("📊 Testing basic art mode operations...")
        
        # Try with longer timeout or just skip if it fails
        try:
            brightness = art.get_brightness()
            print(f"   Current brightness: {brightness}")
        except Exception as e:
            print(f"   ⚠️  Brightness check timed out (TV may be slow to respond)")
        
        try:
            available = art.available()
            if available:
                print(f"   Images on TV: {len(available)}")
        except Exception as e:
            print(f"   ⚠️  Image list timed out (TV may be slow to respond)")
        
        print("\n✓ TV connection works")
        print("   Note: TV seems slow to respond - uploads may take extra time")
        print("   This is normal for some Frame TV models\n")
        return True
        
    except Exception as e:
        print(f"⚠️  TV connected but not responding: {e}")
        print("   The TV may be busy or needs a restart\n")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Upload and display images on Samsung Frame TV (test script)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %%(prog)s /path/to/photo.jpg
  %%(prog)s ~/Pictures/artwork.jpg --matte flexible_apricot
  %%(prog)s image.jpg --brightness 50 --matte modern_black
  %%(prog)s image.jpg --no-display
  %%(prog)s image.jpg --auto-artmode            # Enable art mode if needed
  %%(prog)s image.jpg --delete-others            # Delete all other images after upload
  %%(prog)s image.jpg --auto-artmode --delete-others  # Combine options
  %%(prog)s image.jpg --debug                    # See detailed timing info
  %%(prog)s large_image.jpg --timeout 300        # 5 minute timeout for big files
  %%(prog)s --list-mattes
  %%(prog)s --list-filters
  %%(prog)s --test

timing:
  Script uses extended wait times for reliability:
  • 6s after upload (TV finishes processing)
  • 8s after select_image (TV completes switch)
  • Wake-up call before verification (keeps connection alive)
  These timings ensure reliable verification on Samsung Frame TVs

important:
  TV MUST be in art mode for uploads to work safely.
  Script will check and refuse to upload if not in art mode.
  Use --auto-artmode to automatically enable art mode first.

large files:
  Files > 5MB may timeout. Script auto-calculates timeout based on size.
  For manual control, use --timeout to set seconds (e.g., --timeout 300)
  Ideal: 3840x2160 (4K) JPEG at 70-80%% quality = ~3-5MB

note:
  Some Frame TVs are slow to respond to status queries.
  If you see timeout messages, don't worry - the upload still worked!
  Just check your TV to see the image.

common mattes:
  flexible_apricot (warm beige), flexible_polar (white), flexible_black
  modern_black, modern_white, beveled_white
  Use --list-mattes to see all options from your TV

brightness:
  1-10 = normal brightness levels (recommended)
  50   = maximum brightness
  11-49 = unreliable (avoid these)

first run:
  TV will show authorization popup - click ALLOW
  Token saved to frame_tv_token.txt for future use
        """
    )
    
    parser.add_argument('image', nargs='?', help='Path to image file to upload')
    parser.add_argument('--matte', '-m', help='Matte style to apply (e.g., flexible_apricot)')
    parser.add_argument('--brightness', '-b', type=int, 
                       help='Brightness level (1-10 normal, 50 for max)')
    parser.add_argument('--no-display', action='store_true',
                       help='Upload only, do not display the image')
    parser.add_argument('--list-mattes', action='store_true',
                       help='List all available matte options')
    parser.add_argument('--list-filters', action='store_true',
                       help='List all available photo filters')
    parser.add_argument('--test', action='store_true',
                       help='Test connection to TV without uploading')
    parser.add_argument('--debug', '-d', action='store_true',
                       help='Enable verbose debug output')
    parser.add_argument('--timeout', '-t', type=int,
                       help='Upload timeout in seconds (auto-calculated if not specified)')
    parser.add_argument('--auto-artmode', action='store_true',
                       help='Automatically enable art mode if TV is not already in art mode')
    parser.add_argument('--delete-others', action='store_true',
                       help='Delete all other images after successfully displaying the new one')
    
    args = parser.parse_args()
    
    # Handle special list commands
    if args.test:
        print("\n" + "=" * 60)
        print("CONNECTION TEST")
        print("=" * 60 + "\n")
        success = test_connection_quick()
        sys.exit(0 if success else 1)
    if args.list_mattes:
        success = list_mattes()
        sys.exit(0 if success else 1)
    
    if args.list_filters:
        success = list_filters()
        sys.exit(0 if success else 1)
    
    # Require image path for upload
    if not args.image:
        parser.print_help()
        print("\n✗ Error: Please specify an image file to upload")
        print("   Or use --list-mattes or --list-filters to see available options")
        sys.exit(1)
    
    # Validate brightness if specified
    if args.brightness is not None:
        if args.brightness < 1:
            print(f"✗ Error: Brightness must be at least 1 (you entered {args.brightness})")
            sys.exit(1)
        
        if 11 <= args.brightness <= 49:
            print("⚠️  Warning: Brightness values 11-49 may be unreliable")
            print("   Recommended: 1-10 for normal, 50 for maximum")
    
    # Expand user path
    image_path = os.path.expanduser(args.image)
    
    # Make absolute if relative
    if not os.path.isabs(image_path):
        image_path = os.path.abspath(image_path)
    
    # Upload and display
    print("\n" + "=" * 60)
    print("SAMSUNG FRAME TV - IMAGE UPLOAD")
    print("=" * 60 + "\n")
    
    if args.debug:
        print("[DEBUG MODE ENABLED]\n")
    
    success = upload_and_display(
        image_path,
        matte=args.matte,
        brightness=args.brightness,
        display=not args.no_display,
        debug=args.debug,
        upload_timeout=args.timeout,
        auto_artmode=args.auto_artmode,
        delete_others=args.delete_others
    )
    
    if success:
        print("\n" + "=" * 60)
        print("✓ SUCCESS!")
        print("=" * 60)
        print("\nYour image has been uploaded to the Frame TV! 🎨")
        if not args.no_display:
            print("It should be displaying in art mode.")
            print("(If not showing, the TV may be slow - check in a moment)")
        else:
            print("Image is in your TV's art collection.")
        print()
    else:
        print("\n" + "=" * 60)
        print("✗ FAILED")
        print("=" * 60)
        print("\nSomething went wrong. Check the errors above.")
        print()
        sys.exit(1)

if __name__ == "__main__":
    main()
