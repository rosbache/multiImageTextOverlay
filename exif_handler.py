"""
EXIF Metadata Extraction Module

Extracts DateTime and GPS location data from JPG image EXIF metadata.
"""

import piexif
import logging
from typing import Optional, Tuple, Dict
from pyproj import Transformer
import config

# Cache for coordinate transformers (one per process)
_transformer_cache: Dict[int, Transformer] = {}


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


def degrees_to_cardinal(degrees: float, precision: int = 8) -> str:
    """
    Convert degrees (0-360) to cardinal/intercardinal direction.
    
    Args:
        degrees: Direction in degrees (0-360, where 0/360 is North)
        precision: Number of direction sectors (8 or 16)
                   8 = N, NE, E, SE, S, SW, W, NW
                   16 = N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW
        
    Returns:
        Cardinal/intercardinal direction string
    """
    # Normalize degrees to 0-360 range
    degrees = degrees % 360
    
    if precision == 16:
        # 16-sector compass (22.5° per sector)
        directions = [
            'N', 'NNE', 'NE', 'ENE',
            'E', 'ESE', 'SE', 'SSE',
            'S', 'SSW', 'SW', 'WSW',
            'W', 'WNW', 'NW', 'NNW'
        ]
        sector_size = 360 / 16
        index = int((degrees + sector_size / 2) % 360 / sector_size)
    else:
        # 8-sector compass (45° per sector) - default
        directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        sector_size = 360 / 8
        index = int((degrees + sector_size / 2) % 360 / sector_size)
    
    return directions[index]


def get_transformer(target_epsg: int) -> Transformer:
    """
    Get or create a cached coordinate transformer.
    Uses a cache to avoid recreating transformers for each image.
    
    Args:
        target_epsg: Target EPSG code
        
    Returns:
        Transformer object for WGS84 to target CRS
    """
    if target_epsg not in _transformer_cache:
        _transformer_cache[target_epsg] = Transformer.from_crs(
            "EPSG:4326",  # WGS84 (GPS standard)
            f"EPSG:{target_epsg}",
            always_xy=True  # Ensure longitude, latitude order
        )
        logging.debug(f"Created transformer for EPSG:{target_epsg}")
    return _transformer_cache[target_epsg]


def transform_to_utm(lat_decimal: float, lon_decimal: float, target_epsg: int) -> Tuple[float, float]:
    """
    Transform WGS84 coordinates to target coordinate system.
    
    Args:
        lat_decimal: Latitude in decimal degrees (WGS84)
        lon_decimal: Longitude in decimal degrees (WGS84)
        target_epsg: Target EPSG code
        
    Returns:
        Tuple of (easting, northing) in target coordinate system
    """
    transformer = get_transformer(target_epsg)
    # Transform: lon, lat (X, Y) -> easting, northing
    easting, northing = transformer.transform(lon_decimal, lat_decimal)
    return easting, northing


def format_utm_coordinates(easting: float, northing: float, zone: int, hemisphere: str) -> str:
    """
    Format UTM coordinates for display.
    
    Args:
        easting: UTM easting coordinate
        northing: UTM northing coordinate
        zone: UTM zone number
        hemisphere: 'N' or 'S'
        
    Returns:
        Formatted UTM coordinate string
    """
    return f"UTM {zone}{hemisphere}: {easting:.2f}E, {northing:.2f}N"


def extract_exif_data(image_path: str, filename: str = None) -> dict:
    """
    Extract EXIF metadata from a JPG image.
    
    Args:
        image_path: Path to the JPG image file
        filename: Filename to include in metadata (optional)
        
    Returns:
        Dictionary containing:
        - 'filename': Filename (or None)
        - 'datetime': Date and time string (or None)
        - 'location': Human-readable GPS coordinates (or None)
        - 'altitude': Altitude in meters (or None)
        - 'direction': Image direction in degrees (or None)
    """
    result = {
        'filename': filename,
        'datetime': None,
        'location': None,
        'altitude': None,
        'direction': None
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
                    
                    # Extract GPS altitude if available
                    if piexif.GPSIFD.GPSAltitude in gps_data:
                        try:
                            altitude_rational = gps_data[piexif.GPSIFD.GPSAltitude]
                            altitude_ref = gps_data.get(piexif.GPSIFD.GPSAltitudeRef, 0)
                            
                            # Convert rational to float
                            if isinstance(altitude_rational, tuple) and len(altitude_rational) == 2:
                                altitude = altitude_rational[0] / altitude_rational[1]
                            else:
                                altitude = float(altitude_rational)
                            
                            # Apply altitude reference (0 = above sea level, 1 = below sea level)
                            if altitude_ref == 1:
                                altitude *= -1
                            
                            result['altitude'] = altitude
                        except (ValueError, ZeroDivisionError, TypeError) as e:
                            logging.debug(f"Could not parse altitude from {image_path}: {e}")
                    
                    # Extract GPS image direction if available
                    if piexif.GPSIFD.GPSImgDirection in gps_data:
                        try:
                            direction_rational = gps_data[piexif.GPSIFD.GPSImgDirection]
                            direction_ref = gps_data.get(piexif.GPSIFD.GPSImgDirectionRef, b'T')
                            
                            # Convert rational to float
                            if isinstance(direction_rational, tuple) and len(direction_rational) == 2:
                                direction = direction_rational[0] / direction_rational[1]
                            else:
                                direction = float(direction_rational)
                            
                            # Direction ref can be 'T' (True North) or 'M' (Magnetic North)
                            # We'll use the value as-is since most devices use True North
                            result['direction'] = direction
                            logging.debug(f"Extracted direction: {direction}° from {image_path}")
                        except (ValueError, ZeroDivisionError, TypeError) as e:
                            logging.debug(f"Could not parse direction from {image_path}: {e}")
                    
                    # Transform to UTM if enabled
                    if config.SHOW_UTM_COORDINATES:
                        try:
                            easting, northing = transform_to_utm(
                                lat_decimal, lon_decimal, config.TARGET_EPSG
                            )
                            result['location_utm'] = format_utm_coordinates(
                                easting, northing, config.UTM_ZONE, config.UTM_HEMISPHERE
                            )
                        except Exception as e:
                            logging.warning(f"Failed to transform coordinates for {image_path}: {e}")
                            result['location_utm'] = None
                    
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

