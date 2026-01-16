"""
Configuration Settings

User-configurable settings for image metadata overlay.
Modify these values to customize the appearance of overlaid text.
"""

import os
from pathlib import Path
import sys

# Directory settings
INPUT_DIR = "input"           # Default input directory
OUTPUT_DIR = "output"         # Default output directory

# Text appearance
TEXT_COLOR = (255, 255, 255)  # RGB tuple - White
OUTLINE_COLOR = (0, 0, 0)     # RGB tuple - Black outline for visibility
OUTLINE_WIDTH = 2             # Pixels for text outline

# Font settings
FONT_SIZE = 96                # Font size in points
FONT_PATH = "fonts/arial.ttf" # Path to TrueType font file

# Text positioning
TEXT_POSITION = 'bottom-left'  # Options: 'top-left', 'top-right', 'bottom-left', 'bottom-right'
PADDING = 20                   # Pixels from edge of image

# Output settings
OUTPUT_QUALITY = 95            # JPEG quality (1-100, higher is better)

# Processing settings
MAX_WORKERS = 6                # Maximum number of parallel workers for multiprocessing

# Output safety settings
FILE_COLLISION_MODE = 'rename' # Options: 'overwrite', 'skip', 'rename'


def validate_config():
    """
    Validate configuration values.
    Raises ValueError if any configuration is invalid.
    """
    # Validate RGB tuples
    def validate_rgb(color, name):
        if not isinstance(color, tuple) or len(color) != 3:
            raise ValueError(f"{name} must be a tuple of 3 values (R, G, B)")
        if not all(isinstance(c, int) and 0 <= c <= 255 for c in color):
            raise ValueError(f"{name} values must be integers between 0 and 255")
    
    validate_rgb(TEXT_COLOR, "TEXT_COLOR")
    validate_rgb(OUTLINE_COLOR, "OUTLINE_COLOR")
    
    # Validate font size
    if not isinstance(FONT_SIZE, int) or FONT_SIZE < 1 or FONT_SIZE > 500:
        raise ValueError("FONT_SIZE must be an integer between 1 and 500")
    
    # Validate outline width
    if not isinstance(OUTLINE_WIDTH, int) or OUTLINE_WIDTH < 0 or OUTLINE_WIDTH > 20:
        raise ValueError("OUTLINE_WIDTH must be an integer between 0 and 20")
    
    # Validate text position
    valid_positions = ['top-left', 'top-right', 'bottom-left', 'bottom-right']
    if TEXT_POSITION not in valid_positions:
        raise ValueError(f"TEXT_POSITION must be one of: {', '.join(valid_positions)}")
    
    # Validate padding
    if not isinstance(PADDING, int) or PADDING < 0:
        raise ValueError("PADDING must be a non-negative integer")
    
    # Validate output quality
    if not isinstance(OUTPUT_QUALITY, int) or OUTPUT_QUALITY < 1 or OUTPUT_QUALITY > 100:
        raise ValueError("OUTPUT_QUALITY must be an integer between 1 and 100")
    
    # Validate max workers
    if not isinstance(MAX_WORKERS, int) or MAX_WORKERS < 1 or MAX_WORKERS > 32:
        raise ValueError("MAX_WORKERS must be an integer between 1 and 32")
    
    # Validate file collision mode
    valid_modes = ['overwrite', 'skip', 'rename']
    if FILE_COLLISION_MODE not in valid_modes:
        raise ValueError(f"FILE_COLLISION_MODE must be one of: {', '.join(valid_modes)}")
    
    return True
