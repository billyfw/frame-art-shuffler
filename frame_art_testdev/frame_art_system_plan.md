Do not begin to implement yet. Just provide me steps. 

I want to construct a system to manage a library of images and samsung frame TVs in art mode, and to rotate those images to TVs. It will consist of the following components: 

1. frame_art git lfs repo, with thumbnails, images, and a json metadata file. Details: filenames of images will be some user provided text followed by a unique string to try to ensure no dupes. thumbnail filenames probably should be same image name maybe prepended with thumb_? json metadata file will need to hold, for each image, a value for matte, a value for filter, and tags for that image. not sure if we need to keep a master list of tags or not as well, and whether that should be in the same file. 

2. a frame_art_manager HA add on, tracked in a separate and public repo (so that HACS can automatically update it), that provides a webapp which can be used on a mobile phone (like in an iframe on HA dashboard) or local desktop, to: upload new images, tag them, manage their metadata; manage samsung frame TVs - IP addresses, etc., manage the git lfs / cloud sync of new images and to HA

3. An HA dashboard that lets us manage the showing of images on tvs; functions include: 
--static show an image on a particular tv
--set a tv to shuffle through images with a tag or tag(s)
--set the frequency of that shuffle (e.g. 2 min, 15 min, 1 day, etc.)
--view the status of TVs 

4. HA python shell scripts based on what we learned in #frame_art_testdev/README.md to actually manage the uploading, showing, and deleting of images on frame TVs

5. HA automation(s) to use the functions in 4 to actually perform image rotation and display

Examine the current state of #www/frame_art repo and the #frame_art_testdev/README.md, Make me a succinct list of planned steps to make this happen. 

Do not begin to implement yet. Just provide me steps.

---

## Implementation Plan

### Phase 1: Frame Art Repository Setup
1. **Enhance Git LFS repo structure** (`www/frame_art/`):
   - Add `metadata.json` with schema: `{images: [{filename, content_id, matte, filter, tags[], upload_date}], tags: [], tvs: []}`
   - Implement filename convention: `{user_text}_{uuid}.jpg`

### Phase 2: Frame Art Manager Add-on (separate public repo)
2. **Initialize new repo**: `ha-frame-art-manager`
   - Add-on directory structure for HACS compatibility
   - Node/Express web server for API and static frontend
   - HTML/CSS/JavaScript frontend (mobile-responsive) or lightweight framework

3. **Build web interface features**:
    - Image upload
    - Tag management (add/remove tags per image)
    - Matte/filter selection per image
    - TV management (add/remove IPs, test connection, name?)
    - Image gallery /selection with thumbnails and infinite scroll
    - Image delete
    - Git LFS sync management (auto/manual?)

4. **Add API endpoints**:
    - `/api/images` - CRUD for metadata
    - `/api/tvs` - CRUD for TV list
    - `/api/tags` - Manage tag library
    - `/api/sync` - Trigger Git LFS operations
    - `/api/upload` - Handle image uploads
    - `/api/display` - Call AppDaemon service to display image on TV (via HA REST API)
    - `/api/shuffle` - Start/stop shuffle via AppDaemon services
    - Might need `metadata_helper.py` module with functions:
      * `read_metadata()` - Load metadata.json
      * `write_metadata(data)` - Save metadata.json
      * `add_image(filename, matte, filter, tags)` - Add new image entry
      * `update_image(filename, **kwargs)` - Update existing image metadata
      * `get_images_by_tag(tag)` - Query images by tag
      * `get_all_images()` - Return all image metadata
      * `generate_thumbnail(image_path, thumb_size=(400, 300))` - Create thumbnail for an image, save to `thumbs/`
      * `verify_sync()` - Check consistency between actual files in `library/` and `thumbs/` vs metadata.json entries, report:
        - Images in metadata but missing files
        - Files present but not in metadata
        - Thumbnails missing for images
        - Orphaned thumbnails without corresponding images

