"""
Image Processing Module

Handles image reading, text overlay creation, and saving processed images.
"""

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from pathlib import Path
import logging
import shutil
import piexif
from image_metadata_overlay.config import DEFAULT_CONFIG, OverlayConfig
from image_metadata_overlay.core.exif import extract_exif_data
from image_metadata_overlay.paths import resolve_font


def create_overlay_text(metadata: dict, config: OverlayConfig = DEFAULT_CONFIG) -> str:
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
        # If the polygon field value should live with project info, place it
        # right below the project info before the blank separator line.
        if metadata.get('polygon_value') and config.polygon_append_project_info:
            lines.append(metadata['polygon_value'])
        lines.append('')  # Add blank line separator
    elif metadata.get('polygon_value') and config.polygon_append_project_info:
        # No project info configured, but the user still wants the polygon
        # value shown as its own top-of-overlay line.
        lines.append(metadata['polygon_value'])
        lines.append('')
    
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

    # Add address if available
    if config.show_address and metadata.get('address'):
        lines.append(f"Address: {metadata['address']}")

    # Add direction if available or show N/A
    if metadata.get('show_direction'):
        if metadata.get('direction') is not None and metadata.get('direction_cardinal'):
            lines.append(f"Direction: {metadata['direction']:.0f}° ({metadata['direction_cardinal']})")
        else:
            lines.append("Direction: N/A")
    
    # Add chainage if configured
    if metadata.get('show_chainage'):
        ch = metadata.get('chainage')
        lines.append(f"Chainage: {ch}" if ch else "Chainage: N/A")

    # Mark images whose GPS location was manually edited
    if metadata.get('location_edited'):
        lines.append("* Location edited")

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


def load_font_with_fallback(config: OverlayConfig = DEFAULT_CONFIG) -> ImageFont.FreeTypeFont:
    """
    Load font with fallback to bundled default font.
    
    Returns:
        Loaded font object
    """
    try:
        font_path = resolve_font(config.font_path)
        font = ImageFont.truetype(font_path, config.font_size)
        logging.debug(f"Loaded font: {font_path} at size {config.font_size}")
        return font
    except (OSError, IOError) as e:
        logging.warning(f"Could not load font from {config.font_path}: {e}")
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
                    font = ImageFont.truetype(fallback, config.font_size)
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


def process_image(input_path: str, output_path: str, address: str = None, chainage: str = None, location_edited: bool = False, polygon_value: str = None, config: OverlayConfig = DEFAULT_CONFIG) -> bool:
    """
    Process a single image by adding metadata overlay.
    
    Args:
        input_path: Path to source JPG image
        output_path: Path to save processed image
        address: Pre-computed address string from geocoding (or None)
        chainage: Pre-computed chainage string, e.g. "kp 1+234" (or None)
        location_edited: Whether the image's GPS was manually edited
        polygon_value: Pre-computed polygon field value for this image (or None)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # No-text mode: lossless copy — pixels and EXIF stay byte-identical
        if not config.add_text_overlay:
            if Path(input_path).resolve() == Path(output_path).resolve():
                logging.info(f"Overlay disabled and output equals input, nothing to do: {input_path}")
                return True
            shutil.copy2(input_path, output_path)
            logging.debug(f"Copied image without overlay to: {output_path}")
            return True

        # Extract filename without extension
        filename_base = Path(input_path).stem
        
        # Extract EXIF metadata
        metadata = extract_exif_data(input_path, filename=filename_base)

        # Inject pre-computed address if provided
        if address is not None:
            metadata['address'] = address

        # Add project info if configured
        if config.project_info:
            metadata['project_info'] = config.project_info
        
        # Add direction display flag
        metadata['show_direction'] = config.show_direction

        # Add chainage if available
        metadata['show_chainage'] = config.show_chainage
        if chainage is not None:
            metadata['chainage'] = chainage

        metadata['location_edited'] = location_edited

        if polygon_value:
            metadata['polygon_value'] = polygon_value
        
        # Convert direction to cardinal if available and enabled
        if config.show_direction and metadata.get('direction') is not None:
            from image_metadata_overlay.core.exif import degrees_to_cardinal
            metadata['direction_cardinal'] = degrees_to_cardinal(
                metadata['direction'], 
                config.direction_precision
            )
        
        # Open and verify image
        try:
            image = Image.open(input_path)
            image.verify()  # Verify image integrity
            image = Image.open(input_path)  # Reload after verify
            image = ImageOps.exif_transpose(image)  # Apply EXIF orientation so portrait images are upright
        except UnidentifiedImageError as e:
            logging.error(f"Cannot identify image file {input_path}: {e}")
            return False
        except (OSError, IOError) as e:
            logging.error(f"Cannot open image file {input_path}: {e}")
            return False
        
        # Preserve original EXIF data
        try:
            original_exif = piexif.load(input_path)
            # Reset orientation to 1 (normal) since pixels are now correctly rotated
            if piexif.ImageIFD.Orientation in original_exif.get('0th', {}):
                original_exif['0th'][piexif.ImageIFD.Orientation] = 1
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
            'top-left': (config.padding, config.padding),
            'top-right': (image.width - text_width - config.padding, config.padding),
            'bottom-left': (config.padding, image.height - text_height - config.padding),
            'bottom-right': (image.width - text_width - config.padding,
                           image.height - text_height - config.padding)
        }

        position = position_map.get(config.text_position,
                                    (config.padding, image.height - text_height - config.padding))
        
        # Draw text with outline using modern Pillow API
        # This replaces the old nested loop approach with native stroke support
        draw.text(
            position, 
            overlay_text, 
            font=font, 
            fill=config.text_color,
            stroke_width=config.outline_width,
            stroke_fill=config.outline_color
        )
        
        # Save processed image with original EXIF preserved
        save_kwargs = {
            'quality': config.output_quality,
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

