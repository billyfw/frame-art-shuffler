# Samsung Frame TV Matte Behavior

**Last Updated:** December 27, 2025  
**Tested On:** Samsung Frame TV at 192.168.1.249

## Overview

The Samsung Frame TV API has significant bugs and limitations when applying mattes to uploaded images. This document details the workarounds discovered through extensive testing.

## The Error 40000 Problem

When uploading images with a matte specified in the `upload()` call, the upload appears to succeed, but **selecting/displaying the image causes "Unexpected Error 40000"** on the TV screen. This is a known Samsung firmware bug ([GitHub Issue #133](https://github.com/xchwarze/samsung-tv-ws-api/issues/133)).

### What Doesn't Work

```python
# ❌ FAILS - Causes Error 40000 when image is displayed
content_id = art.upload(data, matte='shadowbox_polar', file_type='jpg')
art.select_image(content_id)  # TV shows Error 40000
```

## The Working Workaround

**Upload with a placeholder matte, then use `change_matte()` to set the desired matte.**

```python
# ✅ WORKS - No error on display
content_id = art.upload(data, matte='flexible_warm', file_type='jpg')
art.change_matte(content_id, 'shadowbox_polar')
art.select_image(content_id)  # Displays correctly with matte!
```

### Why This Works

1. Uploading with `matte='flexible_warm'` "enables" matte support for the image
2. `change_matte()` properly applies the matte without triggering the firmware bug
3. The image displays correctly with the matte

## Portrait vs Landscape Images

### Summary

| Image Type | Working Matte Types | Total Options |
|------------|---------------------|---------------|
| **Landscape** | ALL 10 types + `none` | 145+ combinations |
| **Portrait** | `shadowbox` and `flexible` only | 32 combinations |

### Landscape Images (width > height)

**All matte types work for landscape images!**

| Matte Type | Status | Notes |
|------------|--------|-------|
| `none` | ✅ Works | Can remove matte |
| `modernthin` | ✅ Works | All 16 colors |
| `modern` | ✅ Works | All 16 colors |
| `modernwide` | ✅ Works | All 16 colors |
| `flexible` | ✅ Works | All 16 colors |
| `shadowbox` | ✅ Works | All 16 colors |
| `panoramic` | ✅ Works | All 16 colors |
| `triptych` | ✅ Works | All 16 colors |
| `mix` | ✅ Works | All 16 colors |
| `squares` | ✅ Works | All 16 colors |

### Portrait Images (height > width)

For portrait images, only certain matte types work with `change_matte()`:

| Matte Type | Status | Notes |
|------------|--------|-------|
| `shadowbox` | ✅ Works | All 16 colors work |
| `flexible` | ✅ Works | All 16 colors work |
| `modern` | ❌ Error -7 | Cannot be applied via change_matte |
| `modernthin` | ❌ Error -7 | Cannot be applied via change_matte |
| `modernwide` | ❌ Error -7 | Cannot be applied via change_matte |
| `panoramic` | ❌ Error -7 | Designed for wide images |
| `triptych` | ❌ Error -7 | Designed for wide images |
| `mix` | ❌ Error -7 | |
| `squares` | ❌ Error -7 | |
| `none` | ❌ Error -7 | Cannot remove matte once set |

## Available Matte Colors (All 16)

All colors work with all supported matte types:

| Color | API Value |
|-------|-----------|
| Black | `black` |
| Neutral | `neutral` |
| Antique | `antique` |
| Warm | `warm` |
| Polar | `polar` |
| Sand | `sand` |
| Seafoam | `seafoam` |
| Sage | `sage` |
| Burgundy | `burgandy` (Samsung's spelling!) |
| Navy | `navy` |
| Apricot | `apricot` |
| Byzantine | `byzantine` |
| Lavender | `lavender` |
| Red Orange | `redorange` |
| Sky Blue | `skyblue` |
| Turquoise | `turquoise` |

## Complete Working Combinations for Portrait Images

**32 total working mattes:**

### Shadowbox (16 colors)
- `shadowbox_black`
- `shadowbox_neutral`
- `shadowbox_antique`
- `shadowbox_warm`
- `shadowbox_polar`
- `shadowbox_sand`
- `shadowbox_seafoam`
- `shadowbox_sage`
- `shadowbox_burgandy`
- `shadowbox_navy`
- `shadowbox_apricot`
- `shadowbox_byzantine`
- `shadowbox_lavender`
- `shadowbox_redorange`
- `shadowbox_skyblue`
- `shadowbox_turquoise`

### Flexible (16 colors)
- `flexible_black`
- `flexible_neutral`
- `flexible_antique`
- `flexible_warm`
- `flexible_polar`
- `flexible_sand`
- `flexible_seafoam`
- `flexible_sage`
- `flexible_burgandy`
- `flexible_navy`
- `flexible_apricot`
- `flexible_byzantine`
- `flexible_lavender`
- `flexible_redorange`
- `flexible_skyblue`
- `flexible_turquoise`

## Complete Working Combinations for Landscape Images

**145+ total working mattes (all types × all colors + none):**

All 10 matte types work with all 16 colors:
- `modernthin` (16 colors)
- `modern` (16 colors)
- `modernwide` (16 colors)
- `flexible` (16 colors)
- `shadowbox` (16 colors)
- `panoramic` (16 colors)
- `triptych` (16 colors)
- `mix` (16 colors)
- `squares` (16 colors)
- `none` (removes matte)

## API Details

### Upload Parameters

```python
art.upload(
    data,                    # Image bytes
    matte='flexible_warm',   # Placeholder matte (enables matte support)
    portrait_matte=None,     # Optional - for portrait-specific matte
    file_type='jpg'          # 'jpg' or 'png'
)
```

### Change Matte Parameters

```python
art.change_matte(
    content_id,              # e.g., 'MY_F0831'
    matte_id,                # e.g., 'shadowbox_polar'
    portrait_matte=None      # Optional
)
```

### How the TV Stores Mattes

For portrait images, the TV stores the matte in the `portrait_matte_id` field:

```python
images = art.available()
# Returns: {'content_id': 'MY_F0831', 'matte_id': 'flexible_warm', 'portrait_matte_id': 'shadowbox_polar', ...}
```

## Error Codes Reference

| Error Code | Meaning | Cause |
|------------|---------|-------|
| 40000 | Unexpected Error | Displayed when selecting image uploaded with matte directly |
| -7 | Operation Failed | `change_matte()` called with incompatible matte type for image orientation |
| -1 | Upload Failed | Various upload issues |

## Implementation Recommendations

### For frame-art-shuffler (frame_tv.py)

The workaround has been implemented in `set_art_on_tv_deleteothers()`:

```python
# In _upload_chunked call section:
if matte and matte != "none":
    # Upload with placeholder, then change_matte after
    content_id = _upload_chunked(art, payload, file_type, matte=_MATTE_PLACEHOLDER, portrait_matte=_MATTE_PLACEHOLDER)
    art.change_matte(content_id, matte)
else:
    # No matte requested - upload normally
    content_id = _upload_chunked(art, payload, file_type, matte="none", portrait_matte="none")
```

The constant `_MATTE_PLACEHOLDER = "flexible_warm"` is defined at module level.

### For ha-frame-art-manager

1. **Filter matte options based on image orientation**:
   - Portrait images: Only show `none`, `shadowbox_*`, and `flexible_*` options
   - Landscape images: Show all matte options
2. **Detect orientation from image dimensions** when file is selected
3. **Reset matte to 'none'** if user had selected an invalid matte for the new orientation

### Code Example (frame_tv.py implementation)

```python
from PIL import Image
import io

def upload_with_matte(art, image_data, desired_matte, file_type='jpg'):
    """Upload image with matte using the workaround."""
    
    # Detect orientation
    img = Image.open(io.BytesIO(image_data))
    is_portrait = img.height > img.width
    
    # Upload with placeholder matte
    content_id = art.upload(image_data, matte='flexible_warm', file_type=file_type)
    
    # Apply desired matte
    if desired_matte and desired_matte != 'none':
        # For portrait, only shadowbox and flexible work
        if is_portrait:
            matte_type = desired_matte.split('_')[0]
            if matte_type not in ['shadowbox', 'flexible']:
                raise ValueError(f"Matte type '{matte_type}' not supported for portrait images")
        
        art.change_matte(content_id, desired_matte)
    
    return content_id
```

## Testing History

### Test 1: Direct Upload with Matte
- **Action:** `art.upload(data, matte='modern_warm')`
- **Result:** Upload succeeds, but `select_image()` causes Error 40000

### Test 2: Upload with portrait_matte Parameter
- **Action:** `art.upload(data, matte='none', portrait_matte='modern_warm')`
- **Result:** Image displays with NO matte (parameter ignored?)

### Test 3: Upload + change_matte Workaround
- **Action:** Upload with `matte='flexible_warm'`, then `change_matte('shadowbox_polar')`
- **Result:** ✅ SUCCESS! Image displays with matte, no errors

### Test 4: Testing All Mattes via change_matte (Portrait Image)
- **Working:** All 32 shadowbox and flexible combinations
- **Failing:** All modern, modernthin, modernwide combinations (Error -7)
- **Failing:** `none` - cannot remove matte once applied

## Known Limitations

1. **Cannot remove matte** - Once an image is uploaded with a matte, calling `change_matte(content_id, 'none')` fails with Error -7
2. **Portrait images limited** - Only shadowbox and flexible matte types work on portrait images
3. **Upload matte causes error** - Direct upload with matte causes Error 40000 on display

## Related Issues

- [GitHub Issue #133](https://github.com/xchwarze/samsung-tv-ws-api/issues/133) - "Anyone know which matte style/color options work for uploaded images?"
- [GitHub Issue #107](https://github.com/xchwarze/samsung-tv-ws-api/issues/107) - "Is it possible to change matte options on art already on TV?"
- [GitHub PR #109](https://github.com/xchwarze/samsung-tv-ws-api/pull/109) - "Added support for listing/changing art mode mats"
