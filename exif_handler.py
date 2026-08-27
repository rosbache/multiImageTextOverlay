"""
EXIF Metadata Extraction Module

Extracts capture time and GPS metadata from JPG image EXIF metadata.
"""

import time
import piexif
import logging
from typing import Optional, Tuple, Dict
from pyproj import Transformer
import config

# Cache for coordinate transformers (one per process)
_transformer_cache: Dict[int, Transformer] = {}

# Cache for geocoding results (avoids duplicate requests for the same coordinates)
_geocode_cache: Dict[Tuple[float, float], Optional[str]] = {}
_last_geocode_time: float = 0.0
_nominatim_geocoder = None


def _get_geocoder():
    """Get or create a cached Nominatim geocoder instance."""
    global _nominatim_geocoder
    if _nominatim_geocoder is None:
        from geopy.geocoders import Nominatim
        _nominatim_geocoder = Nominatim(user_agent="multiImageTextOverlay")
    return _nominatim_geocoder


def reverse_geocode(lat: float, lon: float, timeout: int = 5) -> Optional[str]:
    """
    Reverse geocode coordinates to a street + city address string.
    Uses an in-memory cache and respects Nominatim's 1 req/sec rate limit.

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        timeout: Request timeout in seconds

    Returns:
        Address string ("Street N, City") or None if geocoding fails
    """
    global _last_geocode_time

    key = (round(lat, 6), round(lon, 6))
    if key in _geocode_cache:
        logging.debug(f"Geocode cache hit for {key}")
        return _geocode_cache[key]

    # Rate limit: 1 request per second (Nominatim usage policy)
    elapsed = time.time() - _last_geocode_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    try:
        geocoder = _get_geocoder()
        location = geocoder.reverse((lat, lon), timeout=timeout)
        _last_geocode_time = time.time()

        address = None
        if location:
            raw = location.raw.get('address', {})
            road = (raw.get('road') or raw.get('pedestrian') or
                    raw.get('path') or raw.get('cycleway') or raw.get('footway'))
            house_number = raw.get('house_number', '')
            city = (raw.get('city') or raw.get('town') or
                    raw.get('village') or raw.get('municipality') or raw.get('county'))
            parts = []
            if road:
                parts.append(f"{road} {house_number}".strip() if house_number else road)
            if city:
                parts.append(city)
            address = ', '.join(parts) if parts else None

        _geocode_cache[key] = address
        logging.debug(f"Geocoded ({lat:.5f}, {lon:.5f}) -> {address}")
        return address

    except Exception as e:
        logging.warning(f"Geocoding failed for ({lat:.5f}, {lon:.5f}): {e}")
        _geocode_cache[key] = None
        return None


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


def decimal_to_rational(decimal: float) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
    """
    Convert decimal degrees to GPS rational format (degrees, minutes, seconds).
    
    Args:
        decimal: Decimal degree value (can be negative)
        
    Returns:
        Tuple of 3 (numerator, denominator) pairs for degrees, minutes, seconds
    """
    # Work with absolute value; sign is handled by lat/lon reference
    decimal = abs(decimal)
    
    degrees = int(decimal)
    minutes_decimal = (decimal - degrees) * 60
    minutes = int(minutes_decimal)
    seconds_decimal = (minutes_decimal - minutes) * 60
    
    # Use high precision for seconds (1000000 parts)
    seconds_numerator = int(seconds_decimal * 1000000)
    seconds_denominator = 1000000
    
    return (
        (degrees, 1),
        (minutes, 1),
        (seconds_numerator, seconds_denominator)
    )


def validate_coordinates(lat: float, lon: float) -> bool:
    """
    Validate latitude and longitude are within valid ranges.
    
    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        
    Returns:
        True if coordinates are valid, False otherwise
    """
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


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


def _decode_exif_text(value) -> str:
    """
    Decode EXIF text values with UTF-8 fallback to latin-1.

    Args:
        value: EXIF value as bytes or string

    Returns:
        Decoded string value
    """
    if isinstance(value, str):
        return value
    try:
        return value.decode('utf-8')
    except UnicodeDecodeError:
        return value.decode('latin-1', errors='replace')


