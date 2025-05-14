# windows.py
from PySide6.QtWidgets import (QMainWindow, QToolBar, QLabel, QStatusBar,
                               QWidget, QHBoxLayout, QVBoxLayout, QMenu, QToolButton,
                               QDockWidget)
from PySide6.QtGui     import QAction, QActionGroup
from PySide6.QtCore import QTimer, Qt
import asyncio, numpy as np
from collections import deque

from .plots import _Ring, EMGGrid, EMGComposite
from .recording import RecordingPanel
from .imu_viz import MatplotlibIMUCube

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
        self.setWindowTitle("Myo Panel")

        # Initialize EMG and IMU modes
        self._emg_mode = 3  # EMG_MODE_SEND_RAW
        self._imu_mode = 1  # IMU_MODE_SEND_DATA
        self.myo._emg_mode = self._emg_mode
        self.myo._imu_mode = self._imu_mode

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
        
        view_menu.addAction(self.show_emg_act)
        view_menu.addAction(self.show_rec_act)
        view_menu.addAction(self.show_imu_act)
        
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

        opt_btn = QToolButton()
        opt_btn.setText("Options")
        opt_btn.setPopupMode(QToolButton.InstantPopup)
        opt_btn.setMenu(opt_menu)
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
        
        async def _do():
            try:
                loop = asyncio.get_running_loop()
                devs = await loop.run_in_executor(None, self.myo.scan)
                
                # Reset scanning state if no devices found
                if not devs:
                    self.status_lbl.setText("No MYO found")
                    self._scanning = False
                    self.scan_act.setEnabled(True)
                    return

                from PySide6.QtWidgets import QInputDialog, QDialog
                items = [f"{d['name']} ({d['address']})" for d in devs]
                dlg = QInputDialog(self)
                dlg.setWindowTitle("Select MYO")
                dlg.setLabelText("Select a Myo device:")
                dlg.setComboBoxItems(items)
                dlg.setOkButtonText("Connect")
                dlg.setCancelButtonText("Cancel")
                
                # Reset scanning state if dialog is cancelled
                if dlg.exec() != QDialog.Accepted:
                    self.status_lbl.setText("Scan cancelled")
                    self._scanning = False
                    self.scan_act.setEnabled(True)
                    return

                idx = items.index(dlg.textValue())
                addr, name = devs[idx]["address"], devs[idx]["name"]
                self.status_lbl.setText("Connecting…")
                
                try:
                    # Use the configured EMG and IMU modes
                    await loop.run_in_executor(None, lambda: self.myo.connect(addr, emg_mode=self._emg_mode, imu_mode=self._imu_mode))
                    self.status_lbl.setText(f"Streaming from {name}")
                    
                    # Enable controls now that we're connected
                    self.disc_act.setEnabled(True)
                    self.off_act.setEnabled(True)
                    self.vib_act.setEnabled(True)
                    self.pause_act.setEnabled(True)
                    self.record_panel.timer_btn.setEnabled(True)
                    self.record_panel.free_btn.setEnabled(True)
                    
                    # Keep Scan button disabled when connected
                    self.scan_act.setEnabled(False)
                    
                    # Update status with current modes
                    QTimer.singleShot(500, self._update_mode_status)
                except Exception as exc:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.critical(self, "Connect failed", str(exc))
                    self.status_lbl.setText("Disconnected")
                    # Enable scan button on connection failure
                    self._scanning = False
                    self.scan_act.setEnabled(True)
            finally:
                # Only reset scanning state when not successfully connected
                if not self.myo.connected:
                    self._scanning = False
                    self.scan_act.setEnabled(True)
                
        asyncio.create_task(_do())

    # ------------- manual disconnect ---------------------------------
    def _disconnect(self):
        # Disable all controls when disconnected
        self.disc_act.setEnabled(False)
        self.off_act.setEnabled(False)
        self.vib_act.setEnabled(False)
        self.pause_act.setEnabled(False)
        self.record_panel.timer_btn.setEnabled(False)
        self.record_panel.free_btn.setEnabled(False)
        
        # Reset pause state if active
        if self._paused:
            self._paused = False
            self.pause_act.setText("Pause Stream")
            
        self.status_lbl.setText("Disconnecting…")
        self.myo.disconnect_async()
        
        # Enable scan button again
        self._scanning = False
        self.scan_act.setEnabled(True)
        
        QTimer.singleShot(300, lambda: self.status_lbl.setText("Disconnected"))

    # ------------- turn off (deep-sleep) ------------------------------
    def _turn_off(self):
        self.status_lbl.setText("Turning off…")
        self.myo.deep_sleep_async()
        
        # After deep sleep there's no MYO, so disable controls
        self.disc_act.setEnabled(False)
        self.off_act.setEnabled(False)
        self.vib_act.setEnabled(False)
        self.pause_act.setEnabled(False)
        self.record_panel.timer_btn.setEnabled(False)
        self.record_panel.free_btn.setEnabled(False)
        
        # Reset pause state if active
        if self._paused:
            self._paused = False
            self.pause_act.setText("Pause Stream")
        
        # Enable scan button again
        self._scanning = False
        self.scan_act.setEnabled(True)
            
        QTimer.singleShot(600, lambda: self.status_lbl.setText("Disconnected"))

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
        
        self.status_lbl.setText(f"Connected | EMG: {emg_mode_text} | IMU: {imu_mode_text}")
