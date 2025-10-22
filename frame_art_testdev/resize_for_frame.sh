#!/bin/bash
#
# Resize images for Samsung Frame TV
# Optimizes to 3840x2160 at 75% JPEG quality (~3-5MB)
#
# Usage: ./resize_for_frame.sh input.jpg [output.jpg]
#

if [ $# -eq 0 ]; then
    echo "Usage: $0 input.jpg [output.jpg]"
    echo ""
    echo "Resizes image for Samsung Frame TV:"
    echo "  - Resolution: 3840x2160 (4K)"
    echo "  - Quality: 75% JPEG"
    echo "  - Target size: 3-5MB"
    echo ""
    echo "Examples:"
    echo "  $0 large_photo.jpg                    # Creates large_photo_resized.jpg"
    echo "  $0 large_photo.jpg frame_ready.jpg    # Creates frame_ready.jpg"
    exit 1
fi

INPUT="$1"
OUTPUT="${2:-${INPUT%.*}_resized.jpg}"

if [ ! -f "$INPUT" ]; then
    echo "Error: Input file not found: $INPUT"
    exit 1
fi

# Get original file size
ORIGINAL_SIZE=$(du -h "$INPUT" | cut -f1)

echo "🖼️  Resizing image for Samsung Frame TV"
echo "   Input:  $INPUT ($ORIGINAL_SIZE)"
echo "   Output: $OUTPUT"
echo ""

# Check if sips is available (macOS)
if command -v sips &> /dev/null; then
    echo "Using sips (macOS)..."
    sips --resampleWidth 3840 \
         --resampleHeight 2160 \
         --setProperty format jpeg \
         --setProperty formatOptions 75 \
         "$INPUT" --out "$OUTPUT" 2>&1 | grep -v "^/"
    
elif command -v convert &> /dev/null; then
    echo "Using ImageMagick..."
    convert "$INPUT" \
            -resize 3840x2160 \
            -quality 75 \
            "$OUTPUT"
    
else
    echo "Error: Neither sips (macOS) nor ImageMagick (convert) found"
    echo ""
    echo "Install ImageMagick:"
    echo "  macOS: brew install imagemagick"
    echo "  Linux: apt-get install imagemagick"
    exit 1
fi

if [ $? -eq 0 ]; then
    NEW_SIZE=$(du -h "$OUTPUT" | cut -f1)
    echo ""
    echo "✓ Success!"
    echo "  Original: $ORIGINAL_SIZE"
    echo "  Resized:  $NEW_SIZE"
    echo ""
    echo "Ready to upload:"
    echo "  python3 upload_to_frame.py \"$OUTPUT\""
else
    echo "✗ Resize failed"
    exit 1
fi
