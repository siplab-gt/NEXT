import next.utils as utils
import numpy as np
from typing import Dict, Any, List, Tuple
import random
from apps.PAQ.algs.ColorVision.paq_model import *

class MyAlg:
    def initExp(self, butler, referenceItems, 
                directionalItems, tickFlag, tickNum, queryType): 
        # butler.algorithms.set(key='startItems', value=startItems)
        # butler.algorithms.set(key='endItems', value=endItems)
        butler.algorithms.set(key='referenceItems', value=referenceItems)
        butler.algorithms.set(key='directionalItems', value=directionalItems)
        butler.algorithms.set(key='targetItems', value=list())
        butler.algorithms.set(key='tickFlag', value=tickFlag)
        butler.algorithms.set(key='tickNum', value=tickNum)
        butler.algorithms.set(key='queryType', value=queryType)
        butler.algorithms.set(key='num_reported_answers', value=0)
        butler.algorithms.set(key='ticks', value=list())
        return True


    def getQuery(self, butler, ref, start, end, query_id):
        # prepare query
        ticknum = butler.algorithms.get(key='tickNum')
        tickFlag = butler.algorithms.get(key='tickFlag')
        queryType = butler.algorithms.get(key='queryType')
        
        # Get the items
        referenceItem = butler.algorithms.get(key='referenceItems')[query_id]
        directionalItem = butler.algorithms.get(key='directionalItems')[query_id]
        
        # Convert to numpy arrays for calculations
        # referenceItem is already [x, y] in xyY space
        ref_xy = np.array(referenceItem)  # [x, y]
        direction_xy = np.array(directionalItem)  # [x, y] direction in xyY space
        
        # Extract x, y from referenceItem and set Y=0.5
        ref_x = ref_xy[0]
        ref_y = ref_xy[1]
        ref_Y = 0.5  # Set luminance to 0.5
        
        # Generate new colors if needed
        if query_id >= len(butler.algorithms.get(key='targetItems')):
            # Step 1: Generate unit vector from directionalItems (already in xyY space)
            direction_norm = np.linalg.norm(direction_xy)
            if direction_norm > 1e-10:
                xy_unit_vector = direction_xy / direction_norm
            else:
                # If no direction, use a default direction
                xy_unit_vector = np.array([1.0, 0.0])
            
            # Step 2: Find bounds for x and y chromaticity coordinates
            # x and y must be positive and x + y <= 1 (within the chromaticity diagram)
            # Also ensure x, y > 0 for valid colors
            xy_bounds = {
                'x': (0.001, 0.999),  # x chromaticity bounds (avoid 0 to prevent division issues)
                'y': (0.001, 0.999),  # y chromaticity bounds
                'Y': (0.5, 0.5)     # Fixed luminance
            }
            
            # Find the maximum distance we can travel in both positive and negative directions
            max_positive_distance = float('inf')
            max_negative_distance = float('-inf')
            
            for i, component in enumerate(['x', 'y']):
                if abs(xy_unit_vector[i]) > 1e-10:  # Avoid division by zero
                    # Calculate how far we can go in positive direction
                    pos_dist = (xy_bounds[component][1] - [ref_x, ref_y][i]) / xy_unit_vector[i]
                    if pos_dist >= 0:
                        max_positive_distance = min(max_positive_distance, pos_dist)
                    
                    # Calculate how far we can go in negative direction
                    neg_dist = (xy_bounds[component][0] - [ref_x, ref_y][i]) / xy_unit_vector[i]
                    if neg_dist <= 0:
                        max_negative_distance = max(max_negative_distance, neg_dist)
            
            # Additional constraint: x + y <= 1
            if abs(xy_unit_vector[0] + xy_unit_vector[1]) > 1e-10:
                # Calculate distance to x + y = 1 boundary
                boundary_dist = (1.0 - ref_x - ref_y) / (xy_unit_vector[0] + xy_unit_vector[1])
                if boundary_dist >= 0:
                    max_positive_distance = min(max_positive_distance, boundary_dist)
                else:
                    max_negative_distance = max(max_negative_distance, boundary_dist)
            
            # Ensure we have finite bounds
            if max_positive_distance == float('inf'):
                max_positive_distance = 0.1
            if max_negative_distance == float('-inf'):
                max_negative_distance = -0.1
            
            # Step 4: Randomly extract a segment that contains the reference color
            # The reference color is at distance 0 along the direction
            # Simply pick a left point in (min, ref) and a right point in [ref, max)
            segment_start_dist = random.uniform(max_negative_distance, 0)  # Left point in (min, ref)
            segment_end_dist = random.uniform(0, max_positive_distance)    # Right point in [ref, max)
            
            # Step 5: Generate ticknum evenly spaced colors along the segment
            distances = np.linspace(segment_start_dist, segment_end_dist, ticknum)
            
            new_colors = []
            ticks = []
            hex_colors = []
            
            for i, distance in enumerate(distances):
                # Calculate xyY color at this distance along the direction
                color_x = ref_x + distance * xy_unit_vector[0]
                color_y = ref_y + distance * xy_unit_vector[1]
                color_Y = 0.5  # Fixed luminance
                
                # Ensure the color is within bounds
                color_x = np.clip(color_x, xy_bounds['x'][0], xy_bounds['x'][1])
                color_y = np.clip(color_y, xy_bounds['y'][0], xy_bounds['y'][1])
                
                # Ensure x + y <= 1
                if color_x + color_y > 1.0:
                    # Normalize to boundary
                    scale = 1.0 / (color_x + color_y)
                    color_x *= scale
                    color_y *= scale
                
                # Convert xyY to XYZ for hex conversion
                # Y = Y (luminance)
                # X = (x/y) * Y
                # Z = ((1-x-y)/y) * Y
                if color_y > 1e-10:  # Avoid division by zero
                    color_X = (color_x / color_y) * color_Y
                    color_Z = ((1 - color_x - color_y) / color_y) * color_Y
                else:
                    # Fallback to reference color if y is too small
                    color_X = ref_x * color_Y / ref_y if ref_y > 1e-10 else 0
                    color_Z = ((1 - ref_x - ref_y) / ref_y) * color_Y if ref_y > 1e-10 else 0
                
                color_xyz = np.array([color_X, color_Y, color_Z])
                new_colors.append(color_xyz)
                
                # Calculate tick value (distance from reference)
                tick_value = distance
                ticks.append(str(np.abs(tick_value)))
                
                # Convert XYZ to hex color
                xyz_color = XYZColor(color_xyz[0], color_xyz[1], color_xyz[2])
                hex_color = XYZ_to_hex(xyz_color)
                hex_colors.append(hex_color)
            
            # Cache the new colors and ticks
            butler.algorithms.append(key='targetItems', value=hex_colors)
            butler.algorithms.append(key='ticks', value=ticks)
        else:
            # Use cached values
            hex_colors = butler.algorithms.get(key='targetItems')[query_id]
            ticks = butler.algorithms.get(key='ticks')[query_id]
        
        # Convert reference xyY to XYZ then to hex color
        if ref_y > 1e-10:  # Avoid division by zero
            ref_X = (ref_x / ref_y) * ref_Y
            ref_Z = ((1 - ref_x - ref_y) / ref_y) * ref_Y
        else:
            ref_X = 0
            ref_Z = 0
        
        ref_xyz_color = XYZColor(ref_X, ref_Y, ref_Z)
        ref_hex_color = XYZ_to_hex(ref_xyz_color)
       
        return {
            'referenceItem': ref_hex_color,  
            'targetItems': hex_colors, 
            'tickItems': ticks, 
            'tickFlag': tickFlag,
            'queryType': queryType,
            'tickType': 'text'
        }

    def processAnswer(self, butler, answer):
        # to be implemented
        return True

    def getModel(self, butler):
        return butler.algorithms.get(key=['num_reported_answers'])

    def incremental_embedding_update(self, butler, args):
        # to be implemented
        pass

    def full_embedding_update(self, butler, args):
        # to be implemented
        pass

  