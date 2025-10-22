# Samsung Frame TV - Quick Test & Upload Script

A simple script to upload images to your Samsung Frame TV with proper timing, error handling, and automatic cleanup.

**✨ Key Features:**
- ✅ Reliable uploads with optimized timing (6s + 8s delays)
- ✅ Automatic art mode detection and activation
- ✅ **NEW: `--delete-others` flag** to keep only the current image on your TV
- ✅ Debug mode to see exactly what's happening
- ✅ Works with Home Assistant automations

**Quick Example:**
```bash
# Upload image and delete all others (perfect for daily rotation)
python3 upload_to_frame.py new_artwork.jpg --auto-artmode --delete-others
```

## TL;DR - Critical Timing Pattern

**The TV needs processing time between operations. Use this pattern for reliable uploads:**

```python
# 1. Upload the image
content_id = art.upload(image_path)  # Returns string like "MY_F0044"

# 2. WAIT for TV to process upload
time.sleep(6)  # CRITICAL: TV needs time to process the file

# 3. Display the image
art.select_image(content_id, show=True)

# 4. WAIT for TV to switch images
time.sleep(8)  # CRITICAL: TV needs time to switch displays

# 5. Wake-up call to keep connection alive
art.get_artmode()  # Ping the websocket before verification

# 6. NOW you can verify (much more likely to succeed)
current = art.get_current()

# 7. OPTIONAL: Delete other images (only after verification succeeds)
if current == content_id:
    time.sleep(3)  # Wait before fetching list
    available = art.available()
    to_delete = [img['content_id'] for img in available if img['content_id'] != content_id]
    art.delete_list(to_delete)
    time.sleep(4)  # Wait for TV to process deletions
```

**Why this works:**
- 6 seconds after upload: TV finishes processing the file
- 8 seconds after select_image: TV completes the display switch
- Wake-up call: Keeps websocket connection responsive
- **Without these waits, verification will timeout even though the command succeeded**

---

## Important: Frame TV API Timing Notes

**Critical Discovery:** The Samsung Frame TV needs time to process commands before it can respond to status queries.

### Key Lessons Learned:

1. **Upload Response Format:**
   - The `art.upload()` method returns the content_id as a **string**, not a dict
   - Example: `"MY_F0044"` (not `{"content_id": "MY_F0044"}`)
   - Always check `isinstance(response, str)` first

2. **Command Processing Delays:**
   - After `art.upload()` completes, **wait 6 seconds** before calling `select_image()`
     - TV needs time to finish processing the uploaded image
     - Without this wait, `select_image()` will timeout
   - After calling `art.select_image(content_id, show=True)`, **wait 8 seconds** before calling any status methods
     - The TV needs time to actually switch the image
     - Calling `art.get_current()` immediately will timeout
   - **Wake-up call technique**: Call `art.get_artmode()` before verification
     - This keeps the websocket connection alive and responsive
     - Without this, the connection goes "idle" and verification timeouts occur
     - This simple ping makes verification much more reliable

3. **Timeout Behavior:**
   - Websocket operations can timeout (30+ seconds)
   - Methods like `art.available()`, `art.get_current()`, and even `art.select_image()` are prone to timeouts
   - **IMPORTANT:** Timeouts don't mean failure!
     - If `select_image()` times out, the command was still sent and the image will display
     - The TV just didn't respond quickly enough over the websocket
     - This is a library/TV limitation, not an error in your code
   - The TV may be "slow" but it's not broken - it's just processing

4. **Retry Strategy:**
   - If a command times out, wait 3-6 seconds and retry
   - Use exponential backoff: 3s, 6s between retries
   - The TV often responds on retry after being given time

5. **Success != Verification:**
   - Upload success doesn't require verification
   - If upload returns a content_id, the image IS on the TV
   - If `select_image()` doesn't throw an error, the command was sent
   - Don't fail the entire operation just because verification timed out

### **TV Must Be On AND In Art Mode!**

⚠️ **CRITICAL:** These commands **require specific TV state**!

**Requirements:**
1. **TV must be powered on** (not off)
2. **TV must be in art mode** (not showing regular content)

**Why Art Mode Matters:**
- Uploading while TV shows regular content can cause the TV to enter a bad state
- TV may become unresponsive and require power cycling
- Upload will likely timeout or fail
- The `upload_to_frame.py` script checks art mode and refuses to upload if not in art mode

