"""
EXIF Metadata Extraction Module

Extracts DateTime and GPS location data from JPG image EXIF metadata.
"""

import piexif
import logging
from typing import Optional, Tuple


def rational_to_decimal(rational: Tuple[Tuple[int, int], ...]) -> float:
    """
    Convert GPS rational coordinates to decimal degrees.
    
    Args:
        rational: Tuple of (numerator, denominator) pairs for degrees, minutes, seconds
        
    Returns:
        Decimal degree value
        
    Raises:
        ValueError: If rational format is invalid or contains zero denominators
    """
    if not rational or len(rational) != 3:
        raise ValueError(f"Invalid GPS rational format: expected 3 elements, got {len(rational) if rational else 0}")
    
    # Validate denominators are not zero
    for i, (num, denom) in enumerate(rational):
        if denom == 0:
            raise ValueError(f"Invalid GPS rational: zero denominator at position {i}")
    
    degrees = rational[0][0] / rational[0][1]
    minutes = rational[1][0] / rational[1][1]
    seconds = rational[2][0] / rational[2][1]
    
    # Constants for clarity
    MINUTES_PER_DEGREE = 60.0
    SECONDS_PER_DEGREE = 3600.0
    
    return degrees + (minutes / MINUTES_PER_DEGREE) + (seconds / SECONDS_PER_DEGREE)


def decimal_to_dms(decimal: float, is_latitude: bool) -> str:
    """
    Convert decimal degrees to human-readable degrees, minutes, seconds format.
    
    Args:
        decimal: Decimal degree value
        is_latitude: True for latitude (N/S), False for longitude (E/W)
        
    Returns:
        Human-readable coordinate string (e.g., "40°42'46\"N")
    """
    is_positive = decimal >= 0
    decimal = abs(decimal)
    
    degrees = int(decimal)
    minutes_decimal = (decimal - degrees) * 60
    minutes = int(minutes_decimal)
    seconds = int((minutes_decimal - minutes) * 60)
    
    if is_latitude:
        direction = 'N' if is_positive else 'S'
    else:
        direction = 'E' if is_positive else 'W'
    
    return f"{degrees}°{minutes}'{seconds}\"{direction}"


def extract_exif_data(image_path: str) -> dict:
    """
    Extract EXIF metadata from a JPG image.
    
    Args:
        image_path: Path to the JPG image file
        
    Returns:
        Dictionary containing:
        - 'datetime': Date and time string (or None)
        - 'location': Human-readable GPS coordinates (or None)
    """
    result = {
        'datetime': None,
        'location': None
    }
    
    try:
        exif_dict = piexif.load(image_path)
        
        # Extract DateTime
        if '0th' in exif_dict and piexif.ImageIFD.DateTime in exif_dict['0th']:
            try:
                datetime_bytes = exif_dict['0th'][piexif.ImageIFD.DateTime]
                # Try UTF-8 first, with fallback to latin-1
                try:
                    result['datetime'] = datetime_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    result['datetime'] = datetime_bytes.decode('latin-1', errors='replace')
                    logging.debug(f"Used latin-1 encoding for datetime in {image_path}")
            except (AttributeError, UnicodeDecodeError) as e:
                logging.warning(f"Could not decode datetime from {image_path}: {e}")
        
        # Extract GPS coordinates
        if 'GPS' in exif_dict:
            gps_data = exif_dict['GPS']
            
            # Check if we have all required GPS fields
            has_lat = piexif.GPSIFD.GPSLatitude in gps_data and piexif.GPSIFD.GPSLatitudeRef in gps_data
            has_lon = piexif.GPSIFD.GPSLongitude in gps_data and piexif.GPSIFD.GPSLongitudeRef in gps_data
            
            if has_lat and has_lon:
                try:
                    # Get latitude
                    lat_rational = gps_data[piexif.GPSIFD.GPSLatitude]
                    lat_ref_bytes = gps_data[piexif.GPSIFD.GPSLatitudeRef]
                    
                    # Decode latitude reference with error handling
                    try:
                        lat_ref = lat_ref_bytes.decode('utf-8')
                    except (AttributeError, UnicodeDecodeError):
                        lat_ref = lat_ref_bytes.decode('latin-1', errors='replace')
                    
                    lat_decimal = rational_to_decimal(lat_rational)
                    if lat_ref == 'S':
                        lat_decimal *= -1
                    
                    # Get longitude
                    lon_rational = gps_data[piexif.GPSIFD.GPSLongitude]
                    lon_ref_bytes = gps_data[piexif.GPSIFD.GPSLongitudeRef]
                    
                    # Decode longitude reference with error handling
                    try:
                        lon_ref = lon_ref_bytes.decode('utf-8')
                    except (AttributeError, UnicodeDecodeError):
                        lon_ref = lon_ref_bytes.decode('latin-1', errors='replace')
                    
                    lon_decimal = rational_to_decimal(lon_rational)
                    if lon_ref == 'W':
                        lon_decimal *= -1
                    
                    # Convert to human-readable format
                    lat_str = decimal_to_dms(lat_decimal, is_latitude=True)
                    lon_str = decimal_to_dms(lon_decimal, is_latitude=False)
                    result['location'] = f"{lat_str}, {lon_str}"
                    
                except ValueError as e:
                    logging.warning(f"Invalid GPS data in {image_path}: {e}")
                except (KeyError, IndexError, ZeroDivisionError) as e:
                    logging.warning(f"Error parsing GPS coordinates from {image_path}: {e}")
    
    except piexif.InvalidImageDataError as e:
        # Specific exception for invalid/corrupted EXIF data
        logging.warning(f"Invalid or corrupted EXIF data in {image_path}: {e}")
    except FileNotFoundError as e:
        logging.error(f"Image file not found: {image_path}")
    except (OSError, IOError) as e:
        logging.warning(f"Could not read file {image_path}: {e}")
    except Exception as e:
        # Catch any other unexpected exceptions
        logging.warning(f"Unexpected error reading EXIF from {image_path}: {e}")
    
    return result

