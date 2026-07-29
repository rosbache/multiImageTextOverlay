# Image Metadata Overlay

A Python tool for processing JPG images with EXIF-driven text overlays. It supports CLI and FastAPI-based web workflows for metadata overlays, coordinate conversion, address lookup, and GPS correction, and it can also calculate chainage from a SOSI reference line in the web UI.

## Features

- Extracts EXIF metadata from JPG images
- Displays date and time from image metadata
- Shows GPS location in human-readable format (for example, `40°42'46"N, 74°0'21"W`)
- Corrects wrong GPS locations before processing, either on the map or through a JSON override file
- Converts GPS coordinates to UTM or other projected coordinate systems
- Displays image direction in degrees with cardinal directions
- Optionally looks up the nearest street address from GPS coordinates
- Calculates chainage from a SOSI `KURVE` reference line, with optional left/right offset text
- Adds optional project information at the top of every image
- Supports customizable text appearance, padding, and outline styling
- Provides live preview, map view, and selective processing in the web UI
- Processes images in parallel with configurable worker count
- Preserves EXIF metadata in output files
- Handles output collisions with overwrite, skip, or rename modes
- Includes progress reporting, logging, and dry-run support

## Example Output

The overlay will display metadata like:
```
Project XYZ - Survey 2024

image001
Date: 2024-08-15 14:30:22
Location: 40°42'46"N, 74°0'21"W
UTM 32N: 123456.78E, 987654.32N
Address: Exampleveien 12, 3530 Røyse
Height: 125.3 m
Direction: 45° (NE)
Chainage: kp 1+234
```
<img width="344" height="60" alt="image" src="https://github.com/user-attachments/assets/24aea6f3-dd10-42ec-88d3-94d6bc6ec492" />


If an image has no metadata, it will display: "No metadata available"

<img width="182" height="22" alt="image" src="https://github.com/user-attachments/assets/35d27b54-1ed4-4f12-9df2-aa91b9ada588" />

## Project Structure

```
multiImageTextOverlay/
├── main.py              # CLI entry point
├── web_app.py           # FastAPI web UI entry point
├── image_processor.py   # Core image processing and overlay rendering
├── exif_handler.py      # EXIF extraction, GPS utilities, and reverse geocoding
├── chainage_calculator.py # SOSI reference line loading and chainage calculations
├── sosi_parser.py       # General SOSI parsing utilities
├── sosi_koordsys.jsonc  # SOSI coordinate-system lookup data
├── config.py            # User-configurable defaults with validation
├── launcher.py          # Desktop launcher entry point
├── start_web.bat        # Windows helper for starting the web app
├── requirements.txt     # Python dependencies
├── templates/
│   └── index.html       # Web UI (single-page, no build step required)
├── input/               # Place your JPG images here (configurable)
├── output/              # Processed images will be saved here (configurable)
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

4. **Start the web UI:**
   ```bash
   uvicorn web_app:app --host 127.0.0.1 --port 8000
   ```
   Then open **http://localhost:8000** in your browser.

   On Windows you can also double-click **`start_web.bat`** — it activates the virtual environment and starts the server automatically.

   > To stop the server press **Ctrl + C** in the terminal.

## Usage

### Web UI (recommended)

Start the local web server:
```bash
uvicorn web_app:app --host 127.0.0.1 --port 8000
```
Or on Windows, double-click `start_web.bat`.

Then open **http://localhost:8000** in your browser.

The web interface has three panels and two main views:

| Panel | Description |
|---|---|
| **Left** | All overlay settings grouped in collapsible sections |
| **Center** | Preview tab: Live preview for the selected image<br>Map tab: Interactive map showing image locations and optional reference line geometry |
| **Right** | Scrollable list of loaded images; click to select and optionally multi-select for partial processing |

**Loading images:**
- **Folder tab** — type (or paste) a folder path and click *Load*. The server scans the folder and begins looking up addresses in the background.
- **Upload tab** — drag-and-drop JPG files onto the drop zone, or click to browse. Files are copied to a temporary folder on the server.

**Processing:**  
Click *Process All* to batch-process every loaded image, or *Process Selected* to process only the currently selected subset. A progress bar and live status message update as each file completes. Output is written to the *Output folder* field (defaults to `<input folder>/processed` if left blank).

**Correcting GPS Locations:**

Some images may have incorrect GPS coordinates (wrong location metadata). The map-based editor lets you visually correct these before processing:

1. **View locations**: Click the *Map* tab in the center panel to see all images with GPS data plotted on an OpenStreetMap
2. **Select image**: Click any marker on the map (or select from the image list) to highlight an image
3. **Edit location**: 
   - Drag the marker to the correct position, or
   - Click on the map where the image should be located
4. **Staged edits**: Location changes are *staged* (not immediately written to source files). Edited images show warning styling in the map and image list.
5. **Apply changes**: When you click *Process All* or *Process Selected*, staged edits are written to the source EXIF data *before* processing, then geocoding is refreshed for the new coordinates.
6. **Reset**: Use *Reset Location* to undo edits for the selected image, or *Reset All* to clear all staged edits.

> **Important**: Location edits modify the source image EXIF data when you process. This is intentional — it ensures the corrected location is permanently saved and will be used if you process the images again. Original files are modified only when you click Process.

**Reference Lines and Chainage:**

The web UI can also calculate chainage from a SOSI reference line:

1. Load a `.sos` or `.sosi` file by path or upload it in the *Line / Chainage* section
2. Select the `KURVE` object to use as the active reference line
3. Choose whether to reverse the line direction and set marker spacing / chainage start offset
4. Enable *Show chainage on overlay* to add formatted stationing text to previews and processed output
5. Optionally include left/right offset from the line for each image location

When a line is active, the map can display the reference geometry and chainage tick markers, and image popups are updated with computed chainage values.

### Command-Line GPS Overrides

You can also correct GPS locations via the CLI using a JSON override file:

```bash
# Process with default settings
python main.py