5. **Package for HACS**:
    - Create `info.md`, `README.md`, `config.json`
    - Set up GitHub releases
    - Submit to HACS default repository

### Phase 3: Core Python Scripts (AppDaemon app)
6. **Query TV for available mattes and filters**:
   - Run `list_mattes_filters.py` to get actual available options from your Frame TV
   - Update `www/frame_art/metadata.json` with the real values:
     * Populate `matte_types[]` array with available styles (shadowbox, modern, flexible, etc.)
     * Populate `matte_colors[]` array with available colors (polar, apricot, charcoal, etc.)
     * Populate `filters[]` array with available filter IDs (none, ink, grayscale, etc.)
   - Commit updated metadata.json to frame_art repository
   - Note: Matte format is `{type}_{color}` (e.g., `shadowbox_polar`, `modern_apricot`)

7. **Create AppDaemon app** (`apps/frame_art/frame_art_controller.py`):
   - AppDaemon app that wraps Frame TV control functionality
   - Install `samsungtvws` in AppDaemon's Python environment
   - Core functions:
     * `upload_display_delete(image_path, tv_ip, matte, filter)` - Upload, display, and clean TV
     * `display_image(tv_ip, content_id)` - Show existing image on TV
     * `get_tv_status(tv_ip)` - Return current TV state and displayed image
     * `start_shuffle(tv_ip, tags, frequency)` - Begin rotation based on tags
     * `stop_shuffle(tv_ip)` - Stop rotation
   - Based on proven timing patterns from `upload_to_frame.py`:
     * 6s wait after upload
     * 8s wait after select_image
     * Wake-up call before verification
     * Batch delete of other images after successful verification
   - Expose as HA services:
     * `appdaemon.frame_art_display`
     * `appdaemon.frame_art_shuffle_start`
     * `appdaemon.frame_art_shuffle_stop`
   - Built-in logging via AppDaemon
   - Maintain shuffle state and timers per TV

### Phase 4: Home Assistant Dashboard & Automations
8. **Build HA dashboard** (`dashboards/frame-art-dashboard.yaml`):
   - Embed add-on web interface in iframe
   - Card to show current image on each TV
   - Shuffle controls (on/off, frequency, tags)
   - TV status display

8. **Create HA automations** (`automations.yaml`):
   - Image rotation automation (trigger: time_pattern based on frequency)
   - Tag-filtered shuffle logic (calls AppDaemon services)
   - Sync library on HA restart (calls add-on API)
   - Can also be managed directly by AppDaemon app's internal timers

### Phase 5: Testing & Polish
9. **Test workflow**:
    - Upload via web interface → verify in Git LFS
    - Tag images → verify metadata.json updated
    - Dashboard display → verify correct image shown
    - Shuffle automation → verify rotation works
    - Multi-TV support → verify independent control

10. **Documentation**:
    - Update installation guide
    - Document metadata schema
    - Add troubleshooting section
    - Create example automations

### Key Dependencies
- **AppDaemon**: For Frame TV control app
- **Python** (in AppDaemon): `samsungtvws`, `Pillow` (thumbnails), `GitPython` (Git LFS ops if needed)
- **Node.js** (in add-on container): Express, Multer (file uploads)
- **Frontend**: Vanilla JS or lightweight framework (Alpine.js, htmx)
- Git LFS installed on HA system

**Tech Stack Rationale:**
- Node/Express add-on handles web UI, API endpoints, file management, metadata JSON operations
- AppDaemon app handles Frame TV communication with proper logging and service exposure
- Add-on calls AppDaemon services via HA REST API when TV control is needed
- AppDaemon manages shuffle timers and rotation logic internally
- Clean separation: Add-on = UI/metadata, AppDaemon = TV control/automation

**Estimated Timeline**: 2-3 weeks for core functionality (Phases 1-3), additional 2 weeks for polished web interface (Phase 4)
