import numpy as np
from typing import Dict, Any, List, Tuple
import random
import base64
import gc
import time
import os
from PIL import Image
import io
import requests

class MyAlg:
    def initExp(self, butler, startItems, referenceItems, 
                endItems, tickFlag, tickNum, queryType):  
        butler.algorithms.set(key='startItems', value=startItems)
        butler.algorithms.set(key='referenceItems', value=referenceItems)
        butler.algorithms.set(key='endItems', value=endItems)
        butler.algorithms.set(key='tickFlag', value=tickFlag)
        butler.algorithms.set(key='tickNum', value=tickNum)
        butler.algorithms.set(key='num_reported_answers', value=0) 
        butler.algorithms.set(key='ticks', value=list())
        butler.algorithms.set(key='queryType', value=queryType)
        # Initialize storage for morphed images
        butler.algorithms.set(key='postProcessReferenceItems', value=list())
        butler.algorithms.set(key='targetItems', value=list())
        return True

    def getQuery(self, butler, ref, start, end, query_id):
        # Load start and end images
        start_image = self.load_image(start)
        end_image = self.load_image(end)
        ref_image = self.load_image(ref)
        if (len(butler.algorithms.get(key='targetItems')) <= query_id):
            # Generate morphed reference (interpolation between start and end)
            # morph_level = random.random()  # Random value between 0 and 1
            # morphed_ref = self.interpolate_images(start_image, end_image, morph_level)
            # Convert reference image to base64 for consistency
            ref_base64 = self.image_to_base64(ref_image)
            butler.algorithms.append(key='postProcessReferenceItems', value=ref_base64)
            
            # Generate target images and ticks
            targets, ticks = self.interpolate(start_image, end_image, butler.algorithms.get(key='tickNum'))
            butler.algorithms.append(key='targetItems', value=targets)
            butler.algorithms.append(key='ticks', value=ticks)
        
        return {'referenceItem': butler.algorithms.get(key='postProcessReferenceItems')[query_id], 
                'targetItems': butler.algorithms.get(key='targetItems')[query_id], 
                'tickItems': butler.algorithms.get(key='ticks')[query_id], 
                'tickFlag': butler.algorithms.get(key='tickFlag'),
                'queryType': 'image',
                'tickType': 'text'}

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

    def load_image(self, image_path: str) -> np.ndarray:
        """
        Load an image file and convert to numpy array.
        Supports both local file paths and URLs.
        
        Args:
            image_path: Path to the image file or URL
            
        Returns:
            Image as numpy array with shape (height, width, channels)
        """
        try:
            # Check if it's a URL
            if image_path.startswith(('http://', 'https://')):
                # Download image from URL
                response = requests.get(image_path, timeout=30)
                response.raise_for_status()  # Raise exception for bad status codes
                
                # Load image from bytes
                with Image.open(io.BytesIO(response.content)) as img:
                    # Convert to RGB if necessary
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Convert to numpy array
                    img_array = np.array(img)
                    
                    return img_array
            else:
                # Handle local file path
                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image file not found: {image_path}")
                
                # Load image using PIL
                with Image.open(image_path) as img:
                    # Convert to RGB if necessary
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Convert to numpy array
                    img_array = np.array(img)
                    
                    return img_array
                
        except Exception as e:
            raise ValueError(f"Could not load image file {image_path}: {str(e)}")

    def interpolate_images(self, img1: np.ndarray, img2: np.ndarray, alpha: float) -> np.ndarray:
        """
        Interpolate between two images using linear interpolation.
        
        Args:
            img1: Source image (start image)
            img2: Target image (end image)
            alpha: Interpolation factor (0 to 1)
                    0 = start image, 1 = end image
            
        Returns:
            Interpolated image
        """
        # Ensure images are the same size
        if img1.shape != img2.shape:
            # Resize img2 to match img1
            from skimage.transform import resize
            img2 = resize(img2, img1.shape, preserve_range=True).astype(img1.dtype)
        
        # Linear interpolation between images
        interpolated = img1 * (1 - alpha) + img2 * alpha
        return interpolated.astype(np.uint8)

    def image_to_base64(self, image: np.ndarray) -> str:
        """
        Convert an image to base64 string for transmission.
        
        Args:
            image: Image as numpy array
            
        Returns:
            Base64 encoded string
        """
        # Convert numpy array to PIL Image
        pil_image = Image.fromarray(image)
        
        # Save to bytes buffer
        buffer = io.BytesIO()
        pil_image.save(buffer, format='JPEG', quality=85)
        
        # Convert to base64
        img_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return img_str

    def interpolate(self, start_image: np.ndarray, end_image: np.ndarray, num_samples: int = 5) -> Tuple[List[str], List[float]]:
        """
        Generate sample interpolated images between start and end images.
        
        Args:
            start_image: Starting image
            end_image: Ending image
            num_samples: Number of samples to generate
            
        Returns:
            List of base64 encoded images, list of tick values
        """
        # Generate tick values from 0 to 1 (leftmost = start, rightmost = end)
        tick_values = np.linspace(0, 1, num_samples)
        
        # Generate interpolated images
        interpolated_images = []
        for tick in tick_values:
            # Interpolate between start and end images
            morphed_image = self.interpolate_images(start_image, end_image, tick)
            
            # Convert to base64 for transmission
            base64_image = self.image_to_base64(morphed_image)
            interpolated_images.append(base64_image)
            
            # Force garbage collection periodically
            if len(interpolated_images) % 10 == 0:
                gc.collect()
        
        return interpolated_images, tick_values.tolist()

    def load_image_with_timeout(self, image_path: str, timeout_seconds: int = 30) -> np.ndarray:
        """
        Load image with timeout to prevent long processing times.
        """
        start_time = time.time()
        
        try:
            if time.time() - start_time > timeout_seconds:
                raise ValueError(f"Image loading timeout after {timeout_seconds} seconds")
            
            return self.load_image(image_path)
            
        except Exception as e:
            raise ValueError(f"Could not load image file {image_path}: {str(e)}")

    def generate_image_samples_with_timeout(self, start_image: np.ndarray, end_image: np.ndarray, num_samples: int = 5) -> Tuple[List[str], List[float]]:
        """
        Generate image samples with timeout to prevent long processing.
        """
        start_time = time.time()
        timeout_seconds = 60  # 1 minute timeout
        
        try:
            tick_values = np.linspace(0, 1, num_samples)
            interpolated_images = []
            
            for tick in tick_values:
                if time.time() - start_time > timeout_seconds:
                    raise ValueError(f"Sample generation timeout after {timeout_seconds} seconds")
                
                # Interpolate between start and end images
                morphed_image = self.interpolate_images(start_image, end_image, tick)
                
                # Convert to base64 for transmission
                base64_image = self.image_to_base64(morphed_image)
                interpolated_images.append(base64_image)
                
                # Force garbage collection periodically
                if len(interpolated_images) % 10 == 0:
                    gc.collect()
            
            return interpolated_images, tick_values.tolist()
            
        except Exception as e:
            raise e
