"""UI modules for Myo Panel."""

from .windows import MainWindow
from .plots import EMGGrid, EMGComposite
from .recording import RecordingPanel
from .imu_viz import MatplotlibIMUCube

# Camera imports are optional
try:
    from .camera_manager import CameraManager
    from .vision_recording import VisionRecordingWidget
    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False