def _parse_rational_value(value) -> float:
    """
    Convert a rational EXIF value to float.

    Args:
        value: EXIF rational tuple or numeric value

    Returns:
        Parsed float value
    """
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        if denominator == 0:
            raise ZeroDivisionError("EXIF rational denominator cannot be zero")
        return numerator / denominator
    return float(value)


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
        - 'datetime': Capture date and time string, preferring DateTimeOriginal (or None)
        - 'location': Human-readable GPS coordinates (or None)
        - 'altitude': Altitude in meters (or None)
        - 'direction': Image direction in degrees (or None)
        - 'gps_accuracy': GPS positioning accuracy in meters (or None)
    """
    result = {
        'filename': filename,
        'datetime': None,
        'location': None,
        'altitude': None,
        'direction': None,
        'gps_accuracy': None,
        '_lat_decimal': None,
        '_lon_decimal': None,
    }
    
    try:
        exif_dict = piexif.load(image_path)
        
        # Extract capture time, preferring DateTimeOriginal over the generic DateTime
        datetime_value = None
        if 'Exif' in exif_dict and piexif.ExifIFD.DateTimeOriginal in exif_dict['Exif']:
            datetime_value = exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal]
        elif '0th' in exif_dict and piexif.ImageIFD.DateTime in exif_dict['0th']:
            datetime_value = exif_dict['0th'][piexif.ImageIFD.DateTime]

        if datetime_value is not None:
            try:
                result['datetime'] = _decode_exif_text(datetime_value)
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
                    result['_lat_decimal'] = lat_decimal
                    result['_lon_decimal'] = lon_decimal
                    
                    # Extract GPS altitude if available
                    if piexif.GPSIFD.GPSAltitude in gps_data:
                        try:
                            altitude_rational = gps_data[piexif.GPSIFD.GPSAltitude]
                            altitude_ref = gps_data.get(piexif.GPSIFD.GPSAltitudeRef, 0)
                            
                            altitude = _parse_rational_value(altitude_rational)
                            
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
                            
                            direction = _parse_rational_value(direction_rational)
                            
                            # Direction ref can be 'T' (True North) or 'M' (Magnetic North)
                            # We'll use the value as-is since most devices use True North
                            result['direction'] = direction
                            logging.debug(f"Extracted direction: {direction}° from {image_path}")
                        except (ValueError, ZeroDivisionError, TypeError) as e:
                            logging.debug(f"Could not parse direction from {image_path}: {e}")

                    # Extract GPS horizontal positioning accuracy if available
                    if piexif.GPSIFD.GPSHPositioningError in gps_data:
                        try:
                            result['gps_accuracy'] = _parse_rational_value(
                                gps_data[piexif.GPSIFD.GPSHPositioningError]
                            )
                        except (ValueError, ZeroDivisionError, TypeError) as e:
                            logging.debug(f"Could not parse GPS accuracy from {image_path}: {e}")
                    
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


def write_gps_to_exif(image_path: str, lat: float, lon: float, altitude: Optional[float] = None) -> bool:
    """
    Write GPS coordinates to image EXIF data, preserving other metadata.
    
    Args:
        image_path: Path to the JPG image file
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        altitude: Optional altitude in meters above sea level
        
    Returns:
        True if write was successful, False otherwise
    """
    if not validate_coordinates(lat, lon):
        logging.error(f"Invalid coordinates for {image_path}: lat={lat}, lon={lon}")
        return False
    
    try:
        # Load existing EXIF data
        try:
            exif_dict = piexif.load(image_path)
        except piexif.InvalidImageDataError:
            # No EXIF data exists, create new dict
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            logging.debug(f"No existing EXIF in {image_path}, creating new data")
        
        # Ensure GPS IFD exists
        if "GPS" not in exif_dict or exif_dict["GPS"] is None:
            exif_dict["GPS"] = {}
        
        # Convert latitude
        lat_rational = decimal_to_rational(lat)
        lat_ref = b'N' if lat >= 0 else b'S'
        
        # Convert longitude
        lon_rational = decimal_to_rational(lon)
        lon_ref = b'E' if lon >= 0 else b'W'
        
        # Update GPS fields
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = lat_rational
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = lon_rational
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
        
        # Update altitude if provided
        if altitude is not None:
            altitude_ref = 0 if altitude >= 0 else 1
            altitude_abs = abs(altitude)
            # Use high precision for altitude (1000000 parts)
            altitude_rational = (int(altitude_abs * 1000000), 1000000)
            exif_dict["GPS"][piexif.GPSIFD.GPSAltitude] = altitude_rational
            exif_dict["GPS"][piexif.GPSIFD.GPSAltitudeRef] = altitude_ref
        
        # Dump and write EXIF
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, image_path)
        
        logging.info(f"Updated GPS in {image_path}: ({lat:.6f}, {lon:.6f})")
        return True
        
    except piexif.InvalidImageDataError as e:
        logging.error(f"Invalid image data when writing GPS to {image_path}: {e}")
        return False
    except FileNotFoundError:
        logging.error(f"Image file not found: {image_path}")
        return False
    except (OSError, IOError) as e:
        logging.error(f"Could not write to {image_path}: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error writing GPS to {image_path}: {e}")
        return False
