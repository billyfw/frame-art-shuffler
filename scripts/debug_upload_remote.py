import logging
import sys
import time
from pathlib import Path

# Configure logging to stdout
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout
)

# Add the integration directory to path so we can import samsungtvws
sys.path.append("/config/custom_components/frame_art_shuffler")

try:
    from samsungtvws import SamsungTVWS
except ImportError:
    print("Could not import samsungtvws. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "samsungtvws"])
    from samsungtvws import SamsungTVWS

# Configuration
TV_IP = "192.168.1.249"
TOKEN_FILE = f"/config/custom_components/frame_art_shuffler/tokens/{TV_IP}.token"
IMAGE_FILE = "samready-57b9e82a.jpg"  # We'll need to find where this is or use a dummy

print(f"Connecting to {TV_IP} using token {TOKEN_FILE}...")

try:
    tv = SamsungTVWS(
        host=TV_IP,
        port=8002,
        token_file=TOKEN_FILE,
        timeout=30,
        name="FrameArtDebug"
    )
    
    # Test Remote Connection
    print("Testing Remote Channel...")
    tv.open()
    print("Remote Channel OK")
    tv.close()

    # Test Art Connection
    print("Testing Art Channel...")
    art = tv.art()
    images = art.available()
    print(f"Art Channel OK. Found {len(images)} images.")
    
    # Create a dummy image to upload if needed
    if not Path(IMAGE_FILE).exists():
        print(f"Creating dummy image {IMAGE_FILE}...")
        with open(IMAGE_FILE, "wb") as f:
            f.write(b"\xFF" * 1024 * 1024) # 1MB dummy file
            
    # Test Upload
    print(f"Attempting upload of {IMAGE_FILE}...")
    with open(IMAGE_FILE, "rb") as f:
        data = f.read()
        
    print(f"Read {len(data)} bytes. Sending...")
    start_time = time.time()
    
    # This is the call that hangs
    content_id = art.upload(data, file_type="jpg", matte="none")
    
    duration = time.time() - start_time
    print(f"Upload SUCCESS! Content ID: {content_id}")
    print(f"Time taken: {duration:.2f} seconds")

except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
