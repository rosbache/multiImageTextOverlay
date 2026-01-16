"""
EXIF Metadata Extraction Module

Extracts DateTime and GPS location data from JPG image EXIF metadata.
"""

import piexif
from typing import Optional, Tuple


def rational_to_decimal(rational: Tuple[Tuple[int, int], ...]) -> float:
    """
    Convert GPS rational coordinates to decimal degrees.
    
    Args:
        rational: Tuple of (numerator, denominator) pairs for degrees, minutes, seconds
        
    Returns:
        Decimal degree value
    """
    degrees = rational[0][0] / rational[0][1]
    minutes = rational[1][0] / rational[1][1]
    seconds = rational[2][0] / rational[2][1]
    
    return degrees + (minutes / 60.0) + (seconds / 3600.0)


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
            datetime_bytes = exif_dict['0th'][piexif.ImageIFD.DateTime]
            result['datetime'] = datetime_bytes.decode('utf-8')
        
        # Extract GPS coordinates
        if 'GPS' in exif_dict:
            gps_data = exif_dict['GPS']
            
            # Check if we have all required GPS fields
            has_lat = piexif.GPSIFD.GPSLatitude in gps_data and piexif.GPSIFD.GPSLatitudeRef in gps_data
            has_lon = piexif.GPSIFD.GPSLongitude in gps_data and piexif.GPSIFD.GPSLongitudeRef in gps_data
            
            if has_lat and has_lon:
                # Get latitude
                lat_rational = gps_data[piexif.GPSIFD.GPSLatitude]
                lat_ref = gps_data[piexif.GPSIFD.GPSLatitudeRef].decode('utf-8')
                lat_decimal = rational_to_decimal(lat_rational)
                if lat_ref == 'S':
                    lat_decimal *= -1
                
                # Get longitude
                lon_rational = gps_data[piexif.GPSIFD.GPSLongitude]
                lon_ref = gps_data[piexif.GPSIFD.GPSLongitudeRef].decode('utf-8')
                lon_decimal = rational_to_decimal(lon_rational)
                if lon_ref == 'W':
                    lon_decimal *= -1
                
                # Convert to human-readable format
                lat_str = decimal_to_dms(lat_decimal, is_latitude=True)
                lon_str = decimal_to_dms(lon_decimal, is_latitude=False)
                result['location'] = f"{lat_str}, {lon_str}"
    
    except Exception as e:
        # If there's any error reading EXIF, return empty result
        print(f"Warning: Could not read EXIF data from {image_path}: {e}")
    
    return result
