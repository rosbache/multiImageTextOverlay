"""
Image Processing Module

Handles image reading, text overlay creation, and saving processed images.
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import config
from exif_handler import extract_exif_data


def create_overlay_text(metadata: dict) -> str:
    """
    Create formatted text string from metadata.
    
    Args:
        metadata: Dictionary with 'datetime' and 'location' keys
        
    Returns:
        Formatted text string for overlay
    """
    lines = []
    
    if metadata['datetime']:
        # Format datetime (from "YYYY:MM:DD HH:MM:SS" to more readable format)
        datetime_str = metadata['datetime'].replace(':', '-', 2)
        lines.append(f"Date: {datetime_str}")
    
    if metadata['location']:
        lines.append(f"Location: {metadata['location']}")
    
    return '\n'.join(lines) if lines else "No metadata available"


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
        # Extract EXIF metadata
        metadata = extract_exif_data(input_path)
        
        # Open image
        image = Image.open(input_path)
        
        # Create a drawing context
        draw = ImageDraw.Draw(image)
        
        # Load font
        try:
            font = ImageFont.truetype(config.FONT_PATH, config.FONT_SIZE)
        except Exception as e:
            print(f"Warning: Could not load font from {config.FONT_PATH}, using default font")
            font = ImageFont.load_default()
        
        # Prepare overlay text
        overlay_text = create_overlay_text(metadata)
        
        # Calculate text position based on configuration
        if config.TEXT_POSITION == 'top-left':
            position = (config.PADDING, config.PADDING)
        elif config.TEXT_POSITION == 'top-right':
            # Get text bounding box to align right
            bbox = draw.textbbox((0, 0), overlay_text, font=font)
            text_width = bbox[2] - bbox[0]
            position = (image.width - text_width - config.PADDING, config.PADDING)
        elif config.TEXT_POSITION == 'bottom-left':
            bbox = draw.textbbox((0, 0), overlay_text, font=font)
            text_height = bbox[3] - bbox[1]
            position = (config.PADDING, image.height - text_height - config.PADDING)
        elif config.TEXT_POSITION == 'bottom-right':
            bbox = draw.textbbox((0, 0), overlay_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            position = (image.width - text_width - config.PADDING, 
                       image.height - text_height - config.PADDING)
        else:
            # Default to bottom-left
            bbox = draw.textbbox((0, 0), overlay_text, font=font)
            text_height = bbox[3] - bbox[1]
            position = (config.PADDING, image.height - text_height - config.PADDING)
        
        # Draw text with outline for better visibility
        x, y = position
        outline_color = config.OUTLINE_COLOR
        outline_width = config.OUTLINE_WIDTH
        
        # Draw outline
        for adj_x in range(-outline_width, outline_width + 1):
            for adj_y in range(-outline_width, outline_width + 1):
                draw.text((x + adj_x, y + adj_y), overlay_text, font=font, fill=outline_color)
        
        # Draw main text
        draw.text(position, overlay_text, font=font, fill=config.TEXT_COLOR)
        
        # Save processed image
        image.save(output_path, quality=config.OUTPUT_QUALITY)
        
        return True
        
    except Exception as e:
        print(f"Error processing image {input_path}: {e}")
        return False
