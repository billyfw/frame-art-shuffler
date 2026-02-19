# Getting Started: Samsung Frame Art Manager + Shuffler

A step-by-step guide to setting up the full Samsung Frame TV art management system in Home Assistant.

## What You're Setting Up

There are **two separate components** that work together:

| Component | Type | What it does | How to install |
|-----------|------|-------------|----------------|
| **Frame Art Shuffler** | HA Custom Integration | Talks to your Frame TVs. Handles pairing, art uploads, brightness, shuffling, motion control. | HACS (Integrations) |
| **Frame Art Manager** | HA Add-on | Web UI for uploading images, tagging, applying mattes/filters. Manages your art library. | Add-on Store (Repository) |

The **Shuffler** is the engine (controls TVs). The **Manager** is the cockpit (manages your image library and sends commands to the Shuffler). You can run the Shuffler alone for basic TV control, but you need both for the full experience.

---

## Prerequisites

- Home Assistant (2024.6.0 or later)
- [HACS](https://hacs.xyz/) installed
- Samsung Frame TV on the same network as your HA instance
- Your Frame TV's **IP address** and **MAC address**
  - IP: Check your router's DHCP list, or go to TV Settings > General > Network > Network Status
  - MAC: Same network status screen, or check your router
  - Tip: Assign a static IP to your Frame TV in your router so it doesn't change

---

## Step 1: Install Frame Art Shuffler (the integration)

This is the core component that communicates with your Samsung Frame TV.

1. Open Home Assistant
2. Go to **HACS > Integrations**
3. Click the **three dots menu (top right) > Custom repositories**
4. Add repository URL: `https://github.com/billyfw/frame-art-shuffler`
5. Category: **Integration**
6. Click **Add**, then close the dialog
7. Search for **"Frame Art Shuffler"** in HACS Integrations and click **Download**
8. **Restart Home Assistant** (Settings > System > Restart)

After restart:

9. Go to **Settings > Devices & Services > Add Integration**
10. Search for **"Frame Art Shuffler"** and select it
11. Enter a **Home name** (can be anything, e.g., "My Home" -- this is just a label)
12. The integration is now installed but has no TVs yet

---

## Step 2: Install layout-card (required for the dashboard)

The Shuffler's auto-generated dashboard uses the `layout-card` custom frontend card for responsive layout. **Without this, the dashboard will show errors.**

1. Go to **HACS > Frontend**
2. Click **Explore & Download Repositories**
3. Search for **"layout-card"** and install it
4. **Restart Home Assistant**

---

## Step 3: Add your Frame TV

1. Go to **Settings > Devices & Services**
2. Find the **Frame Art Shuffler** integration card
3. Click **Configure**
4. Select **Add TV**
5. Enter:
   - **TV Name**: Whatever you want (e.g., "Living Room Frame")
   - **IP Address**: Your TV's IP
   - **MAC Address**: Your TV's MAC address (needed for Wake-on-LAN)
   - **Shuffle Frequency**: How often to change art (in minutes, e.g., 60)
6. Click **Submit**

**Important -- TV Pairing:**
- When you submit, the integration will attempt to pair with your TV
- **Your TV must be ON** (not in standby/art mode -- actually on, showing the home screen or an app)
- A popup will appear on your TV asking to "Allow" or "Deny" the connection
- Select **"Allow"** using your TV remote
- A token file is saved automatically -- you won't need to approve again

If pairing fails:
- Make sure the TV is powered on and awake (not just displaying art)
- Make sure the TV and HA are on the same network/VLAN
- Try again from Settings > Devices & Services > Frame Art Shuffler > Configure > Add TV

---

## Step 4: Register the dashboard in configuration.yaml

The integration auto-generates a Lovelace dashboard YAML file when you add TVs. You need to tell Home Assistant about it.

1. Edit your `configuration.yaml` file (via File Editor add-on, VS Code add-on, or SSH)
2. Add this block:

```yaml
lovelace:
  mode: storage
  dashboards:
    frame-art-shuffler:
      mode: yaml
      title: Frame Art Shuffler
      icon: mdi:television-ambient-light
      show_in_sidebar: true
      filename: custom_components/frame_art_shuffler/dashboards/frame_tv_manager.yaml
```

**Note:** If you already have a `lovelace:` section in your configuration.yaml, merge the `dashboards:` block into it rather than duplicating the top-level key.

3. **Restart Home Assistant**
4. You should now see **"Frame Art Shuffler"** in the sidebar

---

## Step 5: Verify the Shuffler is working

At this point, the integration should be functional:

- In **Settings > Devices & Services > Frame Art Shuffler**, you should see your TV as a device
- Click on the device to see all its entities (sensors, buttons, switches, etc.)
- The sidebar dashboard should show controls for your TV (brightness slider, shuffle button, on/off, etc.)
- To **edit or delete a TV**: Go to Settings > Devices & Services > Frame Art Shuffler > **Configure** (not the device page -- the integration's Configure button)

**Troubleshooting the dashboard:**
- If the dashboard is blank or shows errors, make sure `layout-card` is installed (Step 2)
- If you see "file not found" type errors, make sure you've added at least one TV first (Step 3) -- the dashboard YAML file is generated when a TV is added
- Check your Home Assistant logs for errors: Settings > System > Logs, filter for `frame_art_shuffler`

---

## Step 6: Install Frame Art Manager (the add-on) -- Optional but Recommended

This gives you the web UI for uploading and managing artwork. Without it, the Shuffler has no image library to work with (you'd need to manually create a `metadata.json`).

### 6a. Create the artwork directory

Before starting the add-on, you need to prepare where it will store images. You have two options:

**Option A: Local-only (simplest, no backup)**

SSH into your Home Assistant host (via the SSH & Web Terminal add-on) and run:

```bash
mkdir -p /config/www/frame_art
cd /config/www/frame_art
git init
```

That `git init` creates a local Git repository with no remote. This is needed because the Manager uses `git mv` internally when renaming images -- without it, renames will fail. Everything else (uploads, deletes, tagging, displaying) works without Git, but renaming is common enough that you'll want this.

No GitHub account, no SSH keys, no Git LFS needed. Your images just live locally on the HA box with no off-device backup.

**Option B: Git LFS with remote backup (more involved)**

This backs up your entire art library to a GitHub repository using Git LFS (Large File Storage). You get version history and off-device backup, but it requires more setup:

1. Create a GitHub repository for your artwork (e.g., `your-username/frame_art`)
2. Install Git + Git LFS on your HA host:
   ```bash
   apk add git git-lfs
   git lfs install --system
   ```
3. Set up an SSH key on the HA host and add it to your GitHub account
4. Clone your repo:
   ```bash
   cd /config/www
   git clone git@github.com:your-username/frame_art.git frame_art
   ```
5. Configure Git LFS for SSH (the add-on normalizes this on startup, but to be safe):
   ```bash
   cd /config/www/frame_art
   git config remote.origin.lfsurl ssh://git@github.com/your-username/frame_art
   git config lfs.url ssh://git@github.com/your-username/frame_art
   ```

If you go with Option B, you'll also need to provide your SSH private key in the add-on configuration (see below).

### 6b. Install and configure the add-on

1. Go to **Settings > Add-ons > Add-on Store**
2. Click the **three dots menu (top right) > Repositories**
3. Add repository URL: `https://github.com/billyfw/ha-frame-art-manager`
4. Click **Add**, then close
5. Find **"Frame Art Manager"** in the store and click **Install**
6. In the add-on's **Configuration** tab, set:
   - `frame_art_path`: `/config/www/frame_art` (default, should be fine)
   - `port`: `8099` (default)
   - `ssh_private_key`: Only needed if you chose Option B above
7. Click **Start**
8. Toggle **"Start on boot"** and **"Show in sidebar"** if desired

The add-on creates the `library/`, `thumbs/`, and `originals/` subdirectories and an initial `metadata.json` automatically on first start. You'll see some Git warnings in the add-on log if you used Option A -- that's normal and can be ignored. Sync features just won't be available.

---

## Step 7: Upload your first image

1. Open the Frame Art Manager (click it in the sidebar, or go to the add-on page and click **Open Web UI**)
2. Go to the **Upload** tab
3. Drag and drop an image or click to browse
4. Add tags if desired (e.g., "landscape", "family")
5. Optionally apply a matte style and filter
6. Click Upload

The image is now in your library. The Shuffler will include it in its rotation based on the tags and tagsets you configure.

---

## Step 8: Display art on your TV

From the Frame Art Manager web UI:
- Go to the **Gallery** tab
- Click on an image
- Click **Display on TV** and select which TV

Or let the Shuffler handle it automatically:
- Make sure **Auto Shuffle** is enabled for your TV (in the dashboard or via the switch entity)
- The Shuffler will pick images from your library based on the active tagset and display them at the configured interval

---

## Architecture Overview

```
You (phone/browser)
    |
    v
Frame Art Manager (web UI, port 8099)
    |
    |-- Manages images in /config/www/frame_art/
    |-- Reads/writes metadata.json (image tags, mattes, filters)
    |-- Calls Frame Art Shuffler services via HA API
    |
    v
Frame Art Shuffler (HA integration)
    |
    |-- Reads metadata.json for image library
    |-- Manages shuffle logic, tagsets, recency
    |-- Controls TV brightness, power, art mode
    |
    v
Samsung Frame TV (WebSocket on port 8002)
    |
    |-- Receives images, displays art
    |-- Reports art mode / screen state
```

---

## Common Issues

**"I can't see anything on the dashboard"**
- Is `layout-card` installed? (HACS > Frontend)
- Did you add the `lovelace:` block to `configuration.yaml`?
- Did you restart HA after both changes?
- Did you add at least one TV? (the dashboard YAML is generated when TVs are added)

**"TV pairing failed"**
- TV must be fully awake (not just art mode standby)
- TV and HA must be on the same network
- Try power cycling the TV and retrying

**"I can edit but not delete a TV"**
- TV management (add/edit/delete) is in: Settings > Devices & Services > Frame Art Shuffler > **Configure**
- This is different from clicking on the device itself

**"Frame Art Manager can't control my TV"**
- The Manager doesn't talk to TVs directly -- it calls Shuffler services
- Make sure the Shuffler integration is running and the TV is added there first
- Check that the TV was paired successfully (token file exists)

**"Images aren't shuffling"**
- Is Auto Shuffle enabled for the TV? (check the switch entity)
- Does your active tagset match any images in the library?
- Is the TV in art mode? (shuffling only happens when art mode is enabled)
- Check HA logs for shuffle-related messages

**"Renaming an image fails with a Git error"**
- The Manager uses `git mv` internally for renames. Your `frame_art` directory needs to be a Git repository
- If you set up without Git, the fix is simple: SSH into HA and run `cd /config/www/frame_art && git init`
- Everything else (upload, delete, tag, display) works without Git -- only rename requires it

**"I installed via HACS but it's not showing up"**
- Did you restart Home Assistant after the HACS download?
- After restart, go to Settings > Devices & Services > **Add Integration** (you still need to add it manually after HACS installs the files)