# Specify custom input/output directories
python main.py --input photos --output processed

# Customize text appearance
python main.py --position top-right --color 255 0 0 --font-size 72

# Control processing
python main.py --workers 4 --collision skip

# Disable reverse geocoding
python main.py --no-address

# Add project information
python main.py --project-info "Highway Survey 2026 - Phase 1"

# Apply corrected GPS coordinates before processing
python main.py --overrides overrides.json

# Use 16-sector compass for more precise directions
python main.py --direction-precision 16

# Disable direction display
python main.py --no-direction

# Enable verbose logging
python main.py --verbose

# Save logs to file
python main.py --log-file process.log

# Preview without processing
python main.py --dry-run

# Combine options
python main.py -i photos -o processed -p top-right -c 255 255 0 -s 60 --project-info "Survey 2026" -v
```

### Available Options

```
-h, --help                    Show help message and exit
-i, --input DIR               Input directory containing images (default: input)
-o, --output DIR              Output directory for processed images (default: output)
-p, --position POS            Text position: top-left, top-right, bottom-left, bottom-right
-c, --color R G B             Text color as RGB values 0-255
-s, --font-size SIZE          Font size in points
-q, --quality QUALITY         Output JPEG quality 1-100
--target-epsg EPSG            Target EPSG code for coordinate transformation
--no-utm                      Disable UTM coordinate display
--show-direction              Enable image direction display
--no-direction                Disable image direction display
--no-address                  Disable nearest address lookup from GPS coordinates
--direction-precision {8,16}  Cardinal direction precision (8 or 16 sectors)
--project-info TEXT           Project information text displayed at top
--overrides FILE              JSON file with GPS location overrides
-w, --workers N               Maximum number of parallel workers
--collision MODE              File collision handling: overwrite, skip, rename
--dry-run                     Preview files without processing
-v, --verbose                 Enable debug logging
--quiet                       Suppress console output except errors
--log-file FILE               Save logs to specified file
```

## Configuration Options

Edit `config.py` to customize default settings:

### Directory Settings
- `INPUT_DIR`: Default input directory (default: "input")
- `OUTPUT_DIR`: Default output directory (default: "output")

### Text Appearance
- `TEXT_COLOR`: RGB tuple for text color (default: (255, 255, 255) - white)
- `OUTLINE_COLOR`: RGB tuple for outline color (default: (0, 0, 0) - black)
- `OUTLINE_WIDTH`: Outline thickness in pixels (default: 2)

### Font Settings
- `FONT_SIZE`: Font size in points (default: 96)
- `FONT_PATH`: Path to TrueType font file (default: "fonts/arial.ttf")

### Text Positioning
- `TEXT_POSITION`: Corner placement - `'top-left'`, `'top-right'`, `'bottom-left'`, `'bottom-right'`
- `PADDING`: Distance from image edge in pixels (default: 20)

### Output Settings
- `OUTPUT_QUALITY`: JPEG quality 1-100 (default: 95)

### Coordinate System Settings
- `SHOW_UTM_COORDINATES`: Enable/disable UTM coordinate display (default: True)
- `TARGET_EPSG`: Target EPSG code for coordinate transformation (default: 25832 - UTM Zone 32N)
- `UTM_ZONE`: UTM zone number for display (default: 32)
- `UTM_HEMISPHERE`: UTM hemisphere, 'N' or 'S' (default: 'N')

### Direction Settings
- `SHOW_DIRECTION`: Enable/disable image direction display from GPS data (default: True)
- `DIRECTION_PRECISION`: Cardinal direction precision - 8 or 16 sectors (default: 8)
  - 8 sectors: N, NE, E, SE, S, SW, W, NW (45° increments)
  - 16 sectors: N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW (22.5° increments)

### Project Information
- `PROJECT_INFO`: Optional text displayed at the top of the overlay (default: None)
  - Example: "Highway Survey 2026 - Phase 1" or "Bridge Inspection Q1"

### Processing Settings
- `MAX_WORKERS`: Maximum number of parallel workers (default: 4)
- `FILE_COLLISION_MODE`: How to handle existing files - 'overwrite', 'skip', 'rename' (default: 'overwrite')

### Address Settings
- `SHOW_ADDRESS`: Enable/disable nearest-address lookup (default: True)
- `GEOCODER_TIMEOUT`: Timeout in seconds for reverse geocoding requests (default: 10)

### Chainage / Reference Line Settings
- `SHOW_CHAINAGE`: Enable/disable chainage text in overlays (default: False)
- `CHAINAGE_PREFIX`: Prefix used in formatted stationing text (default: `"kp"`)
- `CHAINAGE_PRECISION`: Round chainage to the nearest N metres (default: 1)
- `SHOW_CHAINAGE_OFFSET`: Append left/right offset from the reference line (default: False)
- `CHAINAGE_START_M`: Value added to all displayed chainage values (default: 0.0)

### Coordinate System Conversion

The tool supports automatic conversion of GPS coordinates (WGS84) to UTM or other projected coordinate systems:

- **WGS84 to UTM conversion**: GPS coordinates are automatically transformed to UTM coordinates
- **Customizable target CRS**: Configure any EPSG code in `config.py` (e.g., 25832 for UTM Zone 32N, 25833 for UTM Zone 33N)
- **Display both formats**: Shows both degree-minute-second format and UTM coordinates on the image
- **Efficient caching**: Coordinate transformers are cached per process to optimize batch operations
- **Error resilient**: Falls back gracefully if coordinate transformation fails

The coordinate conversion uses the **pyproj** library, which provides accurate transformations between different coordinate reference systems based on PROJ definitions.

### Reverse Geocoding (Address Lookup)

When `SHOW_ADDRESS = True`, the tool looks up the nearest street address for each image's GPS coordinates and adds it to the overlay.

- **Provider**: [Nominatim](https://nominatim.org/) (OpenStreetMap), via the **geopy** library — no API key required
- **Rate limiting**: Nominatim enforces a **1 request per second** policy. The tool respects this automatically.
- **In-memory cache**: Coordinates rounded to 6 decimal places (~0.1 m precision) are cached so the same location is never looked up twice within a single run.
- **Pre-geocoding in CLI**: All GPS coordinates are resolved in the main process *before* images are dispatched to worker processes, so the cache is shared across all workers.
- **Pre-geocoding in Web UI**: After loading a folder or uploading files, the server begins geocoding in the background. Preview and batch processing use the cached addresses automatically.
- **Timeout**: Controlled by `GEOCODER_TIMEOUT` in `config.py` (default: 10 seconds). Increase this on slow connections.
- **Graceful fallback**: If a lookup fails or times out, the address line is simply omitted from the overlay — processing continues normally.
- **Privacy note**: GPS coordinates are sent to the public Nominatim service. For sensitive locations, set `SHOW_ADDRESS = False` or host your own Nominatim instance and update the `user_agent` in `exif_handler.py`.

### Chainage from SOSI Reference Lines

When `SHOW_CHAINAGE = True` and a reference line is active in the web UI, the tool calculates stationing for each GPS-tagged image against the selected SOSI `KURVE` geometry.

- **SOSI input**: Load `.sos` or `.sosi` files by path or upload
- **Reference geometry**: Select the `KURVE` object to use as the active line
- **Projected calculations**: Distances are computed in the projected coordinate system declared by the SOSI file
- **Display formatting**: Output is formatted as values such as `kp 1+234`
- **Offset support**: Optional perpendicular offset can be appended as left/right distance from the line
- **Map visualization**: The active line and chainage tick markers can be shown in the map view

## Dependencies

- **Pillow (PIL) >= 10.0.0**: Image processing and text rendering
- **piexif >= 1.1.3**: EXIF metadata extraction
- **tqdm >= 4.65.0**: Progress bars for batch processing
- **pyproj >= 3.6.0**: Coordinate system transformations (WGS84 to UTM/other CRS)
- **geopy >= 2.4.0**: Reverse geocoding via Nominatim (OpenStreetMap)
- **fastapi >= 0.110.0**: Web UI backend framework
- **uvicorn >= 0.29.0**: ASGI server for running the web UI
- **python-multipart >= 0.0.9**: File upload support in the web UI
- **jinja2 >= 3.1.0**: HTML template serving (used by FastAPI)

## Advanced Features

### Image Direction
The tool extracts GPS image direction (bearing) from EXIF data when available:
- **Automatic extraction**: Reads `GPSImgDirection` from EXIF metadata
- **Degree display**: Shows precise bearing (0-360°)
- **Cardinal conversion**: Converts to human-readable directions (N, NE, E, etc.)
- **Configurable precision**: Choose 8-sector or 16-sector compass
- **Graceful fallback**: Shows "Direction: N/A" when GPS direction is unavailable

### Project Information
Add custom project information that appears at the top of every processed image:
- **Flexible text**: Any descriptive text (project name, survey ID, date, etc.)
- **Consistent branding**: Apply the same header to all images in a batch
- **Command-line or config**: Set via `--project-info` flag or `PROJECT_INFO` in config.py

### GPS Correction Workflow
- **Interactive correction**: Move image positions in the web map before processing
- **Selective application**: Process either all loaded images or only a selected subset
- **Persistent fixes**: Corrected GPS coordinates are written back to the source EXIF data when processing starts
- **CLI alternative**: Apply the same kind of correction through `--overrides` with a JSON file

### Multiprocessing
The tool can process images in parallel using a configurable worker count. You can adjust this with the `--workers` option or by changing `MAX_WORKERS` in `config.py`.

### EXIF Preservation
Original EXIF metadata is preserved in processed images, including camera settings, GPS data, and timestamps.

### File Collision Handling
- **overwrite** (default): Replaces existing files
- **rename**: Adds a counter suffix to avoid overwriting (e.g., image_1.jpg, image_2.jpg)
- **skip**: Skips processing if output file already exists

### Logging
- Console logging with INFO level by default
- `--verbose` enables DEBUG level logging with timestamps
- `--quiet` suppresses all output except errors
- `--log-file` saves complete logs to a file for review

### Error Handling
Robust error handling with specific exception catching for:
- Invalid image files
- Corrupted EXIF data
- Missing fonts
- File I/O errors
- Invalid GPS coordinates

## Notes

- Only JPG/JPEG images are currently supported
- Images without EXIF data will still be processed but show "No metadata available"
- GPS coordinates are displayed in degrees, minutes, seconds format
- Reverse geocoding and chainage display are optional and can be disabled
- Image direction is only shown if GPS direction data (`GPSImgDirection`) is available in EXIF
  - Most modern smartphones and drones with GPS+compass record this data
  - Images without direction data will show "Direction: N/A" if direction display is enabled
- Configuration is validated at startup to catch errors early
- Font fallback mechanism tries multiple system fonts if custom font fails
- Normal overlay rendering writes processed copies to the output directory
- Source images are modified only when you explicitly apply GPS corrections through the web UI or the `--overrides` CLI workflow

## License

This project is open source and available for personal and commercial use.
