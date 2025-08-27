import numpy as np
from colormath.color_objects import sRGBColor, XYZColor
from colormath.color_conversions import convert_color

def hex_to_XYZ(hex_color, luminance=0.5):
    """
    Convert hex color code to XYZ color space with specified luminance.
    
    Parameters:
    - hex_color: str, hex color code (e.g. '#FFFFFF')
    - luminance: float, target luminance (default 0.5)
    
    Returns:
    - XYZColor object
    """
    # Convert hex to RGB
    rgb = sRGBColor.new_from_rgb_hex(hex_color)
    # Convert RGB to XYZ
    xyz = convert_color(rgb, XYZColor)
    # Scale to match the target luminance (Y component in XYZ)
    current_luminance = xyz.xyz_y
    if current_luminance > 0:
        scale = luminance / current_luminance
        xyz.xyz_x *= scale
        xyz.xyz_y *= scale
        xyz.xyz_z *= scale
    return xyz

def generate_unit_vector(start, end):
    """
    Generate a unit vector in XYZ color space from the difference between start and end colors.
    The vector is normalized and represents the direction from start to end color.
    
    Parameters:
    - start: np.ndarray or list, XYZ color values [X, Y, Z] of the start color
    - end: np.ndarray or list, XYZ color values [X, Y, Z] of the end color
    
    Returns:
    - np.ndarray, unit vector in XYZ space representing the direction from start to end
    """
    # Convert inputs to numpy arrays if they aren't already
    start = np.array(start)
    end = np.array(end)
    
    # Calculate the difference vector
    diff_vector = end - start
    
    # Check if the vector is non-zero
    norm = np.linalg.norm(diff_vector)
    if norm == 0:
        # If start and end are the same, return a default direction
        return np.array([1.0, 0.0, 0.0])
    
    # Normalize the vector to unit length
    unit_vector = diff_vector / norm
    
    return unit_vector

def XYZ_to_hex(xyz_color):
    """
    Convert XYZColor object to hex color string.
    
    Parameters:
    - xyz_color: XYZColor object
    
    Returns:
    - str, hex color code (e.g. '#FFFFFF')
    """
    try:
        # Convert XYZ to RGB
        rgb = convert_color(xyz_color, sRGBColor, target_illuminant='d65')
        # Ensure RGB values are in valid range
        rgb.rgb_r = max(0, min(1, rgb.rgb_r))
        rgb.rgb_g = max(0, min(1, rgb.rgb_g))
        rgb.rgb_b = max(0, min(1, rgb.rgb_b))
        # Convert RGB to hex
        return rgb.get_rgb_hex()
    except Exception as e:
        # If conversion fails, return a fallback color
        print(f"Color conversion error: {e}")
        return "#FFFFFF"

def get_new_color(start, end, ticknum=10):
    """
    Generate a sequence of evenly spaced colors in XYZ color space between start and end colors.
    
    Parameters:
    - start: np.ndarray or list, XYZ color values [X, Y, Z] of the start color
    - end: np.ndarray or list, XYZ color values [X, Y, Z] of the end color
    - ticknum: int, number of colors to generate (default 10)
    
    Returns:
    - list of np.ndarray, each containing XYZ color values [X, Y, Z]
    """
    # Convert inputs to numpy arrays if they aren't already
    start = np.array(start)
    end = np.array(end)
    
    # Generate evenly spaced points between start and end
    # We use linspace to create ticknum points including both start and end
    colors = []
    for i in range(3):  # For each X, Y, Z component
        component_values = np.linspace(start[i], end[i], ticknum)
        colors.append(component_values)
    
    # Transpose to get list of [X,Y,Z] arrays
    result = np.array(colors).T
    
    # Ensure all values are non-negative (XYZ values can be greater than 1)
    result = np.clip(result, 0, None)
    
    return result.tolist()  # Convert to list of lists for easier handling