**Checking Art Mode:**
```python
artmode = art.get_artmode()  # Returns 'on' if in art mode
```

**Enabling Art Mode:**
```python
art.set_artmode(True)
time.sleep(3)  # Wait for TV to switch
```

**For Command Line:**
```bash
# Script will check and refuse if not in art mode
python3 upload_to_frame.py image.jpg

# Automatically enable art mode if needed
python3 upload_to_frame.py image.jpg --auto-artmode
```

### **Delete Other Images After Upload**

⚠️ **NEW FEATURE:** Automatically clean up old images after uploading a new one!

The `--delete-others` flag will delete all other images on the Frame TV after successfully displaying your newly uploaded image.

**Use Cases:**
- Keep only the current image on the TV (no clutter)
- Home automation: rotate a single image daily without accumulating old ones
- Digital signage: always show exactly one current image

**How It Works:**
1. Uploads your new image to the TV
2. Displays it in art mode
3. **Waits for verification** that the image is displaying
4. Fetches the list of all images on the TV
5. Deletes all images except the newly uploaded one

**Command Line:**
```bash
# Upload, display, and delete all other images
python3 upload_to_frame.py new_image.jpg --delete-others

# Combine with auto art mode
python3 upload_to_frame.py new_image.jpg --auto-artmode --delete-others

# Enable debug to see what's being deleted
python3 upload_to_frame.py new_image.jpg --delete-others --debug
```

**Important Timing Notes:**
- Deletion only happens **after successful verification** that the new image is displaying
- The script waits 3 seconds before fetching the image list (TV needs time to settle)
- The script waits 4 seconds after deletion (TV needs time to process)
- If display verification fails, **deletion will NOT occur** (safe by default)

