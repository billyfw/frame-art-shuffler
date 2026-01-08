# Tag Weights Feature

**Status: IMPLEMENTED**

## Overview

Tag weights allow users to control the relative frequency of image categories during shuffle. Instead of equal probability across all include tags, users can specify that certain tags should be selected more or less frequently.

**Example**: A tagset with `zebra` (weight 4), `lion` (weight 2), `monkey` (weight 1) will show:
- Zebra category: 57% of the time (4/7)
- Lion category: 29% of the time (2/7)  
- Monkey category: 14% of the time (1/7)

This is **category weighting** (Option A), not per-image weighting. Having 10,000 zebra images vs 2 lion images doesn't affect the category percentages — weights control how often each *category* is chosen, then a random image is selected from that category.

---

## Algorithm

### Weighted Shuffle Selection

```
1. Get include tags and their weights from active tagset
2. For each tag, build pool of eligible images (not excluded, file exists)
3. Assign multi-tag images to highest-weight tag only (ties: first in tagset order)
4. Calculate total weight (sum of weights for tags with ≥1 image)
5. Roll weighted random to select a tag
   - If selected tag has 0 images: log warning, remove from candidates, re-roll
   - Repeat until a tag with images is selected (or no tags remain)
6. Select random image from the chosen tag's pool
7. Return selected image
```

### Multi-Tag Image Assignment

