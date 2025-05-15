# windows.py
from PySide6.QtWidgets import (QMainWindow, QToolBar, QLabel, QStatusBar,
                               QWidget, QHBoxLayout, QVBoxLayout, QMenu, QToolButton,
                               QDockWidget)
from PySide6.QtGui     import QAction, QActionGroup
from PySide6.QtCore import QTimer, Qt
import asyncio, numpy as np
from collections import deque
import time

from .plots import _Ring, EMGGrid, EMGComposite
from .recording import RecordingPanel
from .imu_viz import MatplotlibIMUCube
# Delay importing VisionRecordingWidget for better startup performance

FRAME_UPDATE_INTERVAL   = 100   # ms
BATTERY_CHECK_INTERVAL  = 5000  # ms

class MainWindow(QMainWindow):
    def __init__(self, myo_mgr):
        super().__init__()
        self.myo = myo_mgr
        self._frame_q = deque(maxlen=500)
        self._ring    = _Ring()
        self._paused  = False
        self._scanning = False  # Track scanning state
        self._scan_connect_task = None # To store the reference to the scan/connect task
        self.setWindowTitle("Myo Panel")

        # Initialize EMG and IMU modes
        self._emg_mode = 3  # EMG_MODE_SEND_RAW
        self._imu_mode = 1  # IMU_MODE_SEND_DATA
        self.myo._emg_mode = self._emg_mode
        self.myo._imu_mode = self._imu_mode
        
        # Register connection callback to handle connection state changes from MyoManager
        self.myo.set_connection_callback(self._on_connection_changed)

        # ── top toolbar ────────────────────────────────────────────────
        tb = QToolBar()
        self.addToolBar(tb)

        self.scan_act  = tb.addAction("Scan")
        self.disc_act  = tb.addAction("Disconnect"); self.disc_act.setEnabled(False)
        self.off_act   = tb.addAction("Turn Off"); self.off_act.setEnabled(False)

        # Vibrate button (medium by default)
        self.vib_act   = tb.addAction("Vibrate"); self.vib_act.setEnabled(False)
        self.pause_act = tb.addAction("Pause Stream"); self.pause_act.setEnabled(False)

        # ----------------  View ▾ menu -----------------
        view_btn = QToolButton()
        view_btn.setText("View")
        view_btn.setPopupMode(QToolButton.InstantPopup)
        view_menu = QMenu(self)
        
        # EMG view mode options (moved from Options menu)
        view_group = QActionGroup(self); view_group.setExclusive(True)
        act_split  = QAction("Split channel view", self, checkable=True); act_split.setChecked(True)
        act_comp   = QAction("Composite view", self, checkable=True)
        for a in (act_split, act_comp):
            view_group.addAction(a); view_menu.addAction(a)
        view_group.triggered.connect(lambda a: self._show_split(a is act_split))
        
        view_menu.addSeparator()
        
        # Panel visibility toggles
        self.show_emg_act = QAction("Show EMG Visualization", self, checkable=True)
        self.show_emg_act.setChecked(True)
        self.show_emg_act.triggered.connect(lambda checked: self._toggle_dock_visibility("emg", checked))
        
        self.show_rec_act = QAction("Show Data Collection", self, checkable=True)
        self.show_rec_act.setChecked(True)
        self.show_rec_act.triggered.connect(lambda checked: self._toggle_dock_visibility("recording", checked))
        
        self.show_imu_act = QAction("Show IMU Visualization", self, checkable=True)
        self.show_imu_act.setChecked(True)
        self.show_imu_act.triggered.connect(lambda checked: self._toggle_dock_visibility("imu", checked))
        
        self.show_vision_act = QAction("Show CV View", self, checkable=True)
        self.show_vision_act.setChecked(False)
        # Connect to special handler that initializes the vision panel if needed
        self.show_vision_act.triggered.connect(self._toggle_vision_view)
        
        view_menu.addAction(self.show_emg_act)
        view_menu.addAction(self.show_rec_act)
        view_menu.addAction(self.show_imu_act)
        view_menu.addAction(self.show_vision_act)
        
        view_btn.setMenu(view_menu)
        tb.addWidget(view_btn)

        # ----------------  Options ▾ menu -----------------
        opt_menu = QMenu(self)

        #  Vibration sub-menu with *radio* items (just set preference)
        vib_menu = opt_menu.addMenu("Vibration")
        vib_group = QActionGroup(self); vib_group.setExclusive(True)

        act_v_short  = QAction("Short",  self, checkable=True)
        act_v_medium = QAction("Medium", self, checkable=True); act_v_medium.setChecked(True)
        act_v_long   = QAction("Long",   self, checkable=True)
        for a in (act_v_short, act_v_medium, act_v_long):
            vib_group.addAction(a); vib_menu.addAction(a)

        self._vib_pattern = "medium"             # default
        def _set_vib(act):
            self._vib_pattern = act.text().lower()
        vib_group.triggered.connect(_set_vib)

        #  EMG Mode sub-menu
        emg_menu = opt_menu.addMenu("EMG Mode")
        emg_group = QActionGroup(self); emg_group.setExclusive(True)
        
        act_emg_none = QAction("None (0x00)", self, checkable=True)
        act_emg_send_emg = QAction("Filtered (0x02)", self, checkable=True)
        act_emg_send_raw = QAction("Raw (0x03)", self, checkable=True); act_emg_send_raw.setChecked(True)
        
        for a in (act_emg_none, act_emg_send_emg, act_emg_send_raw):
            emg_group.addAction(a); emg_menu.addAction(a)
            
        self._emg_mode = 3  # default to EMG_MODE_SEND_RAW
        def _set_emg_mode(act):
            mode_map = {"None (0x00)": 0, "Filtered (0x02)": 2, "Raw (0x03)": 3}
            new_mode = mode_map[act.text()]
            self._emg_mode = new_mode
            self.myo._emg_mode = new_mode
            # Apply the change immediately if connected
            if self.myo.connected:
                self.status_lbl.setText("Updating EMG mode...")
                success = self.myo.update_modes(emg_mode=new_mode)
                if success:
                    QTimer.singleShot(300, self._update_mode_status)
                else:
                    QTimer.singleShot(300, lambda: self.status_lbl.setText("EMG mode update failed"))
        emg_group.triggered.connect(_set_emg_mode)
        
        #  IMU Mode sub-menu
        imu_menu = opt_menu.addMenu("IMU Mode")
        imu_group = QActionGroup(self); imu_group.setExclusive(True)
        
        act_imu_none = QAction("None (0x00)", self, checkable=True)
        act_imu_send_data = QAction("Data Streams (0x01)", self, checkable=True); act_imu_send_data.setChecked(True)
        act_imu_send_events = QAction("Motion Events (0x02)", self, checkable=True)
        act_imu_send_all = QAction("All Data & Events (0x03)", self, checkable=True)
        act_imu_send_raw = QAction("Raw Data (0x04)", self, checkable=True)
        
        for a in (act_imu_none, act_imu_send_data, act_imu_send_events, act_imu_send_all, act_imu_send_raw):
            imu_group.addAction(a); imu_menu.addAction(a)
            
        self._imu_mode = 1  # default to IMU_MODE_SEND_DATA
        def _set_imu_mode(act):
            mode_map = {
                "None (0x00)": 0, 
                "Data Streams (0x01)": 1, 
                "Motion Events (0x02)": 2, 
                "All Data & Events (0x03)": 3,
                "Raw Data (0x04)": 4
            }
            new_mode = mode_map[act.text()]
            self._imu_mode = new_mode
            self.myo._imu_mode = new_mode
            # Apply the change immediately if connected
            if self.myo.connected:
                self.status_lbl.setText("Updating IMU mode...")
                success = self.myo.update_modes(imu_mode=new_mode)
                if success:
                    QTimer.singleShot(300, self._update_mode_status)
                else:
                    QTimer.singleShot(300, lambda: self.status_lbl.setText("IMU mode update failed"))
        imu_group.triggered.connect(_set_imu_mode)

        #  Camera Settings sub-menu
        cam_menu = opt_menu.addMenu("Camera Settings")
        cam_menu.setObjectName("cam_menu")  # Set object name for later lookup
        
        # Camera selection
        cam_group = QActionGroup(self); cam_group.setExclusive(True)
        # We'll populate this when cameras are detected
        self.cam_actions = []
        
        # Default camera action is always available
        act_cam_default = QAction("Default Camera", self, checkable=True)
        act_cam_default.setChecked(True)
        cam_group.addAction(act_cam_default)
        cam_menu.addAction(act_cam_default)
        self.cam_actions.append({"action": act_cam_default, "id": 0})
        
        # Set camera function
        def _set_camera(act):
            # Find the camera ID for this action
            for cam in self.cam_actions:
                if cam["action"] is act:
                    # Set camera in vision recording widget if it exists
                    if hasattr(self, "vision_recording") and self.vision_recording:
                        self.vision_recording.camera_manager.set_camera(cam["id"])
                    break
        
        cam_group.triggered.connect(_set_camera)
        
        # Resolution sub-menu
        res_menu = cam_menu.addMenu("Resolution")
        res_group = QActionGroup(self); res_group.setExclusive(True)
        
        act_res_low = QAction("Low (320x240)", self, checkable=True)
        act_res_med = QAction("Medium (640x480)", self, checkable=True); act_res_med.setChecked(True)
        act_res_high = QAction("High (1280x720)", self, checkable=True)
        
        for a in (act_res_low, act_res_med, act_res_high):
            res_group.addAction(a); res_menu.addAction(a)
        
        # Set resolution function
        def _set_resolution(act):
            if hasattr(self, "vision_recording") and self.vision_recording:
                if act is act_res_low:
                    self.vision_recording.camera_manager.set_resolution(320, 240)
                elif act is act_res_med:
                    self.vision_recording.camera_manager.set_resolution(640, 480)
                elif act is act_res_high:
                    self.vision_recording.camera_manager.set_resolution(1280, 720)
        
        res_group.triggered.connect(_set_resolution)
        
        # Populate available cameras
        self._populate_camera_menu(cam_menu, cam_group)

        opt_btn = QToolButton()
        opt_btn.setText("Options")
        opt_btn.setPopupMode(QToolButton.InstantPopup)
        opt_btn.setMenu(opt_menu)
        opt_btn.setObjectName("opt_btn")  # Set object name for later lookup
        tb.addWidget(opt_btn)

        # Create dock widgets for movable and resizable components
        
        # EMG Grid dock widget
        self.grid_view = EMGGrid(self._ring)
        self.comp_view = EMGComposite(self._ring)
        self.comp_view.hide()
        
        emg_container = QWidget()
        emg_layout = QHBoxLayout(emg_container)
        emg_layout.addWidget(self.grid_view)
        emg_layout.addWidget(self.comp_view)
        
        self.emg_dock = QDockWidget("EMG Visualization", self)
        self.emg_dock.setWidget(emg_container)
        self.emg_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        # Only allow moving, no floating/popup
        self.emg_dock.setFeatures(QDockWidget.DockWidgetMovable)
        
        # Recording panel dock widget - remove title as it's already in the GroupBox
        self.record_panel = RecordingPanel(self.myo)
        # Disable recording buttons initially since no device is connected
        self.record_panel.timer_btn.setEnabled(False)
        self.record_panel.free_btn.setEnabled(False)
        
        # Connect the Enable Vision checkbox
        self.record_panel.enable_vision_chk.stateChanged.connect(self._toggle_vision_feature)
        
        self.recording_dock = QDockWidget("Data Collection", self)  # Add title here now
        self.recording_dock.setWidget(self.record_panel)
        self.recording_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        # Only allow moving, no floating/popup
        self.recording_dock.setFeatures(QDockWidget.DockWidgetMovable)
        
        # IMU visualization dock widget - using matplotlib-based cube
        self.imu = MatplotlibIMUCube()
        
        self.imu_dock = QDockWidget("IMU Visualization", self)
        self.imu_dock.setWidget(self.imu)
        self.imu_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        # Only allow moving, no floating/popup
        self.imu_dock.setFeatures(QDockWidget.DockWidgetMovable)
        
        # Vision Based Recording dock widget - lazy loaded
        # Will be created on demand when needed
        
        # Add dock widgets to the main window
        self.addDockWidget(Qt.LeftDockWidgetArea, self.emg_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.recording_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.imu_dock)
        
        # Dictionary to track dock widgets by name
        self.dock_widgets = {
            "emg": self.emg_dock,
            "recording": self.recording_dock,
            "imu": self.imu_dock
        }
        
        # Enable dock nesting
        self.setDockNestingEnabled(True)

        # ── status bar ────────────────────────────────────────────────
        sb = QStatusBar(); self.setStatusBar(sb)
        self.status_lbl = QLabel("Disconnected"); sb.addWidget(self.status_lbl)
        self.batt_lbl   = QLabel("Battery: -- %"); sb.addPermanentWidget(self.batt_lbl)

        # ── timers ────────────────────────────────────────────────────
        QTimer(self, interval=FRAME_UPDATE_INTERVAL, timeout=self._refresh_plots).start()
        QTimer(self, interval=BATTERY_CHECK_INTERVAL, timeout=self._query_battery).start()
        
        # Add a connection status checker timer - runs every 500ms to ensure UI is accurate
        QTimer(self, interval=500, timeout=self._check_connection_status).start()

        # ── connect actions ───────────────────────────────────────────
        self.scan_act.triggered.connect(self._scan_connect)
        self.disc_act.triggered.connect(self._disconnect)
        self.off_act.triggered .connect(self._turn_off)
        self.vib_act.triggered .connect(lambda: self.myo.vibrate_async(self._vib_pattern))
        self.pause_act.triggered.connect(self._toggle_pause)

        # ── connect IMU handler ───────────────────────────────────────
        self.myo._imu_handler = self._on_imu
    
    # ------------- dock widget visibility toggle ------------------
    def _toggle_dock_visibility(self, dock_name, visible):
        """Toggle the visibility of a dock widget."""
        if dock_name in self.dock_widgets:
            self.dock_widgets[dock_name].setVisible(visible)
            
            # If we're changing the vision dock visibility, sync the checkbox state
            if dock_name == "vision" and visible:
                # Sync the checkbox in recording panel with the vision dock visibility
                # Only set checked if making visible (one-way sync)
                self.record_panel.enable_vision_chk.setChecked(True)
            
    # ------------- toggle vision view ------------------------------
    def _toggle_vision_view(self, checked):
        """Toggle the visibility of the vision panel from the View menu."""
        # Initialize the vision panel if needed and checked
        if checked and "vision" not in self.dock_widgets:
            if not self._init_vision_recording():
                # Failed to initialize, uncheck the menu item
                self.show_vision_act.setChecked(False)
                return
        
        # Toggle visibility if the dock exists
        if "vision" in self.dock_widgets:
            self._toggle_dock_visibility("vision", checked)
            
            # If showing the panel, also check the enable vision checkbox
            if checked:
                self.record_panel.enable_vision_chk.setChecked(True)

    # ───────────────────────────────────────────────────────────────────
    def _refresh_plots(self):
        if self._paused or not self._frame_q:
            return
        take = min(len(self._frame_q), 20)
        frames = [self._frame_q.pop() for _ in range(take)][::-1]   # preserve order
        self._ring.insert(np.array(frames).T)
        (self.grid_view if self.grid_view.isVisible() else self.comp_view).refresh()

    # ------------- BLE stream callback -------------------------------
    def on_emg(self, _bank, two_frames):
        if not self._paused:
            # Append both frames for all EMG modes (1, 2, 3)
            # EMG_MODE_NONE (0) is handled in main.py before this is called
            self._frame_q.append(two_frames[0])
            self._frame_q.append(two_frames[1])

    # ------------- IMU callback ------------------------------------
    def _on_imu(self, quat, acc, gyro, timestamp=None, raw_hex=None):
        """Handle IMU data for both visualization and recording."""
        # Debug output - print IMU data periodically
        if getattr(self, "_imu_debug_counter", 0) % 100 == 0:  # Every 100 readings
            print(f"IMU data: quat={quat}, gyro={gyro}")
        
        # Increment debug counter
        self._imu_debug_counter = getattr(self, "_imu_debug_counter", 0) + 1
        
        # Update 3D visualization using either quaternion or gyro data
        # But only update if the IMU widget is visible (save CPU when not needed)
        if self.imu_dock.isVisible():
            if quat is not None:
                self.imu.update_quaternion(quat)
            elif gyro is not None:
                self.imu.update_gyro(gyro)
        
        # Record IMU data
        self.record_panel.push_imu(quat, acc, gyro, timestamp, raw_hex)

    # ------------- battery polling -----------------------------------
    def _query_battery(self):
        self.myo.refresh_battery_async()
        QTimer.singleShot(100, lambda: self.batt_lbl.setText(
            f"Battery: {self.myo.battery:>3d} %" if self.myo.battery is not None else "Battery: -- %"))

    # ------------- scan + connect ------------------------------------
    def _scan_connect(self):
        # Prevent multiple scan operations
        if self._scanning:
            return
        
        # Update scan button state
        self._scanning = True
        self.scan_act.setEnabled(False)
        self.status_lbl.setText("Scanning…")
        
        # Add a timeout timer to abort excessively long operations
        connection_timeout = QTimer(self)
        connection_timeout.setSingleShot(True)
        connection_timeout.setInterval(15000)  # 15 seconds timeout
        
        # Force abort function for connection that takes too long
        def _connection_timeout_handler():
            if self._scanning and self._scan_connect_task and not self._scan_connect_task.done():
                # Cancel the task if it's still running after timeout
                print("[MainWindow] Connection timeout - forcing abort")
                self._scan_connect_task.cancel()
                # Skip status update - let the status checker handle it consistently
                # This avoids showing misleading status messages
                pass
        
        connection_timeout.timeout.connect(_connection_timeout_handler)
        
        async def _do():
            try:
                # Start the timeout timer
                connection_timeout.start()
                
                loop = asyncio.get_running_loop()
                devs = await loop.run_in_executor(None, self.myo.scan)
                
                # Check for cancellation after potentially long operation
                await asyncio.sleep(0) # Allows task to be cancelled if requested
                if not devs:
                    self.status_lbl.setText("No MYO found")
                    return

                from PySide6.QtWidgets import QInputDialog, QDialog
                items = [f"{d['name']} ({d['address']})" for d in devs]
                dlg = QInputDialog(self)
                dlg.setWindowTitle("Select MYO")
                dlg.setLabelText("Select a Myo device:")
                dlg.setComboBoxItems(items)
                dlg.setOkButtonText("Connect")
                dlg.setCancelButtonText("Cancel")
                
                # Check for cancellation before showing dialog
                await asyncio.sleep(0)
                if dlg.exec() != QDialog.Accepted:
                    self.status_lbl.setText("Scan cancelled")
                    return

                idx = items.index(dlg.textValue())
                addr, name = devs[idx]["address"], devs[idx]["name"]
                self.status_lbl.setText("Connecting…")
                
                # Check for cancellation before connect
                await asyncio.sleep(0)
                try:
                    # Use the configured EMG and IMU modes
                    await loop.run_in_executor(None, lambda: self.myo.connect(addr, emg_mode=self._emg_mode, imu_mode=self._imu_mode))
                    
                    # Explicit status update when connection succeeds
                    print(f"[MainWindow] Connected to {name}")
                    
                    # Update UI status explicitly here even though the callback should also do it
                    # This provides redundancy in case the callback has issues
                    self.status_lbl.setText(f"Connected to {name}")
                    
                    # Schedule another status update for detailed info
                    QTimer.singleShot(200, self._update_mode_status)
                    
                except Exception as exc:
                    # Handle connection errors
                    print(f"[MainWindow] Connect error: {exc}")
                    self.status_lbl.setText(f"Connection failed: {str(exc)}")
                    
                    # Show error dialog
                    try:
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.critical(self, "Connect failed", str(exc))
                    except RuntimeError:
                        # Handle case where Qt objects are deleted
                        pass
            except asyncio.CancelledError:
                print("[MainWindow._do] Scan/connect task was cancelled.")
                # Skip status update entirely - let the status checker handle it
                # This avoids any misleading messages about waiting for the device
                pass
            except Exception as e:
                print(f"[MainWindow._do] Unexpected error: {e}")
                self.status_lbl.setText(f"Error: {str(e)}")
            finally:
                # Stop the timeout timer
                connection_timeout.stop()
                
                # Reset state flags
                self._scanning = False
                self._scan_connect_task = None
                
                # Update scan button based on connection status
                # The rest of the UI is updated by the connection callback
                if not self.myo.connected:
                    self.scan_act.setEnabled(True)
                
        # Cancel any existing task
        if self._scan_connect_task and not self._scan_connect_task.done():
            self._scan_connect_task.cancel()
            
        self._scan_connect_task = asyncio.create_task(_do())

    # ------------- manual disconnect ---------------------------------
    def _disconnect(self):
        # Only update status label - button states will be handled by connection callback
        self.status_lbl.setText("Disconnecting…")
        
        # Reset pause state if active
        if self._paused:
            self._paused = False
            self.pause_act.setText("Pause Stream")
            
        # Reset scanning state
        self._scanning = False
        
        # Initiate disconnect - UI will be fully updated via connection callback
        self.myo.disconnect_async()
        
        # Add a safety timer to ensure UI gets updated
        def _ensure_disconnected():
            if self.status_lbl.text() == "Disconnecting…" and not self.myo.connected:
                print("[MainWindow] Safety timer: Forcing 'Disconnected' status")
                self.status_lbl.setText("Disconnected")
                
                # Also ensure buttons are in correct state
                self.disc_act.setEnabled(False)
                self.off_act.setEnabled(False)
                self.vib_act.setEnabled(False)
                self.pause_act.setEnabled(False)
                self.scan_act.setEnabled(True)
                self.record_panel.timer_btn.setEnabled(False)
                self.record_panel.free_btn.setEnabled(False)
                
        # Force update after 1.5 seconds if needed
        QTimer.singleShot(1500, _ensure_disconnected)

    # ------------- turn off (deep-sleep) ------------------------------
    def _turn_off(self):
        # Only update status label - button states will be handled by connection callback
        self.status_lbl.setText("Turning off…")
        
        # Reset pause state if active
        if self._paused:
            self._paused = False
            self.pause_act.setText("Pause Stream")
        
        # Reset scanning state
        self._scanning = False
        
        # Initiate deep sleep - UI will be updated via connection callback
        self.myo.deep_sleep_async()
        
        # Override final status message to be more specific about power state
        QTimer.singleShot(600, lambda: self.status_lbl.setText("Device powered off (disconnected)"))

    # ------------- pause / resume ------------------------------------
    def _toggle_pause(self):
        self._paused = not self._paused
        self.pause_act.setText("Resume Stream" if self._paused else "Pause Stream")
        if self._paused: self._frame_q.clear()

    # ------------- view switching ------------------------------------
    def _show_split(self, split: bool):
        self.grid_view.setVisible(split); self.comp_view.setVisible(not split)
        
    # ------------- mode status display -----------------------------
    def _update_mode_status(self):
        """Update the status bar with current EMG and IMU modes."""
        if not self.myo.connected:
            return
            
        emg_modes = {
            0: "None",
            2: "Filtered",
            3: "Raw"
        }
        
        imu_modes = {
            0: "None",
            1: "Data Streams",
            2: "Motion Events",
            3: "All Data & Events",
            4: "Raw Data"
        }
        
        emg_mode_text = emg_modes.get(self._emg_mode, f"Unknown ({self._emg_mode})")
        imu_mode_text = imu_modes.get(self._imu_mode, f"Unknown ({self._imu_mode})")
        
        # Update detailed status text
        self.status_lbl.setText(f"Connected | EMG: {emg_mode_text} | IMU: {imu_mode_text}")
        
        # IMPORTANT: Always ensure button states match connection state
        # This guarantees UI consistency whenever detailed status is shown
        self.disc_act.setEnabled(True)
        self.off_act.setEnabled(True)
        self.vib_act.setEnabled(True)
        self.pause_act.setEnabled(True)
        self.scan_act.setEnabled(False)  # Can't scan when connected
        self.record_panel.timer_btn.setEnabled(True)
        self.record_panel.free_btn.setEnabled(True)
        
        # Force UI update to ensure changes are visible
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    # ------------- populate camera menu ----------------------------
    def _populate_camera_menu(self, menu, group):
        """Populate camera menu with available cameras."""
        if not hasattr(self, "vision_recording") or not self.vision_recording:
            return
            
        # Get available cameras
        cameras = self.vision_recording.camera_manager.get_available_cameras()
        
        # Skip first camera (Default) as it's already added
        for camera in cameras[1:]:
            action = QAction(camera["name"], self, checkable=True)
            group.addAction(action)
            menu.addAction(action)
            self.cam_actions.append({"action": action, "id": camera["id"]})
    
    # ------------- initialize Vision Recording widget -------------
    def _init_vision_recording(self):
        """Initialize the CV View widget if not already done."""
        # Import the necessary modules only when needed
        try:
            print("Initializing CV View widget...")
            from .vision_recording import VisionRecordingWidget
            
            # Create the Vision Recording widget
            self.vision_recording = VisionRecordingWidget()
            
            self.vision_dock = QDockWidget("CV View", self)
            self.vision_dock.setWidget(self.vision_recording)
            self.vision_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
            # Only allow moving, no floating/popup
            self.vision_dock.setFeatures(QDockWidget.DockWidgetMovable)
            # Hide by default
            self.vision_dock.setVisible(False)
            
            # Add dock widget to the main window
            self.addDockWidget(Qt.RightDockWidgetArea, self.vision_dock)
            
            # Add to dictionary to track dock widgets
            self.dock_widgets["vision"] = self.vision_dock
            
            print("CV View widget initialized successfully.")
            return True
        except ImportError as e:
            print(f"Failed to initialize CV View - ImportError: {e}")
            return False
        except Exception as e:
            print(f"Failed to initialize CV View - Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ------------- toggle vision feature ---------------------------
    def _toggle_vision_feature(self, state):
        """Enable the CV View when checkbox is checked.
        
        This is a one-way toggle - checking will show the panel, but
        unchecking will not hide it, to allow more flexibility.
        """
        if state == Qt.Checked:
            # Initialize the Vision Recording widget if needed
            if "vision" not in self.dock_widgets:
                if not self._init_vision_recording():
                    # Failed to initialize
                    return
                    
            # Only show the vision dock when checked, don't hide when unchecked
            self.vision_dock.setVisible(True)
            self.show_vision_act.setChecked(True)
            
            # Populate camera menu
            opt_btn = self.findChild(QToolButton, "opt_btn")
            if opt_btn and opt_btn.menu():
                cam_menu = opt_btn.menu().findChild(QMenu, "cam_menu")
                if cam_menu:
                    cam_group = cam_menu.findChild(QActionGroup)
                    if cam_group:
                        self._populate_camera_menu(cam_menu, cam_group)

    def closeEvent(self, event):
        """Handle application close."""
        print("MainWindow: closeEvent called.")

        # Flag to indicate shutdown is in progress
        self._shutting_down = True

        # Cancel the scan/connect task if it's running
        if self._scan_connect_task and not self._scan_connect_task.done():
            print("MainWindow: Cancelling active scan/connect task.")
            self._scan_connect_task.cancel()
            # We don't await it here as closeEvent is synchronous and we need it to proceed.
            # The task should handle its cancellation and cleanup in its finally block.

        # Initiate MyoManager shutdown. This is a blocking call with a timeout.
        print("MainWindow: Initiating MyoManager shutdown...")
        if self.myo:  # Ensure myo object exists
            self.myo.shutdown(timeout=2.0) # Reduced timeout for faster exit
            print("MainWindow: MyoManager shutdown process completed or timed out.")
        else:
            print("MainWindow: MyoManager instance not found.")

        # Clean up vision recording if it exists
        if hasattr(self, 'vision_recording') and self.vision_recording:
            if hasattr(self.vision_recording, "camera_manager") and self.vision_recording.camera_manager.running:
                print("MainWindow: Forcing camera_manager stop as a fallback.")
                self.vision_recording.camera_manager.stop()
        
        # Call parent's closeEvent
        super().closeEvent(event)
        print("MainWindow: closeEvent completed. Application should now exit if all non-daemon threads are done.")
        
        # Import inside the method to avoid circular imports
        from PySide6.QtWidgets import QApplication
        from ..ble.myo_manager import stop_bg_loop
        
        # Direct cleanup of the background loop
        stop_bg_loop()
        
        # Force application to quit after a short delay if it hasn't exited naturally
        from PySide6.QtCore import QTimer
        def force_quit():
            print("MainWindow: Forcing application exit")
            import os, signal, sys
            # First try SIGTERM
            try:
                os.kill(os.getpid(), signal.SIGTERM)
                # Short delay to allow SIGTERM to work
                QTimer.singleShot(500, lambda: sys.exit(1))
            except Exception as e:
                print(f"MainWindow: Error during force quit: {e}")
                sys.exit(1)  # Exit with error
            
        # Give the application much less time (1 second) to exit naturally, then force quit
        QTimer.singleShot(1000, force_quit)

    # ------------- connection state change callback ------------------
    def _on_connection_changed(self, connected, reason):
        """Handle connection state changes from MyoManager.
        
        This is called from MyoManager when the connection state changes,
        either due to a successful connection, manual disconnect, or
        unexpected disconnection.
        
        Args:
            connected: bool - whether the device is now connected
            reason: str - reason for the state change
        """
        try:
            print(f"[MainWindow] Connection state changed: connected={connected}, reason={reason}")
            
            # Use QTimer.singleShot to safely update UI from a non-Qt thread
            # This avoids Qt metaobject signature issues
            from PySide6.QtCore import QTimer
            
            # First do an immediate state update for critical UI elements
            # This reduces the chance of experiencing inconsistent UI state
            QTimer.singleShot(0, lambda: self._set_ui_connected_state(connected))
            
            # Then do the full update with text changes
            QTimer.singleShot(50, lambda: self._update_ui_connection_state(connected, reason))
            
            # Also schedule a fallback update to handle any race conditions
            # This ensures we'll update the UI status after a short delay as a backup
            if connected:
                # If connected, schedule another status update as a backup
                QTimer.singleShot(1000, lambda: 
                    self._set_ui_connected_state(True) 
                    if self.myo.connected 
                    else None
                )
        except Exception as e:
            print(f"[MainWindow] Error in connection callback: {e}")
    
    def _set_ui_connected_state(self, connected):
        """Utility method to ensure consistent UI button states.
        
        Args:
            connected: bool - whether to set connected or disconnected state
        """
        print(f"[MainWindow] Setting UI state to {'connected' if connected else 'disconnected'}")
        
        if connected:
            # Connected state
            self.disc_act.setEnabled(True)
            self.off_act.setEnabled(True)
            self.vib_act.setEnabled(True)
            self.pause_act.setEnabled(True)
            self.scan_act.setEnabled(False)  # Can't scan while connected
            self.record_panel.timer_btn.setEnabled(True)
            self.record_panel.free_btn.setEnabled(True)
        else:
            # Disconnected state
            self.disc_act.setEnabled(False)
            self.off_act.setEnabled(False)
            self.vib_act.setEnabled(False)
            self.pause_act.setEnabled(False)
            self.scan_act.setEnabled(True)
            self.record_panel.timer_btn.setEnabled(False)
            self.record_panel.free_btn.setEnabled(False)
            
        # Force UI update
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        
    def _update_ui_connection_state(self, connected, reason):
        """Update UI based on connection state change.
        
        This is called by _on_connection_changed via Qt's invokeMethod
        to ensure UI updates happen on the main thread.
        """
        print(f"[MainWindow] Updating UI connection state: connected={connected}, reason={reason}")
        print(f"[MainWindow] Current status: '{self.status_lbl.text()}'")
        
        # First ensure button states are consistent with connection state
        # This is redundant with the earlier call in _on_connection_changed but provides extra safety
        self._set_ui_connected_state(connected)
        
        if connected:
            # Always print a clear message to help with debugging
            print(f"[MainWindow] Device connected! Updating status from '{self.status_lbl.text()}' to 'Connected'")
            
            # Cancel any ongoing scan/connect task since we're now connected
            if self._scanning:
                self._scanning = False
                if self._scan_connect_task and not self._scan_connect_task.done():
                    print("[MainWindow] Cancelling scan task as connection was established")
                    self._scan_connect_task.cancel()
                    self._scan_connect_task = None
            
            # Force status update - always update when connected regardless of current text
            # This is important to ensure UI shows connected state no matter what
            if self.status_lbl.text() in ["Connection timed out", "Operation Cancelled"]:
                self.status_lbl.setText("Connected (succeeded after timeout)")
            else:
                self.status_lbl.setText("Connected - Streaming data")
            
            # Update with more detailed info after a short delay
            QTimer.singleShot(500, self._update_mode_status)
        else:
            # Device is disconnected - update UI accordingly
            print(f"[MainWindow] Device disconnected! Updating status from '{self.status_lbl.text()}' to 'Disconnected'")
            
            # Reset pause state if active
            if self._paused:
                self._paused = False
                self.pause_act.setText("Pause Stream")
            
            # Always update the status label, including if it was "Disconnecting..."
            if self.status_lbl.text() in ["Disconnecting…", "Connecting…"]:
                self.status_lbl.setText("Disconnected")
            else:
                # Update status message based on reason
                if reason == "unexpected_disconnect":
                    self.status_lbl.setText("Device disconnected unexpectedly")
                else:
                    self.status_lbl.setText("Disconnected")
            
            # Clear scanning flag in case disconnect happened during scan
            self._scanning = False

    # ------------- connection status checker -------------------------
    def _check_connection_status(self):
        """Check the connection status and data flow periodically and update the UI accordingly.
        
        This is a direct way to fix UI state regardless of race conditions in the connection process.
        - The key insight is to check for actual data flowing (IMU or battery updates) rather than
          just the myo.connected flag.
        - This solves the problem with disconnect being called first during connection attempts.
        """
        current_status = self.status_lbl.text()
        
        # Check if we're actually receiving data (battery or IMU data)
        data_flowing = (self.myo.battery is not None) or (len(self._frame_q) > 0)
        
        # Track when we last saw "Disconnecting..." status
        if current_status == "Disconnecting…":
            if not hasattr(self, "_disconnecting_start_time"):
                self._disconnecting_start_time = time.time()
            # Allow a grace period for disconnection (2 seconds)
            elif time.time() - self._disconnecting_start_time > 2.0:
                # It's been stuck on "Disconnecting..." for too long, force an update
                if not self.myo.connected and not data_flowing:
                    self.status_lbl.setText("Disconnected")
                    print("[MainWindow] Status fix: UI was stuck on 'Disconnecting...' - forced update.")
                    # Reset the timer
                    delattr(self, "_disconnecting_start_time")
                    return
        else:
            # Not disconnecting, clear the timer if it exists
            if hasattr(self, "_disconnecting_start_time"):
                delattr(self, "_disconnecting_start_time")
        
        # Don't interfere with active operations
        if current_status in ["Turning off…", "Scanning…"]:
            return
        
        # Data is flowing, ensure UI shows connected
        if data_flowing and self.myo.connected:
            # Verify button states regardless of current status text
            # This addresses cases where the status text is correct but buttons are wrong
            buttons_inconsistent = (
                not self.disc_act.isEnabled() or
                not self.off_act.isEnabled() or
                not self.vib_act.isEnabled() or
                not self.pause_act.isEnabled() or
                self.scan_act.isEnabled() or
                not self.record_panel.timer_btn.isEnabled() or
                not self.record_panel.free_btn.isEnabled()
            )
            
            if buttons_inconsistent:
                print("[MainWindow] Button state inconsistency detected - fixing UI controls")
                # Fix button states
                self.disc_act.setEnabled(True)
                self.off_act.setEnabled(True)
                self.vib_act.setEnabled(True)
                self.pause_act.setEnabled(True)
                self.scan_act.setEnabled(False)
                self.record_panel.timer_btn.setEnabled(True) 
                self.record_panel.free_btn.setEnabled(True)
                # Force UI update
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            
            # Also check if status text needs updating
            if current_status in ["Connection attempt cancelled - still waiting for device", 
                              "Connecting…", "Disconnected", "Operation Cancelled",
                              "Connection timed out - waiting for device (may still connect)"]:
                print(f"[MainWindow] Status fix: UI shows '{current_status}' but data is flowing. Fixing.")
                self.status_lbl.setText("Connected - Streaming data")
                
                # Ensure buttons are enabled (redundant with above but keeping for clarity)
                self.disc_act.setEnabled(True)
                self.off_act.setEnabled(True)
                self.vib_act.setEnabled(True)
                self.pause_act.setEnabled(True)
                self.scan_act.setEnabled(False)
                self.record_panel.timer_btn.setEnabled(True) 
                self.record_panel.free_btn.setEnabled(True)
                
                # Clear any lingering scan task
                if self._scanning:
                    self._scanning = False
                    if self._scan_connect_task and not self._scan_connect_task.done():
                        self._scan_connect_task.cancel()
                        self._scan_connect_task = None
        
        # No data flowing and not connected, ensure UI shows disconnected
        elif not data_flowing and not self.myo.connected:
            if "Connected" in current_status or "Streaming" in current_status:
                print(f"[MainWindow] Status fix: UI shows '{current_status}' but no data flowing and disconnected. Fixing.")
                self.status_lbl.setText("Disconnected")
                
                # Also update UI elements
                self.disc_act.setEnabled(False)
                self.off_act.setEnabled(False)
                self.vib_act.setEnabled(False)
                self.pause_act.setEnabled(False)
                self.scan_act.setEnabled(True)
                self.record_panel.timer_btn.setEnabled(False)
                self.record_panel.free_btn.setEnabled(False)
