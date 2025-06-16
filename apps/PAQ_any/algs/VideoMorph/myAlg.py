import next.utils as utils
import cv2
import numpy as np
from typing import Dict, Any, List, Tuple
import random
import base64

class MyAlg:
    def initExp(self, butler, startItems, referenceItems, 
                endItems, tickFlag, tickNum, queryType):  
        butler.algorithms.set(key='morphedReference', value=list())
        butler.algorithms.set(key='morphedCandidates', value=list())
        butler.algorithms.set(key='tickFlag', value=tickFlag)
        butler.algorithms.set(key='tickNum', value=tickNum)
        butler.algorithms.set(key='num_reported_answers', value=0) 
        butler.algorithms.set(key='ticks', value=list())
        butler.algorithms.set(key='queryType', value=queryType)
        return True


    def getQuery(self, butler, source, query_id):
        if (len(butler.algorithms.get(key='morphedReference')) <= query_id):
            frames, fps, dims = self.load_video(source)
            morph_level = random.random()  # Random value between 0 and 1
            morphed_frames = []
            for i in range(len(frames)-1):
                morphed_frame = self.generate_morphed_frame(frames[i], frames[i+1], morph_level)
                morphed_frames.append(morphed_frame)
            A = np.array(morphed_frames)
            butler.algorithms.append(key='morphedReference', value=A.tolist())
            targets, ticks = self.generate_samples(source, butler.algorithms.get(key='tickNum'))
            butler.algorithms.append(key='morphedCandidates', value=targets.tolist())
            butler.algorithms.append(key='ticks', value=ticks.tolist())
        
        return {'referenceItem': butler.algorithms.get(key='morphedReference')[query_id], 
                'targetItems': butler.algorithms.get(key='morphedCandidates')[query_id], 
                'ticks': butler.algorithms.get(key='ticks')[query_id], 
                'tickFlag': butler.algorithms.get(key='tickFlag'),
                'queryType': 'video',
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

    def load_video(self, video_path: str) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """
        Load a video file and return its frames and metadata.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Tuple of (frames array, fps, (width, height))
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        frames = []
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
            
        cap.release()
        return np.array(frames), fps, (width, height)

    def generate_morphed_frame(self, frame1: np.ndarray, frame2: np.ndarray, alpha: float) -> np.ndarray:
        """
        Generate a morphed frame by interpolating between two frames.
        
        Args:
            frame1: Source frame
            frame2: Target frame
            alpha: Interpolation factor (0 to 1)
            
        Returns:
            Morphed frame
        """
        # Ensure frames are the same size
        if frame1.shape != frame2.shape:
            frame2 = cv2.resize(frame2, (frame1.shape[1], frame1.shape[0]))
            
        # Linear interpolation between frames
        morphed = cv2.addWeighted(frame1, 1 - alpha, frame2, alpha, 0)
        return morphed.astype(np.uint8)

    def frame_to_base64(self, frame: np.ndarray) -> str:
        """
        Convert a frame to base64 string for transmission.
        
        Args:
            frame: Video frame as numpy array
            
        Returns:
            Base64 encoded string
        """
        _, buffer = cv2.imencode('.jpg', frame)
        return base64.b64encode(buffer).decode('utf-8')

    def generate_samples(self, source_video: str, num_samples: int = 5) -> Tuple[List[np.ndarray], List[float]]:
        """
        Generate sample morphed videos from the source video.
        
        Args:
            source_video: Path to source video
            num_samples: Number of samples to generate
            
        Returns:
            List of morphed videos, each in format (num_frames, height, width, channels)
        """
        # Load source video
        source_frames, fps, (width, height) = self.load_video(source_video)
        
        # Generate random transformations for target video
        target_frames = []
        for frame in source_frames:
            # Apply random transformations (rotation, scaling, etc.)
            angle = random.uniform(-30, 30)
            scale = random.uniform(0.8, 1.2)
            
            # Get rotation matrix
            center = (width/2, height/2)
            M = cv2.getRotationMatrix2D(center, angle, scale)
            
            # Apply transformation
            transformed = cv2.warpAffine(frame, M, (width, height))
            target_frames.append(transformed)
            
        target_frames = np.array(target_frames)
        
        # Generate tick values (0 to 1)
        tick_values = np.linspace(0, 1, num_samples)
        
        # Generate morphed videos
        morphed_videos = []
        for tick in tick_values:
            # Generate morphed frames
            morphed_frames = np.array([self.generate_morphed_frame(s, t, tick) 
                                     for s, t in zip(source_frames, target_frames)])
            morphed_videos.append(morphed_frames)
            
        return morphed_videos, tick_values

    # def process_video(self, video_path: str) -> Dict[str, Any]:
    #     """
    #     Process a video file and extract relevant information.
        
    #     Args:
    #         video_path: Path to the video file
            
    #     Returns:
    #         Dictionary containing video metadata and processed frames
    #     """
    #     cap = cv2.VideoCapture(video_path)
        
    #     if not cap.isOpened():
    #         raise ValueError(f"Could not open video file: {video_path}")
            
    #     # Get video properties
    #     fps = cap.get(cv2.CAP_PROP_FPS)
    #     frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    #     width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    #     height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
    #     # Store frames as numpy arrays
    #     frames = []
    #     while True:
    #         ret, frame = cap.read()
    #         if not ret:
    #             break
    #         frames.append(frame)
            
    #     cap.release()
        
    #     return {
    #         'fps': fps,
    #         'frame_count': frame_count,
    #         'width': width,
    #         'height': height,
    #         'frames': np.array(frames)
    #     }
        
    # def save_processed_video(self, frames: np.ndarray, output_path: str, fps: float = 30.0) -> None:
    #     """
    #     Save processed frames as a video file.
        
    #     Args:
    #         frames: Array of video frames
    #         output_path: Path to save the output video
    #         fps: Frames per second for the output video
    #     """
    #     if len(frames) == 0:
    #         raise ValueError("No frames to save")
    #     height, width = frames[0].shape[:2]
    #     fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    #     out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
    #     for frame in frames:
    #         out.write(frame)
            
    #     out.release()
