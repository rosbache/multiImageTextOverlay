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
import config
from image_processor import process_image


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
        default=config.INPUT_DIR,
        help=f'Input directory containing images (default: {config.INPUT_DIR})'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=config.OUTPUT_DIR,
        help=f'Output directory for processed images (default: {config.OUTPUT_DIR})'
    )
    
    # Configuration overrides
    parser.add_argument(
        '--position', '-p',
        choices=['top-left', 'top-right', 'bottom-left', 'bottom-right'],
        help=f'Text position on image (default: {config.TEXT_POSITION})'
    )
    parser.add_argument(
        '--color', '-c',
        nargs=3,
        type=int,
        metavar=('R', 'G', 'B'),
        help=f'Text color as RGB values 0-255 (default: {config.TEXT_COLOR})'
    )
    parser.add_argument(
        '--font-size', '-s',
        type=int,
        help=f'Font size in points (default: {config.FONT_SIZE})'
    )
    parser.add_argument(
        '--quality', '-q',
        type=int,
        help=f'Output JPEG quality 1-100 (default: {config.OUTPUT_QUALITY})'
    )
    
    # Processing options
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=config.MAX_WORKERS,
        help=f'Maximum number of parallel workers (default: {config.MAX_WORKERS})'
    )
    parser.add_argument(
        '--collision',
        choices=['overwrite', 'skip', 'rename'],
        default=config.FILE_COLLISION_MODE,
        help=f'File collision handling mode (default: {config.FILE_COLLISION_MODE})'
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


def apply_argument_overrides(args):
    """
    Apply command-line argument overrides to config module.
    
    Args:
        args: Parsed command-line arguments
    """
    if args.position:
        config.TEXT_POSITION = args.position
    if args.color:
        config.TEXT_COLOR = tuple(args.color)
    if args.font_size:
        config.FONT_SIZE = args.font_size
    if args.quality:
        config.OUTPUT_QUALITY = args.quality
    
    # Update file collision mode
    config.FILE_COLLISION_MODE = args.collision


def get_unique_output_path(output_path: Path) -> Path:
    """
    Generate a unique output path by adding a counter if file exists.
    
    Args:
        output_path: Desired output path
        
    Returns:
        Unique output path
    """
    if not output_path.exists():
        return output_path
    
    stem = output_path.stem
    suffix = output_path.suffix
    parent = output_path.parent
    counter = 1
    
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def process_single_image(args_tuple: Tuple[Path, Path, str]) -> Tuple[bool, str, str]:
    """
    Wrapper function for processing a single image (for multiprocessing).
    
    Args:
        args_tuple: Tuple of (input_path, output_dir, collision_mode)
        
    Returns:
        Tuple of (success, input_filename, message)
    """
    input_path, output_dir, collision_mode = args_tuple
    
    # Create output path with same filename
    output_path = output_dir / input_path.name
    
    # Handle file collision
    if output_path.exists():
        if collision_mode == 'skip':
            return True, input_path.name, "skipped (already exists)"
        elif collision_mode == 'rename':
            output_path = get_unique_output_path(output_path)
            logging.debug(f"Renamed output to: {output_path.name}")
    
    # Process the image
    success = process_image(str(input_path), str(output_path))
    
    if success:
        return True, input_path.name, "processed successfully"
    else:
        return False, input_path.name, "processing failed"


def main():
    """
    Main function to process all images in input directory.
    """
    # Parse command-line arguments
    args = parse_arguments()
    
    # Setup logging
    setup_logging(args.verbose, args.quiet, args.log_file)
    
    # Apply argument overrides to config
    apply_argument_overrides(args)
    
    # Validate configuration
    try:
        config.validate_config()
        logging.debug("Configuration validated successfully")
    except ValueError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Define directories
    input_dir = Path(args.input)
    output_dir = Path(args.output)
    
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
    
    # Get all JPG files from input directory
    jpg_extensions = ['*.jpg', '*.JPG', '*.jpeg', '*.JPEG']
    jpg_files = []
    for ext in jpg_extensions:
        jpg_files.extend(input_dir.glob(ext))
    
    if not jpg_files:
        logging.warning(f"No JPG images found in '{input_dir}' directory.")
        logging.info(f"Please add JPG images to the '{input_dir}' folder.")
        return
    
    logging.info(f"Found {len(jpg_files)} image(s) to process")
    
    # Dry-run mode
    if args.dry_run:
        logging.info("DRY-RUN MODE: No files will be processed")
        logging.info(f"Input directory: {input_dir.absolute()}")
        logging.info(f"Output directory: {output_dir.absolute()}")
        logging.info("Files to be processed:")
        for jpg_file in jpg_files:
            logging.info(f"  - {jpg_file.name}")
        logging.info(f"\nConfiguration:")
        logging.info(f"  Text position: {config.TEXT_POSITION}")
        logging.info(f"  Text color: RGB{config.TEXT_COLOR}")
        logging.info(f"  Font size: {config.FONT_SIZE}")
        logging.info(f"  Output quality: {config.OUTPUT_QUALITY}")
        logging.info(f"  Max workers: {args.workers}")
        logging.info(f"  Collision mode: {args.collision}")
        return
    
    # Prepare arguments for multiprocessing
    process_args = [(jpg_file, output_dir, args.collision) for jpg_file in jpg_files]
    
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
                    success, name, message = future.result()
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

