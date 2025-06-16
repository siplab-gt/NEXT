import next.utils as utils
import numpy as np
from typing import Dict, Any, List, Tuple
import random
from apps.PAQ_any.algs.ColorVision.paq_model import *

class MyAlg:
    def initExp(self, butler, startItems, referenceItems, endItems, tickFlag, tickNum, queryType): 
        butler.algorithms.set(key='startItems', value=startItems)
        butler.algorithms.set(key='referenceItems', value=referenceItems)
        butler.algorithms.set(key='endItems', value=endItems)
        butler.algorithms.set(key='targetItems', value=list())
        butler.algorithms.set(key='tickFlag', value=tickFlag)
        butler.algorithms.set(key='tickNum', value=tickNum)
        butler.algorithms.set(key='queryType', value=queryType)
        butler.algorithms.set(key='num_reported_answers', value=0)
        butler.algorithms.set(key='ticks', value=list())
        return True


    def getQuery(self, butler, source, query_id):
        # prepare query
        ticknum = butler.algorithms.get(key='tickNum')
        tickFlag = butler.algorithms.get(key='tickFlag')
        # Get the hex color from alt_description if source is a target item
        startItem = butler.algorithms.get(key='startItems')[query_id]
        referenceItem = butler.algorithms.get(key='referenceItems')[query_id]
        endItem = butler.algorithms.get(key='endItems')[query_id]
        
        # Convert to numpy arrays for calculations
        start_xyz = np.array(startItem)
        end_xyz = np.array(endItem)
        ref_xyz = np.array(referenceItem)
        
        # Check if reference point is between start and end
        direction = end_xyz - start_xyz
        ref_to_start = ref_xyz - start_xyz
        ref_to_end = ref_xyz - end_xyz
        
        # Project reference point onto the line
        t = np.dot(ref_to_start, direction) / np.dot(direction, direction)
        
        # Check if projection is within [0,1] and if reference point is close to the line
        if not (0 <= t <= 1):
            raise ValueError("Reference point must be between start and end points")
            
        # Calculate distance from reference point to the line
        projection = start_xyz + t * direction
        distance = np.linalg.norm(ref_xyz - projection)
        
        # Generate new colors if needed
        if query_id >= len(butler.algorithms.get(key='targetItems')):
            new_colors = get_new_color(startItem, endItem, ticknum)
            unit_vector = generate_unit_vector(start_xyz, end_xyz)
            
            # Calculate ticks based on color differences
            ticks = []
            hex_colors = []
            for color in new_colors:
                color_xyz = np.array(color)
                # Calculate difference vector from reference
                delta = color_xyz - ref_xyz
                tick_value = np.dot(delta, unit_vector)
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
        
        # Convert reference XYZ to hex color
        ref_xyz_color = XYZColor(ref_xyz[0], ref_xyz[1], ref_xyz[2])
        ref_hex_color = XYZ_to_hex(ref_xyz_color)
       
        return {
            'referenceItem': ref_hex_color,  
            'targetItems': hex_colors, 
            'tickItems': ticks, 
            'tickFlag': tickFlag,
            'queryType': 'color',
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

  