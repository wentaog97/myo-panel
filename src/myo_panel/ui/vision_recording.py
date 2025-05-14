"""Computer vision visualization for Myo Panel."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap

import cv2
import numpy as np

# Try importing camera manager, but handle potential import errors
try:
    from ..vision import CameraManager, MEDIAPIPE_AVAILABLE
    print("Successfully imported camera_manager module")
except ImportError as e:
    print(f"Error importing camera_manager: {e}")
    # Fallback definitions
    MEDIAPIPE_AVAILABLE = False
    
    # Create a dummy CameraManager class if import fails
    class CameraManager:
        def __init__(self):
            self.use_pose = True
            self.use_hands = True
            
        def get_available_cameras(self):
            return [{"id": 0, "name": "Default"}]
            
        def start(self):
            print("Camera manager not available")
            return False
            
        def stop(self):
            pass
            
        def set_camera(self, camera_id):
            pass
            
        def set_resolution(self, width, height):
            pass
            
        def get_latest_frame(self):
            return None
            
        def get_latest_landmarks(self):
            return None

class VideoDisplayWidget(QLabel):
    """Widget to display video from the camera."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(320, 240)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setText("Camera feed will be displayed here")
        self.setStyleSheet("background-color: #222; color: gray;")

    def update_frame(self, frame):
        """Update displayed frame."""
        if frame is None:
            return
            
        # Convert the frame to QImage
        height, width, channels = frame.shape
        bytes_per_line = channels * width
        
        # Convert BGR to RGB for Qt
        qt_image = QImage(
            frame.data, 
            width, 
            height, 
            bytes_per_line, 
            QImage.Format_RGB888
        ).rgbSwapped()
        
        # Scale pixmap to fit label while preserving aspect ratio
        pixmap = QPixmap.fromImage(qt_image)
        self.setPixmap(pixmap.scaled(
            self.width(), 
            self.height(),
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        ))

    def clear_display(self):
        """Clear the video display and show default text."""
        self.clear() # Clears the pixmap
        self.setText("Camera feed will be displayed here") # Reset default text
        self.setStyleSheet("background-color: #222; color: gray;") # Reset style

class VisionRecordingWidget(QWidget):
    """A widget that provides computer vision visualization."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.camera_manager = CameraManager()
        
        layout = QVBoxLayout(self)
        
        info_label = QLabel("CV View")
        info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(info_label)
        
        self.video_display = VideoDisplayWidget()
        layout.addWidget(self.video_display)
        
        control_layout = QHBoxLayout()
        
        self.status_label = QLabel("Camera: Stopped")
        self.status_label.setStyleSheet("color: gray;")
        
        self.preview_btn = QPushButton("Start Preview")
        self.preview_btn.clicked.connect(self._toggle_preview)
        
        control_layout.addStretch()
        control_layout.addWidget(self.status_label)
        control_layout.addStretch()
        control_layout.addWidget(self.preview_btn)
        
        layout.addLayout(control_layout)
        
        if not MEDIAPIPE_AVAILABLE:
            notice = QLabel("MediaPipe not installed. Install with: pip install mediapipe\nHand tracking visualization will not be available.")
            notice.setStyleSheet("color: #d64045;")
            layout.addWidget(notice)
        
        layout.addStretch()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_frame)
        self.timer.setInterval(33)  # ~30 fps
    
    def _toggle_preview(self):
        """Toggle camera preview."""
        if self.timer.isActive():
            # Stop preview
            self.timer.stop()
            self.camera_manager.stop()
            self.preview_btn.setText("Start Preview")
            self.status_label.setText("Camera: Stopped")
            self.status_label.setStyleSheet("color: gray;")
            self.video_display.clear_display() # Clear the display
        else:
            # Start preview
            if self.camera_manager.start():
                self.timer.start()
                self.preview_btn.setText("Stop Preview")
                self.status_label.setText("Camera: Running")
                self.status_label.setStyleSheet("color: green;")
            else:
                self.status_label.setText("Camera: Permission Error")
                self.status_label.setStyleSheet("color: red;")
                
                # Show a more detailed error message in the video display
                self.video_display.setText("Camera access error\n\n" +
                    "This may be due to camera permissions.\n" +
                    "Please ensure the application has permission to access your camera.\n\n" +
                    "On macOS: System Settings > Privacy & Security > Camera\n" +
                    "On Windows: Settings > Privacy > Camera")
    
    def _update_frame(self):
        """Update the video frame from camera."""
        frame = self.camera_manager.get_latest_frame()
        if frame is not None:
            self.video_display.update_frame(frame)
    
    def get_latest_landmarks(self):
        """Get the latest landmarks data for recording."""
        if self.camera_manager:
            return self.camera_manager.get_latest_landmarks()
        return None
    
    def showEvent(self, event):
        """Handle show event."""
        super().showEvent(event)
        # Add a short delay to give the UI time to fully initialize
        QTimer.singleShot(500, self._delayed_start)
        
    def _delayed_start(self):
        """Start the camera with a delay to avoid initialization issues."""
        if not self.timer.isActive() and not self.camera_manager.running:
            self._toggle_preview()
    
    def hideEvent(self, event):
        """Handle hide event."""
        super().hideEvent(event)
        # Stop camera when widget is hidden
        if self.timer.isActive():
            self._toggle_preview()
    
    def closeEvent(self, event):
        """Handle close event for the CV View widget."""
        print("VisionRecordingWidget: closeEvent called.")
        # Ensure camera is stopped
        if hasattr(self, 'timer') and self.timer.isActive():
            print("VisionRecordingWidget: Stopping QTimer.")
            self.timer.stop()
        if hasattr(self, 'camera_manager'):
            print("VisionRecordingWidget: Calling camera_manager.stop().")
            self.camera_manager.stop() 
        super().closeEvent(event)
        print("VisionRecordingWidget: closeEvent completed.") 