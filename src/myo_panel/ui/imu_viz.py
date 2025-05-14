"""Matplotlib-based IMU visualization for Myo Panel."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PySide6.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.axes import Axes
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import matplotlib as mpl
import time

class MatplotlibIMUCube(QWidget):
    """A widget that displays a 3D cube that rotates based on IMU data."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Create a figure and 3D axis
        self.fig = Figure(figsize=(5, 5), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111, projection='3d')
        
        # Create a tare button
        self.tare_button = QPushButton("Reset Orientation")
        self.tare_button.clicked.connect(self.reset_orientation)
        
        # Set up the layout with the button at the top
        layout = QVBoxLayout(self)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.tare_button)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addWidget(self.canvas)
        
        # Initialize with identity rotation
        self.rotation_matrix = np.eye(3)
        
        # Reference orientation - used for taring/resetting
        self.reference_orientation = np.eye(3)
        self.last_raw_rotation = np.eye(3)
        
        # Original cube vertices
        self.original_vertices = np.array([
            [1, 1, 1],
            [1, 1, -1],
            [1, -1, 1],
            [1, -1, -1],
            [-1, 1, 1],
            [-1, 1, -1],
            [-1, -1, 1],
            [-1, -1, -1]
        ])
        
        # Create the cube
        self._setup_cube()
        
        # Set up the axes
        self._setup_axes()
        
        # Debug counter to check if updates are occurring
        self.update_count = 0
        
        # Throttling mechanism to reduce flickering
        self.last_update_time = time.time()
        self.update_interval = 0.05  # 50ms between updates (20 fps)
        
        # Rotation has been updated flag
        self.rotation_updated = False
        
        # Set up a timer to handle updates on the UI thread
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(50)  # 50ms between updates (20 fps)
        self.update_timer.timeout.connect(self._process_updates)
        self.update_timer.start()
    
    def _setup_axes(self):
        """Configure the 3D axes for the cube visualization."""
        self.ax.set_xlim([-1.5, 1.5])
        self.ax.set_ylim([-1.5, 1.5])
        self.ax.set_zlim([-1.5, 1.5])
        
        # Add axis labels
        self.ax.set_xlabel('X')
        self.ax.set_ylabel('Y')
        self.ax.set_zlabel('Z')
        
        # Optional: Remove ticks for cleaner look
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.ax.set_zticks([])
        
        # Set empty title
        self.ax.set_title("")
        
        # Equal aspect ratio
        self.ax.set_box_aspect([1, 1, 1])
        
        # Dark background for better visibility
        self.fig.patch.set_facecolor('#2D2D30')
        self.ax.set_facecolor('#2D2D30')
        
        # Set the axis colors to white for visibility
        self.ax.xaxis.label.set_color('white')
        self.ax.yaxis.label.set_color('white')
        self.ax.zaxis.label.set_color('white')
        
        # Disable autoscale to prevent flickering
        self.ax.autoscale(enable=False)
    
    def _setup_cube(self):
        """Create the cube vertices and faces."""
        # Define the faces using vertex indices
        self.face_indices = [
            [0, 1, 3, 2],  # Right face
            [4, 6, 7, 5],  # Left face
            [0, 4, 5, 1],  # Top face
            [2, 3, 7, 6],  # Bottom face
            [0, 2, 6, 4],  # Front face
            [1, 5, 7, 3]   # Back face
        ]
        
        # Colors for each face
        colors = ['#FFD700', '#87CEEB', '#FF6347', '#32CD32', '#9370DB', '#FF8C00']
        
        # Create the faces
        self.faces = []
        for i, idx in enumerate(self.face_indices):
            verts = [self.original_vertices[j] for j in idx]
            poly = Poly3DCollection([verts], alpha=0.9)
            poly.set_facecolor(colors[i])
            poly.set_edgecolor('white')
            self.ax.add_collection3d(poly)
            self.faces.append(poly)
    
    def _process_updates(self):
        """Process any pending updates (called by timer on UI thread)."""
        if not self.rotation_updated:
            return
            
        # Reset the flag
        self.rotation_updated = False
        
        # Rotate all vertices
        rotated_vertices = np.dot(self.original_vertices, self.rotation_matrix)
        
        # Update each face with new vertex positions
        for i, poly in enumerate(self.faces):
            idx = self.face_indices[i]
            verts = [rotated_vertices[j] for j in idx]
            poly.set_verts([verts])
        
        # Update counter (keep it for internal tracking but don't display it)
        self.update_count += 1
        
        # Redraw the canvas - use draw_idle for better performance
        self.canvas.draw_idle()
    
    def reset_orientation(self):
        """Reset/tare the orientation to current position as reference."""
        # Current raw rotation becomes the new reference point
        self.reference_orientation = np.copy(self.last_raw_rotation)
        
        # Reset the effective rotation to identity (upright orientation)
        self.rotation_matrix = np.eye(3)
        
        # Mark for update
        self.rotation_updated = True
    
    def update_gyro(self, gyro):
        """Update cube rotation based on gyroscope data."""
        if not gyro or len(gyro) != 3:
            return
        
        # For simplicity, directly use the gyro values for rotation
        # In a more complex implementation, you'd integrate over time
        x_rot, y_rot, z_rot = gyro
        
        # Invert the rotation values to correct the mirrored direction
        x_rot, y_rot, z_rot = -x_rot, -y_rot, -z_rot
        
        # Scale the rotation to make it more visible
        scale = 0.1
        x_rot *= scale
        y_rot *= scale
        z_rot *= scale
        
        # Create rotation matrices for each axis
        # X-axis rotation
        Rx = np.array([[1, 0, 0],
                      [0, np.cos(x_rot), -np.sin(x_rot)],
                      [0, np.sin(x_rot), np.cos(x_rot)]])
        # Y-axis rotation
        Ry = np.array([[np.cos(y_rot), 0, np.sin(y_rot)],
                      [0, 1, 0],
                      [-np.sin(y_rot), 0, np.cos(y_rot)]])
        # Z-axis rotation
        Rz = np.array([[np.cos(z_rot), -np.sin(z_rot), 0],
                      [np.sin(z_rot), np.cos(z_rot), 0],
                      [0, 0, 1]])
                      
        # Combined rotation matrix
        R = np.dot(Rz, np.dot(Ry, Rx))
        
        # Update the raw rotation (without reference compensation)
        self.last_raw_rotation = np.dot(R, self.last_raw_rotation)
        
        # Apply the rotation relative to the reference orientation
        # Reffective = R * Rinverse_reference
        effective_rotation = np.dot(self.last_raw_rotation, np.linalg.inv(self.reference_orientation))
        
        # Set the rotation matrix
        self.rotation_matrix = effective_rotation
        
        # Set flag to indicate the rotation has been updated
        self.rotation_updated = True
    
    def update_quaternion(self, quat):
        """Update cube orientation based on quaternion data.
        
        Args:
            quat: A list [w, x, y, z] representing the quaternion
        """
        if not quat or len(quat) != 4:
            return
            
        # Extract quaternion components
        w, x, y, z = quat
        
        # Invert the x, y, z components to correct the mirrored direction
        x, y, z = -x, -y, -z
        
        # Convert quaternion to rotation matrix (raw orientation from sensor)
        raw_rotation = np.array([
            [1 - 2*y*y - 2*z*z, 2*x*y - 2*z*w, 2*x*z + 2*y*w],
            [2*x*y + 2*z*w, 1 - 2*x*x - 2*z*z, 2*y*z - 2*x*w],
            [2*x*z - 2*y*w, 2*y*z + 2*x*w, 1 - 2*x*x - 2*y*y]
        ])
        
        # Save the raw rotation for reference when taring
        self.last_raw_rotation = raw_rotation
        
        # Apply the rotation relative to the reference orientation
        # Reffective = R * Rinverse_reference
        effective_rotation = np.dot(raw_rotation, np.linalg.inv(self.reference_orientation))
        
        # Set the rotation matrix
        self.rotation_matrix = effective_rotation
        
        # Set flag to indicate the rotation has been updated
        self.rotation_updated = True
    
    def showEvent(self, event):
        """Handle widget show event by performing a full redraw."""
        super().showEvent(event)
        # Ensure timer is running when widget is shown
        if not self.update_timer.isActive():
            self.update_timer.start()
        
    def hideEvent(self, event):
        """Handle widget hide event."""
        super().hideEvent(event)
        # Stop timer when widget is hidden to save resources
        self.update_timer.stop()
        
    def closeEvent(self, event):
        """Handle widget close event."""
        super().closeEvent(event)
        # Ensure timer is stopped when widget is closed
        self.update_timer.stop() 