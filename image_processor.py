"""
Image Processing Module

Handles image reading, text overlay creation, and saving processed images.
"""

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from pathlib import Path
import logging
import piexif
import config
from exif_handler import extract_exif_data


def create_overlay_text(metadata: dict) -> str:
    """
    Create formatted text string from metadata.
    
    Args:
        metadata: Dictionary with 'filename', 'datetime', 'location', 'altitude', 'direction', 
                  'direction_cardinal', 'project_info', and optionally 'location_utm' keys
        
    Returns:
        Formatted text string for overlay
    """
    lines = []
    
    # Add project info at the top (if available)
    if metadata.get('project_info'):
        lines.append(metadata['project_info'])
        lines.append('')  # Add blank line separator
    
    # Add filename (if available)
    if metadata.get('filename'):
        lines.append(metadata['filename'])
    
    if metadata.get('datetime'):
        # Format datetime (from "YYYY:MM:DD HH:MM:SS" to more readable format)
        datetime_str = metadata['datetime'].replace(':', '-', 2)
        lines.append(f"Date: {datetime_str}")
    
    if metadata.get('location'):
        lines.append(f"Location: {metadata['location']}")
    
    # Add UTM coordinates if available
    if metadata.get('location_utm'):
        lines.append(metadata['location_utm'])
    
    # Add altitude/height if available
    if metadata.get('altitude') is not None:
        lines.append(f"Height: {metadata['altitude']:.1f} m")
    
    # Add direction if available or show N/A
    if metadata.get('show_direction'):
        if metadata.get('direction') is not None and metadata.get('direction_cardinal'):
            lines.append(f"Direction: {metadata['direction']:.0f}° ({metadata['direction_cardinal']})")
        else:
            lines.append("Direction: N/A")
    
    # If only filename/project exists, add "No metadata available"
    metadata_exists = any([
        metadata.get('datetime'),
        metadata.get('location'),
        metadata.get('altitude') is not None,
        metadata.get('direction') is not None
    ])
    if not metadata_exists and (metadata.get('filename') or metadata.get('project_info')):
        lines.append("No metadata available")
    
    return '\n'.join(lines) if lines else "No metadata available"


def load_font_with_fallback() -> ImageFont.FreeTypeFont:
    """
    Load font with fallback to bundled default font.
    
    Returns:
        Loaded font object
    """
    try:
        font = ImageFont.truetype(config.FONT_PATH, config.FONT_SIZE)
        logging.debug(f"Loaded font: {config.FONT_PATH} at size {config.FONT_SIZE}")
        return font
    except (OSError, IOError) as e:
        logging.warning(f"Could not load font from {config.FONT_PATH}: {e}")
        logging.warning("Attempting to use default font")
        try:
            # Try to load a system font as fallback
            # For Windows, try Arial
            fallback_fonts = [
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/verdana.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
                "/System/Library/Fonts/Helvetica.ttc",  # macOS
            ]
            for fallback in fallback_fonts:
                try:
                    font = ImageFont.truetype(fallback, config.FONT_SIZE)
                    logging.info(f"Using fallback font: {fallback}")
                    return font
                except (OSError, IOError):
                    continue
            
            # If all else fails, use the default bitmap font (deprecated but works)
            logging.warning("All font loading attempts failed, using basic default font")
            return ImageFont.load_default()
        except Exception as e:
            logging.error(f"Critical font loading error: {e}")
            return ImageFont.load_default()


def process_image(input_path: str, output_path: str) -> bool:
    """
    Process a single image by adding metadata overlay.
    
    Args:
        input_path: Path to source JPG image
        output_path: Path to save processed image
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Extract filename without extension
        filename_base = Path(input_path).stem
        
        # Extract EXIF metadata
        metadata = extract_exif_data(input_path, filename=filename_base)
        
        # Add project info if configured
        if config.PROJECT_INFO:
            metadata['project_info'] = config.PROJECT_INFO
        
        # Add direction display flag
        metadata['show_direction'] = config.SHOW_DIRECTION
        
        # Convert direction to cardinal if available and enabled
        if config.SHOW_DIRECTION and metadata.get('direction') is not None:
            from exif_handler import degrees_to_cardinal
            metadata['direction_cardinal'] = degrees_to_cardinal(
                metadata['direction'], 
                config.DIRECTION_PRECISION
            )
        
        # Open and verify image
        try:
            image = Image.open(input_path)
            image.verify()  # Verify image integrity
            image = Image.open(input_path)  # Reload after verify
        except UnidentifiedImageError as e:
            logging.error(f"Cannot identify image file {input_path}: {e}")
            return False
        except (OSError, IOError) as e:
            logging.error(f"Cannot open image file {input_path}: {e}")
            return False
        
        # Preserve original EXIF data
        try:
            original_exif = piexif.load(input_path)
            exif_bytes = piexif.dump(original_exif)
        except Exception as e:
            logging.warning(f"Could not load EXIF for preservation: {e}")
            exif_bytes = None
        
        # Create a drawing context
        draw = ImageDraw.Draw(image)
        
        # Load font (singleton pattern - could be optimized further)
        font = load_font_with_fallback()
        
        # Prepare overlay text
        overlay_text = create_overlay_text(metadata)
        
        # Calculate text bounding box
        bbox = draw.textbbox((0, 0), overlay_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Calculate text position based on configuration
        position_map = {
            'top-left': (config.PADDING, config.PADDING),
            'top-right': (image.width - text_width - config.PADDING, config.PADDING),
            'bottom-left': (config.PADDING, image.height - text_height - config.PADDING),
            'bottom-right': (image.width - text_width - config.PADDING, 
                           image.height - text_height - config.PADDING)
        }
        
        position = position_map.get(config.TEXT_POSITION, 
                                    (config.PADDING, image.height - text_height - config.PADDING))
        
        # Draw text with outline using modern Pillow API
        # This replaces the old nested loop approach with native stroke support
        draw.text(
            position, 
            overlay_text, 
            font=font, 
            fill=config.TEXT_COLOR,
            stroke_width=config.OUTLINE_WIDTH,
            stroke_fill=config.OUTLINE_COLOR
        )
        
        # Save processed image with original EXIF preserved
        save_kwargs = {
            'quality': config.OUTPUT_QUALITY,
            'optimize': True
        }
        
        if exif_bytes:
            save_kwargs['exif'] = exif_bytes
        
        try:
            image.save(output_path, **save_kwargs)
            logging.debug(f"Saved processed image to: {output_path}")
        except (OSError, IOError) as e:
            logging.error(f"Failed to save image to {output_path}: {e}")
            return False
        
        return True
        
    except Exception as e:
        # Catch any unexpected exceptions
        logging.error(f"Unexpected error processing {input_path}: {e}", exc_info=True)
        return False