When an image has multiple tags that are all in the tagset's include list:
- Assign to the tag with the **highest weight**
- If weights are equal, assign to the **first matching tag** (based on tagset's tag order)
- Image appears in only ONE pool — prevents over-representation of multi-tagged images

**Example**:
- Tagset include tags: `["zebra", "lion", "monkey"]` with weights `{zebra: 4, lion: 2, monkey: 1}`
- Image tagged: `["lion", "monkey"]`
- Result: Image goes in `lion` pool only (weight 2 > weight 1)

### Empty Tag Handling

If a tag is rolled but has 0 eligible images:
1. Log: "Tag 'zebra' rolled but has 0 eligible images, re-rolling"
2. Remove that tag from candidates for this shuffle
3. Recalculate weights and re-roll
4. If all tags exhausted: return no selection (existing behavior)

### Recency Preference Interaction

During auto-shuffle, recency preference is applied *after* tag selection:

1. Weighted random selects a tag (e.g., "zebra" at 57%)
2. Build candidate images from that tag's pool
3. Filter out images shown in last 72 hours → "fresh" pool
4. If fresh images exist, select from fresh pool; otherwise fallback to full pool

This preserves tag weight proportions while still preferring fresh images. The recency filter only affects which *image* is chosen from the selected tag, not which tag is selected.

---

## Data Model

### Config Entry Structure

```python
"tagsets": {
    "animals": {
        "tags": ["zebra", "lion", "monkey"],
        "exclude_tags": ["blurry"],
        "tag_weights": {          # NEW - optional
            "zebra": 4,
            "lion": 2,
            "monkey": 1
        }
    },
    "landscapes": {
        "tags": ["beach", "mountain", "forest"],
        "exclude_tags": []
        # tag_weights omitted = all weights default to 1
    }
}
```

### Weight Rules

- **Range**: 0.1 to 10 (inclusive)
- **Default**: 1 (if `tag_weights` missing or tag not in dict)
- **Type**: Float (0.1, 0.5, 1, 2, 10, etc.)
- **Display format**: 
  - Decimals: "0.5", "0.1"
  - Integers: "1", "4", "10" (no decimal point)

### Percentage Calculation

```python
def calculate_tag_percentages(tags: list[str], weights: dict[str, float]) -> dict[str, int]:
    """Calculate display percentages for each tag.
    
    Returns dict of tag -> percentage (integer, rounded).
    """
    total = sum(weights.get(tag, 1) for tag in tags)
    if total == 0:
        return {tag: 0 for tag in tags}
    
    percentages = {}
    for tag in tags:
        weight = weights.get(tag, 1)
        percentages[tag] = round((weight / total) * 100)
    return percentages
```

---

## Integration Changes

### 1. Shuffle Algorithm (`shuffle.py`)

Modify `_select_random_image()` to implement weighted tag selection:

```python
def _select_random_image(
    metadata_path: Path,
    include_tags: list[str],
    exclude_tags: list[str],
    tag_weights: dict[str, float],  # NEW parameter
    current_image: str | None,
    tv_name: str,
) -> tuple[dict[str, Any] | None, int, str | None]:  # NEW: returns selected tag name
    """Select a random eligible image using weighted tag selection."""
    
    # 1. Load metadata and filter by exclude tags
    # 2. Build per-tag image pools (multi-tag images → highest weight tag)
    # 3. Weighted random tag selection with re-roll on empty
    # 4. Random image from selected tag
    # 5. Return (image, eligible_count, selected_tag_name)
```

### 2. Config Entry Helpers (`config_entry.py`)

Add function to get tag weights:

```python
def get_tag_weights(entry: ConfigEntry, tv_id: str) -> dict[str, float]:
    """Get tag weights for the active tagset.
    
    Returns dict of tag -> weight. Missing tags default to 1.
    """
    tagsets = entry.data.get("tagsets", {})
    tv_config = get_tv_config(entry, tv_id)
    if not tv_config:
        return {}
    
    active_name = tv_config.get("override_tagset") or tv_config.get("selected_tagset")
    if not active_name or active_name not in tagsets:
        active_name = next(iter(tagsets), None)
    
    if not active_name:
        return {}
    
    return tagsets[active_name].get("tag_weights", {})
```

### 3. Services (`services.py`)

Update `upsert_tagset` service schema:

```python
UPSERT_TAGSET_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Required("tags"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("exclude_tags", default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("tag_weights", default={}): {cv.string: vol.Coerce(float)},  # NEW
})
```

Validation in service handler:
```python
# Validate weights are in range 0.1-10
for tag, weight in tag_weights.items():
    if not (0.1 <= weight <= 10):
        raise vol.Invalid(f"Weight for '{tag}' must be between 0.1 and 10")
    if tag not in tags:
        _LOGGER.warning(f"Weight specified for tag '{tag}' not in include tags, ignoring")
```

### 4. Sensors

#### `sensor.<tv>_tags_combined`

Update to show weights when any weight ≠ 1:

**Current**: `[+] zebra, lion, monkey / [-] blurry`

**New (with weights)**: `[+] zebra(57%), lion(29%), monkey(14%) / [-] blurry`

**New (all weights = 1)**: `[+] zebra, lion, monkey / [-] blurry` (unchanged)

#### `sensor.<tv>_current_artwork` attributes

Add to extra state attributes:
```python
"tagset_weights": {"zebra": 4, "lion": 2, "monkey": 1},
"tagset_percentages": {"zebra": 57, "lion": 29, "monkey": 14},
```

### 5. Activity Logging

When shuffle completes, log the selected tag and recency info (auto-shuffle only):

**Manual shuffle**: `Shuffled to z15.jpg (tag: zebra, from 50 in tag)`

**Auto-shuffle (fresh images available)**: `Shuffled to z15.jpg (tag: zebra, from 12 fresh of 50 in tag)`

**Auto-shuffle (all recent)**: `Shuffled to z15.jpg (tag: zebra, all 50 in tag were recent)`

When tag rolled but empty:

`Tag 'extinct_animals' rolled but has 0 images, re-rolling`

---

## Add-on Changes

### 1. Edit Tagset Modal — New Tabs

Add tab navigation to the Edit Tagset modal:
- **Tab: "Tags"** — Existing include/exclude tag UI
- **Tab: "Weights"** — New weight slider UI

### 2. Weights Tab UI

```
┌─────────────────────────────────────────────────────────────────┐
│  WEIGHTS                                                        │
│                                                                 │
│  Adjust how often each tag category is selected during shuffle. │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  zebra                                                    │  │
│  │  4                                                        │  │
│  │  ○────────────────────────●━━━━━━━━━━━━━━━━━○            57% │
│  │  0.1                      1                 10            │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  lion                                                     │  │
│  │  2                                                        │  │
│  │  ○────────────────────────●━━━━━━━○                      29% │
│  │  0.1                      1       10                      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  monkey                                                   │  │
│  │  1                                                        │  │
│  │  ○────────────────────────●───────────────────○          14% │
│  │  0.1                      1                   10          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  [Reset All Weights]                                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Slider Specification

- **20 discrete positions**:
  - Left 10 positions: 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0
  - Right 10 positions: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
  - Note: "1" is shared (center position)
- **Default position**: Center (value = 1)
- **Display above slider**: Current value ("0.5" or "4")
- **Display right of slider**: Calculated percentage ("57%")

### 4. Tags Tab — Weight Indicators

When any tag has weight ≠ 1, show percentage in tag bubbles:

**All weights = 1**:
```
[zebra (50)] [lion (12)] [monkey (8)]
```

**Weights configured**:
```
[zebra 57% (50)] [lion 29% (12)] [monkey 14% (8)]
```

### 5. Reset Weights Button

- **Location**: Bottom of Weights tab
- **Action**: Confirmation dialog → Set all weights to 1
- **Dialog text**: "Reset all tag weights to 1? This will give all tags equal selection probability."

### 6. API Endpoints

Update `/api/ha/tagsets/upsert` to accept `tag_weights`:

```javascript
// Request
POST /api/ha/tagsets/upsert
{
  "name": "animals",
  "tags": ["zebra", "lion", "monkey"],
  "exclude_tags": ["blurry"],
  "tag_weights": {"zebra": 4, "lion": 2, "monkey": 1}
}

// Calls integration service
frame_art_shuffler.upsert_tagset with tag_weights parameter
```

---

## Migration / Backward Compatibility

### Existing Tagsets

- No migration needed
- Missing `tag_weights` key = all weights default to 1
- Behavior identical to current (equal probability per tag)

### Validation

On load, the integration should handle:
- `tag_weights` missing entirely → default all to 1
- `tag_weights` empty dict → default all to 1  
- Tag in `tags` but not in `tag_weights` → default that tag to 1
- Tag in `tag_weights` but not in `tags` → ignore (log warning)
- Weight out of range → clamp to 0.1-10 (log warning)

---

## Testing Checklist

### Integration Tests
- [ ] Weighted selection respects configured weights (statistical test)
- [ ] Multi-tag images assigned to highest-weight tag
- [ ] Multi-tag tie-breaking uses tagset order
- [ ] Empty tag triggers re-roll
- [ ] All tags empty returns no selection
- [ ] Missing tag_weights defaults to equal weights
- [ ] Out-of-range weights are clamped
- [ ] Activity log includes selected tag name

### Add-on Tests
- [ ] Weights tab renders all include tags
- [ ] Slider positions map to correct values
- [ ] Percentage calculation updates live
- [ ] Reset button confirms and resets all to 1
- [ ] Tags tab shows percentages when weights ≠ 1
- [ ] Tags tab hides percentages when all weights = 1
- [ ] API calls include tag_weights in upsert

---

## Implementation Order

1. **Integration**: Data model & config_entry helpers
2. **Integration**: Shuffle algorithm changes
3. **Integration**: Service schema update
4. **Integration**: Sensor updates
5. **Integration**: Activity logging
6. **Add-on**: API endpoint update
7. **Add-on**: Edit Tagset modal tabs
8. **Add-on**: Weights tab UI
9. **Add-on**: Tags tab percentage display
10. **Testing**: End-to-end verification
