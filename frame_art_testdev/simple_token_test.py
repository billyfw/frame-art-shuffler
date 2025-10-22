#!/usr/bin/env python3
"""
Minimal test to establish token authentication with Samsung Frame TV.
This script does ONE thing: get a token and save it.
"""

from samsungtvws import SamsungTVWS
import os
import time

# ====== CONFIGURATION ======
FRAME_TV_IP = "192.168.1.249"
TOKEN_FILE = "frame_tv_token.txt"
# ===========================

def main():
    print("=" * 70)
    print("MINIMAL TOKEN TEST - Samsung Frame TV")
    print("=" * 70)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    token_file_path = os.path.join(script_dir, TOKEN_FILE)
    
    # Check if token already exists
    if os.path.exists(token_file_path):
        print(f"\n⚠️  Token file already exists: {TOKEN_FILE}")
        response = input("Delete it and start fresh? (y/n): ")
        if response.lower() == 'y':
            os.remove(token_file_path)
            print("✓ Token file deleted")
        else:
            print("Exiting. Delete the token file manually to try again.")
            return
    
    print(f"\n📋 No token file found - will request new authentication")
    print(f"   Token will be saved to: {token_file_path}")
    
    print("\n" + "🚨 " * 35)
    print("👀 GET READY TO LOOK AT YOUR TV! 👀")
    print("🚨 " * 35)
    print("\nWhat will happen:")
    print("  1. Script will connect to TV")
    print("  2. A popup will appear on your TV (might take a few seconds)")
    print("  3. You click 'ALLOW' on the TV")
    print("  4. Token gets saved to file")
    print()
    input("Press ENTER when you're ready... ")
    
    print(f"\n⏳ Connecting to TV at {FRAME_TV_IP}...")
    print("   (Popup should appear on TV soon - be ready!)")
    
    try:
        # Create connection with token_file parameter
        # The library will handle the auth and save the token
        tv = SamsungTVWS(
            host=FRAME_TV_IP,
            port=8002,
            token_file=token_file_path,
            timeout=60  # Give plenty of time for approval
        )
        
        print("\n✓ Connection object created!")
        
        # FORCE the connection to open by sending a command
        print("\n⏳ Sending a command to trigger auth popup...")
        print("   >>> POPUP SHOULD APPEAR ON TV NOW! <<<")
        print("   >>> CLICK 'ALLOW' WHEN YOU SEE IT! <<<")
        
        try:
            # Open the connection explicitly
            tv.open()
            print("✓ Connection opened - popup should have appeared!")
            
            # Send a simple key press to ensure auth happens
            print("\n⏳ Sending a test command to complete auth...")
            tv.send_key("KEY_HDMI")  # Harmless key that won't change much
            print("✓ Command sent successfully!")
            
        except Exception as e:
            print(f"\n⚠️  Operation encountered an issue: {e}")
            print(f"   Error type: {type(e).__name__}")
            
            # Check if it's a timeout (means popup wasn't approved)
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                print("\n❌ This looks like a TIMEOUT error!")
                print("   The TV is waiting for you to click ALLOW")
                print("   Did you see and click the popup?")
            else:
                print("   This might still work if token was saved...")
        
        # Wait and check for token file
        print("\n⏳ Waiting for token to be saved...")
        print("   Checking every second for up to 30 seconds...")
        
        for i in range(30):
            time.sleep(1)
            
            if os.path.exists(token_file_path):
                # Token file exists, check if it has content
                with open(token_file_path, 'r') as f:
                    token_content = f.read().strip()
                
                if token_content:
                    print(f"\n✓✓✓ SUCCESS! Token saved after {i+1} seconds! ✓✓✓")
                    print(f"\nToken file: {TOKEN_FILE}")
                    print(f"Token length: {len(token_content)} characters")
                    print(f"Token preview: {token_content[:20]}...{token_content[-10:]}")
                    print("\n🎉 You can now use this token for future connections!")
                    print("   Future scripts won't need TV approval.")
                    return
            
            # Progress indicator every 5 seconds
            if (i + 1) % 5 == 0:
                print(f"   ... still waiting ({i+1}/30 seconds)")
                print("      Did you click ALLOW on the TV?")
        
        # Timeout
        print("\n❌ TIMEOUT: Token file was not created after 30 seconds")
        print("\nPossible issues:")
        print("  1. You didn't click 'ALLOW' on the TV popup")
        print("  2. The popup didn't appear (wrong IP address?)")
        print("  3. TV is not responding")
        print("  4. Network issue between computer and TV")
        print(f"\nTV IP we tried: {FRAME_TV_IP}")
        print("Double-check this is correct!")
        
    except Exception as e:
        print(f"\n❌ Connection failed with error:")
        print(f"   {type(e).__name__}: {e}")
        print("\nThis might mean:")
        print(f"  - TV is not reachable at {FRAME_TV_IP}")
        print("  - TV is off or in wrong mode")
        print("  - Firewall blocking connection")

if __name__ == "__main__":
    main()
