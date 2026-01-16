"""
Configuration Settings

User-configurable settings for image metadata overlay.
Modify these values to customize the appearance of overlaid text.
"""

# Text appearance
TEXT_COLOR = (255, 0, 0)  # RGB tuple - White by default
OUTLINE_COLOR = (0, 0, 0)     # RGB tuple - Black outline for visibility
OUTLINE_WIDTH = 2             # Pixels for text outline

# Font settings
FONT_SIZE = 96               # Font size in points
FONT_PATH = "fonts/arial.ttf" # Path to TrueType font file

# Text positioning
TEXT_POSITION = 'bottom-left'  # Options: 'top-left', 'top-right', 'bottom-left', 'bottom-right'
PADDING = 20                   # Pixels from edge of image

# Output settings
OUTPUT_QUALITY = 95            # JPEG quality (1-100, higher is better)
