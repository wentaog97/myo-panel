# windows.py
from PySide6.QtWidgets import (QMainWindow, QToolBar, QLabel, QStatusBar,
                               QWidget, QHBoxLayout, QVBoxLayout, QMenu, QToolButton)
from PySide6.QtGui     import QAction, QActionGroup
from PySide6.QtCore import QTimer, Qt
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtCore import QUrl
import asyncio, numpy as np
from collections import deque

from .plots import _Ring, EMGGrid, EMGComposite
from .recording import RecordingPanel

FRAME_UPDATE_INTERVAL   = 100   # ms
BATTERY_CHECK_INTERVAL  = 5000  # ms

class MainWindow(QMainWindow):
    def __init__(self, myo_mgr):
        super().__init__()
        self.myo = myo_mgr
        self._frame_q = deque(maxlen=500)
        self._ring    = _Ring()
        self._paused  = False
        self.setWindowTitle("Myo Panel")

        # ── top toolbar ────────────────────────────────────────────────
        tb = QToolBar()
        self.addToolBar(tb)

        self.scan_act  = tb.addAction("Scan")
        self.disc_act  = tb.addAction("Disconnect"); self.disc_act.setEnabled(False)
        self.off_act   = tb.addAction("Turn Off"); self.off_act.setEnabled(False)

        # Vibrate button (medium by default)
        self.vib_act   = tb.addAction("Vibrate"); self.vib_act.setEnabled(False)
        tb.addSeparator()
        self.pause_act = tb.addAction("Pause Stream")

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

        #  View-mode sub-menu with radio items
        view_menu  = opt_menu.addMenu("View mode")
        view_group = QActionGroup(self); view_group.setExclusive(True)
        act_split  = QAction("Split channel view", self, checkable=True); act_split.setChecked(True)
        act_comp   = QAction("Composite view",     self, checkable=True)
        for a in (act_split, act_comp):
            view_group.addAction(a); view_menu.addAction(a)
        view_group.triggered.connect(lambda a: self._show_split(a is act_split))

        opt_btn = QToolButton()
        opt_btn.setText("Options")
        opt_btn.setPopupMode(QToolButton.InstantPopup)
        opt_btn.setMenu(opt_menu)
        tb.addWidget(opt_btn)

        # ── central area: two plot widgets we toggle ──────────────────
        central = QWidget(); h = QHBoxLayout(central)
        self.grid_view = EMGGrid(self._ring)
        self.comp_view = EMGComposite(self._ring); self.comp_view.hide()
        h.addWidget(self.grid_view, 2); h.addWidget(self.comp_view, 2)

        right = QVBoxLayout()
        self.record_panel = RecordingPanel(self.myo); right.addWidget(self.record_panel)

        # IMU cube
        self.imu = QQuickWidget()
        self.imu.setSource(QUrl.fromLocalFile("src/myo_panel/ui/qml/Cube.qml"))
        self.imu.setResizeMode(QQuickWidget.SizeRootObjectToView)
        right.addWidget(self.imu, 1)

        h.addLayout(right, 1); self.setCentralWidget(central)

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

    # ───────────────────────────────────────────────────────────────────
    def _refresh_plots(self):
        if self._paused or not self._frame_q:
            return
        take = min(len(self._frame_q), 20)
        frames = [self._frame_q.pop() for _ in range(take)][::-1]   # preserve order
        self._ring.insert(np.array(frames).T)
        for f in frames:
            self.record_panel.push_frame(f)
        (self.grid_view if self.grid_view.isVisible() else self.comp_view).refresh()

    # ------------- BLE stream callback -------------------------------
    def on_emg(self, _bank, two_frames):
        if not self._paused:
            self._frame_q.append(two_frames[0]); self._frame_q.append(two_frames[1])

    # ------------- IMU callback ------------------------------------
    def _on_imu(self, quat, acc, gyro, timestamp=None, raw_hex=None):
        """Handle IMU data for both visualization and recording."""
        # Update 3D visualization
        if quat is not None and hasattr(self.imu, 'rootObject'):
            root = self.imu.rootObject()
            if root:
                root.setRotation(quat[0], quat[1], quat[2], quat[3])
        
        # Record IMU data
        self.record_panel.push_imu(quat, acc, gyro, timestamp, raw_hex)

    # ------------- battery polling -----------------------------------
    def _query_battery(self):
        self.myo.refresh_battery_async()
        QTimer.singleShot(100, lambda: self.batt_lbl.setText(
            f"Battery: {self.myo.battery:>3d} %" if self.myo.battery is not None else "Battery: -- %"))

    # ------------- scan + connect ------------------------------------
    def _scan_connect(self):
        self.status_lbl.setText("Scanning…")
        async def _do():
            loop = asyncio.get_running_loop()
            devs = await loop.run_in_executor(None, self.myo.scan)
            if not devs:
                self.status_lbl.setText("No MYO found"); return

            from PySide6.QtWidgets import QInputDialog, QDialog
            items = [f"{d['name']} ({d['address']})" for d in devs]
            dlg = QInputDialog(self)
            dlg.setWindowTitle("Select MYO")
            dlg.setLabelText("Select a Myo device:")
            dlg.setComboBoxItems(items)
            dlg.setOkButtonText("Connect")
            dlg.setCancelButtonText("Cancel")
            if dlg.exec() != QDialog.Accepted: self.status_lbl.setText("Scan cancelled"); return

            idx = items.index(dlg.textValue()); addr, name = devs[idx]["address"], devs[idx]["name"]
            self.status_lbl.setText("Connecting…")
            try:
                await loop.run_in_executor(None, lambda: self.myo.connect(addr))
                self.status_lbl.setText(f"Streaming from {name}")
                # enable controls now that we're connected
                self.disc_act.setEnabled(True)
                self.off_act.setEnabled(True)
                self.vib_act.setEnabled(True)
            except Exception as exc:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Connect failed", str(exc))
                self.status_lbl.setText("Disconnected")
        asyncio.create_task(_do())

    # ------------- manual disconnect ---------------------------------
    def _disconnect(self):
        # disable all controls when disconnected
        self.disc_act.setEnabled(False)
        self.off_act.setEnabled(False)
        self.vib_act.setEnabled(False)
        self.status_lbl.setText("Disconnecting…")
        self.myo.disconnect_async()
        QTimer.singleShot(300, lambda: self.status_lbl.setText("Disconnected"))

    # ------------- turn off (deep-sleep) ------------------------------
    def _turn_off(self):
        self.status_lbl.setText("Turning off…"); self.myo.deep_sleep_async()
        # after deep sleep there's no MYO, so disable controls
        self.disc_act.setEnabled(False)
        self.off_act.setEnabled(False)
        self.vib_act.setEnabled(False)
        QTimer.singleShot(600, lambda: self.status_lbl.setText("Disconnected"))

    # ------------- pause / resume ------------------------------------
    def _toggle_pause(self):
        self._paused = not self._paused
        self.pause_act.setText("Resume Stream" if self._paused else "Pause Stream")
        if self._paused: self._frame_q.clear()

    # ------------- view switching ------------------------------------
    def _show_split(self, split: bool):
        self.grid_view.setVisible(split); self.comp_view.setVisible(not split)
