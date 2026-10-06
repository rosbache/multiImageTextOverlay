"""
Image Metadata Overlay - Main Entry Point

Processes all JPG images in the input/ folder and creates copies
with metadata overlays in the output/ folder.
"""

import os
import argparse
import logging
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Tuple
from tqdm import tqdm
from image_metadata_overlay import config as app_config
from image_metadata_overlay.config import DEFAULT_CONFIG, OverlayConfig
from image_metadata_overlay.core.overlay import process_image
from image_metadata_overlay.core.exif import extract_exif_data, reverse_geocode
from image_metadata_overlay.services.batch import process_single_image


# Configure logging
def setup_logging(verbose: bool = False, quiet: bool = False, log_file: str = None):
    """
    Configure logging for the application.
    
    Args:
        verbose: Enable debug logging
        quiet: Suppress all console output except errors
        log_file: Optional file path for logging
    """
    log_level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    simple_formatter = logging.Formatter('%(levelname)s: %(message)s')
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Capture all levels, handlers will filter
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter if not verbose else detailed_formatter)
    logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        logger.addHandler(file_handler)
        logging.info(f"Logging to file: {log_file}")


def parse_arguments():
    """
    Parse command-line arguments.
    
    Returns:
        Namespace object with parsed arguments
    """
    parser = argparse.ArgumentParser(
        description='Add metadata overlays to images with EXIF data.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s                                    # Process input/ to output/
  %(prog)s --input photos --output processed  # Custom directories
  %(prog)s --position top-right --color 255 0 0  # Red text, top-right
  %(prog)s --verbose --log-file process.log   # Verbose with file logging
  %(prog)s --dry-run                          # Preview without processing
        '''
    )
    
    # Directory arguments
    parser.add_argument(
        '--input', '-i',
        type=str,
        default=app_config.INPUT_DIR,
        help=f'Input directory containing images (default: {app_config.INPUT_DIR})'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=app_config.OUTPUT_DIR,
        help=f'Output directory for processed images (default: {app_config.OUTPUT_DIR})'
    )
    
    # Configuration overrides
    parser.add_argument(
        '--position', '-p',
        choices=['top-left', 'top-right', 'bottom-left', 'bottom-right'],
        help=f'Text position on image (default: {DEFAULT_CONFIG.text_position})'
    )
    parser.add_argument(
        '--color', '-c',
        nargs=3,
        type=int,
        metavar=('R', 'G', 'B'),
        help=f'Text color as RGB values 0-255 (default: {DEFAULT_CONFIG.text_color})'
    )
    parser.add_argument(
        '--font-size', '-s',
        type=int,
        help=f'Font size in points (default: {DEFAULT_CONFIG.font_size})'
    )
    parser.add_argument(
        '--quality', '-q',
        type=int,
        help=f'Output JPEG quality 1-100 (default: {DEFAULT_CONFIG.output_quality})'
    )
    
    # Coordinate system options
    parser.add_argument(
        '--target-epsg',
        type=int,
        help=f'Target EPSG code for coordinate transformation (default: {DEFAULT_CONFIG.target_epsg})'
    )
    parser.add_argument(
        '--no-utm',
        action='store_true',
        help='Disable UTM coordinate display (show only WGS84)'
    )
    
    # Direction options
    parser.add_argument(
        '--show-direction',
        action='store_true',
        default=None,
        help='Enable image direction display (degrees and cardinal)'
    )
    parser.add_argument(
        '--no-direction',
        action='store_true',
        help='Disable image direction display'
    )

    # Address options
    parser.add_argument(
        '--no-address',
        action='store_true',
        help='Disable nearest address lookup from GPS coordinates'
    )

    parser.add_argument(
        '--direction-precision',
        type=int,
        choices=[8, 16],
        help=f'Cardinal direction precision: 8 (N,NE,E...) or 16 (N,NNE,NE...) (default: {DEFAULT_CONFIG.direction_precision})'
    )
    
    # Project information
    parser.add_argument(
        '--project-info',
        type=str,
        help='Project information text to display at top of overlay (e.g., "Project XYZ - Survey 2024")'
    )
    
    # Processing options
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=DEFAULT_CONFIG.max_workers,
        help=f'Maximum number of parallel workers (default: {DEFAULT_CONFIG.max_workers})'
    )
    parser.add_argument(
        '--collision',
        choices=['overwrite', 'skip', 'rename'],
        default=DEFAULT_CONFIG.file_collision_mode,
        help=f'File collision handling mode (default: {DEFAULT_CONFIG.file_collision_mode})'
    )
    parser.add_argument(
        '--overrides',
        type=str,
        metavar='FILE',
        help='JSON file with location overrides (format: {"filename.jpg": {"lat": 59.9, "lon": 10.75}})'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview files to be processed without actually processing them'
    )
    
    # Logging options
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose (debug) logging'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress console output except errors'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        help='Save logs to specified file'
    )
    
    return parser.parse_args()


def build_config(args) -> OverlayConfig:
    """
    Build the job's immutable OverlayConfig from defaults plus CLI overrides.

    Args:
        args: Parsed command-line arguments

    Returns:
        OverlayConfig with all CLI overrides applied
    """
    cfg = DEFAULT_CONFIG
    if args.position:
        cfg = cfg.with_overrides(text_position=args.position)
    if args.color:
        cfg = cfg.with_overrides(text_color=tuple(args.color))
    if args.font_size:
        cfg = cfg.with_overrides(font_size=args.font_size)
    if args.quality:
        cfg = cfg.with_overrides(output_quality=args.quality)
    if args.target_epsg:
        cfg = cfg.with_overrides(target_epsg=args.target_epsg)
    if args.no_utm:
        cfg = cfg.with_overrides(show_utm_coordinates=False)

    # Direction settings
    if args.show_direction:
        cfg = cfg.with_overrides(show_direction=True)
    if args.no_direction:
        cfg = cfg.with_overrides(show_direction=False)
    if args.direction_precision:
        cfg = cfg.with_overrides(direction_precision=args.direction_precision)

    # Address settings
    if args.no_address:
        cfg = cfg.with_overrides(show_address=False)

    # Project information
    if args.project_info:
        cfg = cfg.with_overrides(project_info=args.project_info)

    # File collision mode
    return cfg.with_overrides(file_collision_mode=args.collision)


def main():
    """
    Main function to process all images in input directory.
    """
    # Parse command-line arguments
    args = parse_arguments()
    
    # Setup logging
    setup_logging(args.verbose, args.quiet, args.log_file)
    
    # Build the job config from defaults plus CLI overrides
    overlay_cfg = build_config(args)

    # Validate configuration
    try:
        overlay_cfg.validate()
        logging.debug("Configuration validated successfully")
    except ValueError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Validate EPSG code if UTM coordinates are enabled
    if overlay_cfg.show_utm_coordinates:
        try:
            from pyproj import CRS
            # Test if EPSG code is valid
            test_crs = CRS.from_epsg(overlay_cfg.target_epsg)
            logging.info(f"Using coordinate system: {test_crs.name} (EPSG:{overlay_cfg.target_epsg})")
        except Exception as e:
            logging.error(f"Invalid EPSG code {overlay_cfg.target_epsg}: {e}")
            logging.error("Please specify a valid EPSG code using --target-epsg")
            logging.error("Common EPSG codes: 25832 (UTM 32N), 25833 (UTM 33N), 32632 (WGS84 UTM 32N)")
            sys.exit(1)
    
    # Determine input and output directories
    input_dir = Path(args.input if args.input else app_config.INPUT_DIR)
    output_dir = Path(args.output if args.output else app_config.OUTPUT_DIR)
    
    # Check if input directory exists
    if not input_dir.exists():
        logging.error(f"Input directory '{input_dir}' does not exist.")
        logging.info(f"Please create the '{input_dir}' folder and add JPG images to process.")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        logging.debug(f"Output directory: {output_dir.absolute()}")
    except OSError as e:
        logging.error(f"Failed to create output directory: {e}")
        sys.exit(1)
    
    # Get all JPG files from input directory (case-insensitive)
    jpg_files = [f for f in input_dir.iterdir() 
                 if f.is_file() and f.suffix.lower() in ['.jpg', '.jpeg']]
    
    if not jpg_files:
        logging.warning(f"No JPG images found in '{input_dir}' directory.")
        logging.info(f"Please add JPG images to the '{input_dir}' folder.")
        return
    
    logging.info(f"Found {len(jpg_files)} image(s) to process")
    
    # Load and apply location overrides if provided
    if args.overrides:
        import json
        from image_metadata_overlay.core.exif import write_gps_to_exif
        
        try:
            with open(args.overrides, 'r', encoding='utf-8') as f:
                overrides = json.load(f)
            
            if not isinstance(overrides, dict):
                logging.error(f"Overrides file must contain a JSON object, got {type(overrides).__name__}")
                sys.exit(1)
            
            logging.info(f"Loaded {len(overrides)} location override(s) from {args.overrides}")
            
            # Apply overrides to source EXIF
            override_count = 0
            for jpg_file in jpg_files:
                if jpg_file.name in overrides:
                    override_data = overrides[jpg_file.name]
                    
                    if not isinstance(override_data, dict):
                        logging.warning(f"Invalid override format for {jpg_file.name}, skipping")
                        continue
                    
                    lat = override_data.get('lat')
                    lon = override_data.get('lon')
                    altitude = override_data.get('altitude')
                    
                    if lat is None or lon is None:
                        logging.warning(f"Missing lat/lon in override for {jpg_file.name}, skipping")
                        continue
                    
                    success = write_gps_to_exif(str(jpg_file), lat, lon, altitude)
                    if success:
                        override_count += 1
                        logging.debug(f"Applied location override to {jpg_file.name}: ({lat:.6f}, {lon:.6f})")
            
            if override_count > 0:
                logging.info(f"Applied {override_count} location override(s) to source EXIF data")
        
        except FileNotFoundError:
            logging.error(f"Overrides file not found: {args.overrides}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON in overrides file: {e}")
            sys.exit(1)
        except Exception as e:
            logging.error(f"Error loading overrides: {e}")
            sys.exit(1)
    
    # Dry-run mode
    if args.dry_run:
        logging.info("DRY-RUN MODE: No files will be processed")
        logging.info(f"Input directory: {input_dir.absolute()}")
        logging.info(f"Output directory: {output_dir.absolute()}")
        logging.info("Files to be processed:")
        for jpg_file in jpg_files:
            logging.info(f"  - {jpg_file.name}")
        logging.info(f"\nConfiguration:")
        logging.info(f"  Text position: {overlay_cfg.text_position}")
        logging.info(f"  Text color: RGB{overlay_cfg.text_color}")
        logging.info(f"  Font size: {overlay_cfg.font_size}")
        logging.info(f"  Output quality: {overlay_cfg.output_quality}")
        logging.info(f"  Show UTM coordinates: {overlay_cfg.show_utm_coordinates}")
        if overlay_cfg.show_utm_coordinates:
            logging.info(f"  Target EPSG: {overlay_cfg.target_epsg}")
            logging.info(f"  UTM Zone: {overlay_cfg.utm_zone}{overlay_cfg.utm_hemisphere}")
        logging.info(f"  Show direction: {overlay_cfg.show_direction}")
        if overlay_cfg.show_direction:
            logging.info(f"  Direction precision: {overlay_cfg.direction_precision} sectors")
        if overlay_cfg.project_info:
            logging.info(f"  Project info: {overlay_cfg.project_info}")
        logging.info(f"  Max workers: {args.workers}")
        logging.info(f"  Collision mode: {args.collision}")
        return
    
    # The immutable job config is passed to each worker process.

    # Pre-geocode coordinates in the main process to share cache across all images
    address_map: dict = {}
    if overlay_cfg.show_address:
        logging.info("Looking up addresses for GPS coordinates...")
        for jpg_file in jpg_files:
            try:
                meta = extract_exif_data(str(jpg_file), filename=jpg_file.stem)
                lat = meta.get('_lat_decimal')
                lon = meta.get('_lon_decimal')
                if lat is not None and lon is not None:
                    address_map[jpg_file.name] = reverse_geocode(
                        lat, lon, timeout=overlay_cfg.geocoder_timeout
                    )
                else:
                    address_map[jpg_file.name] = None
            except Exception as e:
                logging.warning(f"Could not get address for {jpg_file.name}: {e}")
                address_map[jpg_file.name] = None

    process_args = [
        (jpg_file, output_dir, args.collision, overlay_cfg,
         address_map.get(jpg_file.name), None)  # chainage: no reference line in CLI (yet)
        for jpg_file in jpg_files
    ]
    
    # Process images with multiprocessing
    success_count = 0
    results = []
    
    logging.info(f"Processing with {min(args.workers, len(jpg_files))} worker(s)...")
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        futures = {executor.submit(process_single_image, arg): arg[0].name 
                   for arg in process_args}
        
        # Process results with progress bar
        with tqdm(total=len(jpg_files), desc="Processing images", 
                  disable=args.quiet or args.verbose, unit="image") as pbar:
            for future in as_completed(futures):
                filename = futures[future]
                try:
                    success, name, message, _output_name = future.result()
                    results.append((success, name, message))
                    if success:
                        success_count += 1
                        logging.debug(f"{name}: {message}")
                    else:
                        logging.error(f"{name}: {message}")
                except Exception as e:
                    logging.error(f"{filename}: Unexpected error: {e}")
                    results.append((False, filename, f"exception: {e}"))
                finally:
                    pbar.update(1)
    
    # Summary
    logging.info("=" * 60)
    logging.info("Processing complete!")
    logging.info(f"Successfully processed: {success_count}/{len(jpg_files)} images")
    if success_count < len(jpg_files):
        failed_count = len(jpg_files) - success_count
        logging.warning(f"Failed: {failed_count} image(s)")
    logging.info(f"Output saved to: {output_dir.absolute()}")
    logging.info("=" * 60)


if __name__ == "__main__":
    main()

