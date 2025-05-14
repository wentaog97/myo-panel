"""Camera management for vision-based recording."""
import cv2
import numpy as np
import threading
import time
try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False

class CameraManager:
    """Manages camera operations for vision-based recording."""
    
    def __init__(self):
        self.camera_id = 0  # Default camera
        self.capture = None
        self.running = False
        self.thread = None
        self.latest_frame = None
        self.latest_landmarks = None
        self.frame_width = 640
        self.frame_height = 480
        self.fps = 30
        
        # MediaPipe components
        self.use_pose = False  # Disable pose detection by default
        self.use_hands = True   # Enable hand detection by default
        self.mp_pose = None
        self.mp_hands = None
        self.mp_drawing = None
        
        # Initialize MediaPipe if available
        self._setup_mediapipe()
    
    def _setup_mediapipe(self):
        """Set up MediaPipe hands module if available (pose is now disabled)."""
        if not MEDIAPIPE_AVAILABLE:
            return
        
        # Pose detection is no longer initialized here
        # if self.use_pose:
        #     mp_pose = mp.solutions.pose
        #     self.mp_pose = mp_pose.Pose(
        #         static_image_mode=False,
        #         min_detection_confidence=0.5,
        #         min_tracking_confidence=0.5,
        #         model_complexity=1
        #     )
        
        if self.use_hands:
            mp_hands = mp.solutions.hands
            self.mp_hands = mp_hands.Hands(
                static_image_mode=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
                max_num_hands=2,
                model_complexity=1
            )
        
        self.mp_drawing = mp.solutions.drawing_utils
    
    def get_available_cameras(self):
        """Get a list of available cameras."""
        cameras = []
        # Add "Default" option
        cameras.append({"id": 0, "name": "Default"})
        
        # Try opening the first 5 camera indices
        # This number can be adjusted based on expected maximum cameras
        for i in range(1, 5):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                # Get camera name
                name = f"Camera {i}"
                cameras.append({"id": i, "name": name})
                cap.release()
        
        return cameras
    
    def set_camera(self, camera_id):
        """Set the camera to use."""
        was_running = self.running
        
        # Stop the current camera if running
        if self.running:
            self.stop()
        
        self.camera_id = camera_id
        
        # Restart if it was running before
        if was_running:
            self.start()
    
    def start(self):
        """Start the camera capture."""
        print("CameraManager: start() called.")
        if self.running:
            print("CameraManager: Already running, returning True.")
            return True
            
        # Re-initialize MediaPipe if it was stopped and resources were released
        if MEDIAPIPE_AVAILABLE and self.use_hands and self.mp_hands is None:
            print("CameraManager: MediaPipe Hands was None, re-initializing...")
            self._setup_mediapipe() # This will re-create self.mp_hands
        elif MEDIAPIPE_AVAILABLE and not self.use_hands and self.mp_hands is not None:
            # This case should ideally not happen if use_hands is managed consistently
            # but as a safeguard, close mp_hands if use_hands is false
            print("CameraManager: use_hands is False but mp_hands exists, closing it.")
            self.mp_hands.close()
            self.mp_hands = None

        # Initialize capture
        try:
            self.capture = cv2.VideoCapture(self.camera_id)
            if not self.capture.isOpened():
                print(f"Error: Could not open camera {self.camera_id}")
                print("This may be due to camera permissions. Please ensure the application has permission to access your camera.")
                print("On macOS: System Settings > Privacy & Security > Camera")
                print("On Windows: Settings > Privacy > Camera")
                return False
                
            # Set resolution
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            
            # Start capture thread
            self.running = True
            self.thread = threading.Thread(target=self._capture_loop)
            self.thread.daemon = True  # Thread will exit when main program exits
            self.thread.start()
            return True
        except Exception as e:
            print(f"Camera initialization error: {e}")
            print("This may be due to camera permissions or hardware issues.")
            print("Please ensure the application has permission to access your camera.")
            print("On macOS: System Settings > Privacy & Security > Camera")
            print("On Windows: Settings > Privacy > Camera")
            self.running = False
            self.capture = None
            return False
    
    def stop(self):
        """Stop the camera capture."""
        print("CameraManager: stop() called.")
        if not self.running and not self.thread and not self.capture:
            print("CameraManager: Already stopped or not started.")
            return

        self.running = False # Signal the loop to stop

        if self.thread:
            print("CameraManager: Joining camera thread...")
            self.thread.join(timeout=2.0) # Wait for the thread to finish
            if self.thread.is_alive():
                print("CameraManager: Warning - Camera thread did not terminate in time.")
            else:
                print("CameraManager: Camera thread joined successfully.")
            self.thread = None
            
        if self.capture:
            print("CameraManager: Releasing camera capture object.")
            self.capture.release()
            self.capture = None
        
        # Explicitly release MediaPipe resources
        if MEDIAPIPE_AVAILABLE:
            # self.mp_pose is no longer used actively, but ensure it's cleaned if ever set
            if self.mp_pose:
                print("CameraManager: Closing MediaPipe Pose (if it was ever initialized).")
                self.mp_pose.close()
                self.mp_pose = None 
            if self.mp_hands:
                print("CameraManager: Closing MediaPipe Hands.")
                self.mp_hands.close()
                self.mp_hands = None
        print("CameraManager: stop() completed.")
    
    def _capture_loop(self):
        """Main capture loop that runs in a separate thread."""
        print("CameraManager: Capture loop started.")
        while self.running:
            if not self.capture or not self.capture.isOpened():
                print("CameraManager: Capture object not available/open in loop, stopping.")
                self.running = False # Ensure loop terminates
                break
                
            ret, frame = self.capture.read()
            if not ret:
                time.sleep(0.01) # Brief pause if no frame
                continue
                
            frame = cv2.flip(frame, 1)
            
            processed_frame = frame
            landmarks_data = None

            if MEDIAPIPE_AVAILABLE and self.running:
                if self.mp_hands: # Check if it is not None
                    try:
                        processed_frame, landmarks_data = self._process_mediapipe(frame)
                    except Exception as e:
                        print(f"CameraManager: Error during MediaPipe processing in loop: {e}")
                        processed_frame = frame 
                        landmarks_data = None
            
            self.latest_frame = processed_frame
            self.latest_landmarks = landmarks_data
            
            # Frame rate control (ensure it doesn't block exit if self.running is false)
            for _ in range(int(self.fps * 0.01)): # Sleep in small chunks
                if not self.running:
                    break
                time.sleep(0.01)
            if not self.running: # Check again after sleep
                 break

        print("CameraManager: Capture loop ended.")
    
    def _process_mediapipe(self, frame):
        """Process frame with MediaPipe for hand landmarks only."""
        if not MEDIAPIPE_AVAILABLE or not self.mp_hands:
            return frame, None
            
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        
        hands_results = None
        
        if self.use_hands:
            hands_results = self.mp_hands.process(rgb_frame)
        
        rgb_frame.flags.writeable = True
        frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
        
        if self.use_hands and hands_results and hands_results.multi_hand_landmarks:
            for hand_landmarks in hands_results.multi_hand_landmarks:
                self.mp_drawing.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp.solutions.hands.HAND_CONNECTIONS
                )
        
        landmarks_data = {
            "pose": None,  # Pose data is always None now
            "hands": self._extract_hand_landmarks(hands_results) if hands_results else None
        }
        
        return frame, landmarks_data
    
    def _extract_hand_landmarks(self, results):
        """Extract hand landmarks from MediaPipe results."""
        if not results or not results.multi_hand_landmarks:
            return None
            
        hands = []
        for i, hand_landmarks in enumerate(results.multi_hand_landmarks):
            hand_type = "unknown"
            if results.multi_handedness and i < len(results.multi_handedness):
                # Get hand type (left or right)
                hand_type = results.multi_handedness[i].classification[0].label
                
            landmarks = []
            for landmark in hand_landmarks.landmark:
                landmarks.append({
                    "x": landmark.x,
                    "y": landmark.y,
                    "z": landmark.z
                })
                
            hands.append({
                "type": hand_type,
                "landmarks": landmarks
            })
            
        return hands
    
    def get_latest_frame(self):
        """Get the latest processed frame."""
        return self.latest_frame
        
    def get_latest_landmarks(self):
        """Get the latest landmarks data."""
        return self.latest_landmarks
    
    def set_resolution(self, width, height):
        """Set camera resolution."""
        self.frame_width = width
        self.frame_height = height
        
        # Update camera if running
        if self.capture and self.capture.isOpened():
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    
    def __del__(self):
        """Clean up resources."""
        self.stop()
        
        # Release MediaPipe resources
        if MEDIAPIPE_AVAILABLE:
            if self.mp_hands:
                self.mp_hands.close() 