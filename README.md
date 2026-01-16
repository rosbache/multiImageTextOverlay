# Image Metadata Overlay

A Python tool that reads JPG images, extracts EXIF metadata (date, time, GPS location), and creates copies with configurable text overlays displaying this information.

## Features

- 📸 Extracts EXIF metadata from JPG images
- 🕒 Displays date and time from image metadata
- 📍 Shows GPS location in human-readable format (e.g., 40°42'46"N, 74°0'21"W)
- 🎨 Customizable text appearance (color, size, position)
- ✨ Text outline for better visibility
- 🔄 Batch processing of multiple images

## Project Structure

```
mc_image_overlay/
├── main.py              # Entry point - run this to process images
├── image_processor.py   # Core image processing and overlay logic
├── exif_handler.py      # EXIF metadata extraction utilities
├── config.py            # User-configurable settings
├── requirements.txt     # Python dependencies
├── input/               # Place your JPG images here
├── output/              # Processed images will be saved here
└── fonts/               # TrueType font files
    └── arial.ttf        # Default font (you need to add this)
```

## Installation

1. **Clone or download this project**

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Add a TrueType font file:**
   - Download a font file (e.g., Arial, Roboto, etc.) in `.ttf` format
   - Place it in the `fonts/` directory
   - Update `FONT_PATH` in `config.py` to match your font filename

## Usage

1. **Add JPG images to the `input/` folder**

2. **Configure settings in `config.py` (optional):**
   ```python
   TEXT_COLOR = (255, 255, 255)     # RGB - White
   FONT_SIZE = 24                    # Font size
   TEXT_POSITION = 'bottom-left'     # Text position
   ```

3. **Run the script:**
   ```bash
   python main.py
   ```

4. **Find processed images in the `output/` folder**

## Configuration Options

Edit `config.py` to customize the overlay appearance:

### Text Appearance
- `TEXT_COLOR`: RGB tuple for text color (default: white)
- `OUTLINE_COLOR`: RGB tuple for outline color (default: black)
- `OUTLINE_WIDTH`: Outline thickness in pixels (default: 2)

### Font Settings
- `FONT_SIZE`: Font size in points (default: 24)
- `FONT_PATH`: Path to TrueType font file (default: "fonts/arial.ttf")

### Text Positioning
- `TEXT_POSITION`: Corner placement - `'top-left'`, `'top-right'`, `'bottom-left'`, `'bottom-right'`
- `PADDING`: Distance from image edge in pixels (default: 20)

### Output Settings
- `OUTPUT_QUALITY`: JPEG quality 1-100 (default: 95)

## Example Output

The overlay will display metadata like:
```
Date: 2024-08-15 14:30:22
Location: 40°42'46"N, 74°0'21"W
```

If an image has no metadata, it will display: "No metadata available"

## Dependencies

- **Pillow (PIL)**: Image processing and text rendering
- **piexif**: EXIF metadata extraction

## Notes

- Only JPG/JPEG images are currently supported
- Images without EXIF data will still be processed but show "No metadata available"
- GPS coordinates are displayed in degrees, minutes, seconds format
- Original images in the `input/` folder are not modified

## License

This project is open source and available for personal and commercial use.