**Safety:**
- Your new image is never deleted (it's explicitly excluded from the delete list)
- If verification fails, old images are kept (won't delete if unsure)
- Uses the TV's native batch delete API (`delete_list`) for efficiency

### **File Size Limits!**

⚠️ **IMPORTANT:** Large files will timeout during upload!

**Practical Limits:**
- **< 5MB**: Reliable uploads (recommended)
- **5-10MB**: May work but can be slow/unreliable
- **> 10MB**: Will almost certainly timeout

**Why:** The Samsung TV's websocket has a hardcoded ~30-60 second timeout. Large files can't be transferred in that time.

**Solution:** Use the resize helper script:
```bash
# Resize image to optimal size for Frame TV
./resize_for_frame.sh large_photo.jpg

# Then upload the resized version
python3 upload_to_frame.py large_photo_resized.jpg
```

**Optimal Settings:**
- Resolution: 3840x2160 (4K - Frame TV native resolution)
- Format: JPEG
- Quality: 70-80%
- Result: 3-5MB file size

**Manual Resize Options:**
```bash
# macOS Preview: File → Export → Quality 70%

# macOS sips command:
sips --resampleWidth 3840 --setProperty formatOptions 75 input.jpg --out output.jpg

# ImageMagick:
convert input.jpg -resize 3840x2160 -quality 75 output.jpg
```

**For Home Assistant Integrations:**
```yaml
# ❌ BAD: This will fail if TV is off
- service: shell_command.upload_frame_art
  data:
    image_path: "/path/to/image.jpg"

# ✅ GOOD: Ensure TV is on first
- service: media_player.turn_on
  target:
    entity_id: media_player.samsung_frame_tv
- delay:
    seconds: 5  # Give TV time to fully boot
- service: shell_command.upload_frame_art
  data:
    image_path: "/path/to/image.jpg"
```

**Design Considerations for Image Rotation:**
- **Pre-upload approach:** Upload images when TV is known to be on, build a library
  - Then rotate through existing images (works even if TV was off then turned on)
- **Just-in-time approach:** Only upload/display when TV is on
  - Requires checking TV state first
  - Needs sufficient delay after turning TV on (5-10 seconds)
- **Time-based approach:** Schedule uploads for times TV is typically on
  - Morning routines, evening hours, etc.

### Recommended Pattern:

```python
# Upload image
response = art.upload(image_data, file_type="JPEG", matte="flexible_apricot")
content_id = response  # It's a string!

# CRITICAL: Wait for TV to finish processing upload
time.sleep(6)

# Select/display the image
art.select_image(content_id, show=True)

# CRITICAL: Wait for TV to complete the switch
time.sleep(8)

# Wake-up call: Ping the connection to keep it alive
try:
    art.get_artmode()  # Simple call to wake up websocket
except:
    pass  # Ignore if it fails

# Now safe to verify (much more likely to succeed now)
try:
    current = art.get_current()
    current_id = current.get('content_id')
    print(f"Now showing: {current_id}")
    
    # OPTIONAL: Delete all other images (keeps only the new one)
    if current_id == content_id:  # Verify it's showing before deleting
        time.sleep(3)  # Wait for TV to settle
        available = art.available()
        to_delete = [img['content_id'] for img in available if img['content_id'] != content_id]
        if to_delete:
            print(f"Deleting {len(to_delete)} old image(s)...")
            art.delete_list(to_delete)
            time.sleep(4)  # Wait for TV to process deletions
            print("✓ Cleanup complete - only your new image remains!")
except TimeoutError:
    print("Verification timed out, but command was sent")
```

**Why These Timings:**
- **6 seconds** after upload: Empirically determined to be minimum for TV to finish processing
- **8 seconds** after select_image: TV needs this time to complete the image switch
- **Wake-up call**: Prevents websocket from going idle, dramatically improves verification success rate
- Total time for reliable upload + display + verify: ~15-20 seconds

### What NOT to Do:

```python
# ❌ BAD: No delay before verification
art.select_image(content_id, show=True)
current = art.get_current()  # Will likely timeout!

# ❌ BAD: Treating string response as dict
response = art.upload(...)
content_id = response.get('content_id')  # Fails if response is string!

# ❌ BAD: Failing on verification timeout
art.select_image(content_id, show=True)
current = art.get_current()  # Timeout = complete failure
```

---

## Quick Start (5 minutes)

### 1. Install the library
```bash
# Install directly from GitHub (this is the Frame TV fork)
pip3 install git+https://github.com/NickWaterton/samsung-tv-ws-api.git
```

### 2. Find your TV's IP address
On your Frame TV:
- Settings → General → Network → Network Status → IP Settings
- Write down the IP address (e.g., 192.168.1.100)

### 3. Get a test image
```bash
# Option A: Copy any existing image
cp ~/Pictures/some-photo.jpg frame_art_test/test.jpg

# Option B: Download a test image
curl -o test.jpg https://picsum.photos/3840/2160
```

### 4. Update the script
Edit `test_connection.py` and change:
```python
FRAME_TV_IP = "192.168.1.100"  # Put your TV's IP here
```

### 5. Run it!
```bash
cd frame_art_test
python3 test_connection.py
```

## What This Does

1. **Connects** to your Frame TV
2. **Switches** it to art mode (just by connecting!)
3. **Uploads** your test image
4. **Shows** you what other features are available

## Expected Output

If it works, you'll see:
```
✓ Connection successful!
✓ Art mode object created!
✓ Upload successful!
```

Then check your TV - your image should appear in the art collection!

## Troubleshooting

### "Connection failed"
- Is your TV on?
- Is it on the same network as your computer?
- Try pinging it: `ping YOUR_TV_IP`
- Check if the IP address is correct

### "Test image not found"
- Make sure `test.jpg` is in the same directory as the script
- Try using a different image format (JPEG/JPG only)

### "Upload failed"
- Image might be too large (try resizing to 3840x2160)
- Make sure it's a JPEG/JPG file
- TV might be in the middle of something - try again

## Next Steps

Once this works, you can:
1. **Use `--delete-others`** to keep only one image on the TV at a time
2. Create a Home Assistant automation to rotate images daily (with cleanup!)
3. Build scheduled uploads with automatic old image removal
4. Set up dynamic content (weather, calendar, family photos) with automatic cleanup

**Example Home Assistant Shell Command:**
```yaml
shell_command:
  update_frame_art: 'python3 /path/to/upload_to_frame.py "{{ image_path }}" --auto-artmode --delete-others'
```

**Example Daily Rotation:**
```yaml
automation:
  - alias: "Rotate Frame Art Daily"
    trigger:
      platform: time
      at: "06:00:00"
    action:
      - service: shell_command.update_frame_art
        data:
          image_path: "/path/to/daily/artwork.jpg"
    # Old images are automatically deleted, keeping TV clean!
```

But first - let's just see if this basic test works! 🎨
