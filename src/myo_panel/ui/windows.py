# windows.py  (only showing the changes / additions)
from PySide6.QtWidgets import (QMainWindow, QToolBar, QLabel,
                               QStatusBar, QWidget, QHBoxLayout, QVBoxLayout,
                               QMenu)
from PySide6.QtGui import QAction
from PySide6.QtCore import QTimer, Qt
from .plots import EMGGrid
from .recording import RecordingPanel
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtCore import QUrl

import asyncio

from collections import deque
import numpy as np

FRAME_UPDATE_INTERVAL = 100
BATTERY_CHECK_INTERVAL = 5000

class MainWindow(QMainWindow):
    def __init__(self, myo_mgr):
        super().__init__()
        self.myo = myo_mgr
        self._frame_q = deque(maxlen=500)
        self.setWindowTitle("Myo Panel")

        # ---- top toolbar (buttons & mode selectors) ----
        tb = QToolBar()
        self.addToolBar(tb)

        self.scan_act   = tb.addAction("Scan")
        self.disc_act   = tb.addAction("Disconnect")
        self.reset_act  = tb.addAction("Turn Off")
        self.vib_act    = tb.addAction("Vibrate")
        tb.addSeparator()
        self.pause_act  = tb.addAction("Pause Stream")
        self._paused = False   

        # connect toolbar actions to handlers
        self.scan_act.triggered.connect(self._scan_devices)
        self.disc_act.triggered.connect(self._disconnect)
        self.reset_act.triggered.connect(self._turn_off)
        self.vib_act.triggered.connect(lambda: self.myo.vibrate_async("medium"))
        self.pause_act.triggered.connect(self._toggle_pause)
        self.disc_act.setEnabled(False)      

        # Options pop-over
        opt_menu = QMenu(self)
        chart_size = opt_menu.addAction("Chart size 50 %")
        merge_2    = opt_menu.addAction("Merge x2")
        merge_4    = opt_menu.addAction("Merge x4")
        self.options_act = QAction("Options ⚙️", self)
        self.options_act.setMenu(opt_menu)
        tb.addAction(self.options_act)

        # ---- central splitter: EMG grid | recording+IMU ----
        central = QWidget(); h = QHBoxLayout(central)
        self.emg = EMGGrid()
        h.addWidget(self.emg, 2)

        right = QVBoxLayout()
        self.record_panel = RecordingPanel()
        right.addWidget(self.record_panel)

        self.imu = QQuickWidget()
        self.imu.setSource(QUrl.fromLocalFile("src/myo_panel/ui/qml/Cube.qml"))
        self.imu.setResizeMode(QQuickWidget.SizeRootObjectToView)
        right.addWidget(self.imu, 1)
        h.addLayout(right, 1)
        self.setCentralWidget(central)

        # ---- status bar ----
        sb = QStatusBar(); self.setStatusBar(sb)
        self.status_lbl  = QLabel("Disconnected"); sb.addWidget(self.status_lbl)
        self.batt_lbl    = QLabel("Battery: -- %"); sb.addPermanentWidget(self.batt_lbl)

        # ---- timers ----
        QTimer(self, interval=FRAME_UPDATE_INTERVAL, timeout=self._refresh_plots).start()     
        QTimer(self, interval=BATTERY_CHECK_INTERVAL, timeout=self._query_battery).start()


    def _refresh_plots(self):
        if self._paused or not self._frame_q:
            return
        # process **latest** max 20 frames, drop older to keep UI snappy
        take = min(len(self._frame_q), 20)
        frames = [self._frame_q.pop() for _ in range(take)]
        frames.reverse()                       # preserve order
        self.emg.push_frames(np.array(frames).T)   # shape (8, N)
        self.emg.refresh()

    # ------------------------------------------------------------------ BLE hooks
    def on_emg(self, _bank, two_frames):
        if not self._paused:
            self._frame_q.append(two_frames[0])
            self._frame_q.append(two_frames[1])

    def _query_battery(self):
        self.myo.refresh_battery_async()
        QTimer.singleShot(100, self._update_batt_lbl)

    def _update_batt_lbl(self):
        v = self.myo.battery
        self.batt_lbl.setText(f"Battery: {v:>3d} %" if v is not None else "Battery: -- %")

    # ------------------------------------------------------------------ scan / connect
    def _scan_devices(self):
        """Run blocking scan() in thread-pool; then show a pick-list."""
        self.status_lbl.setText("Scanning…")

        async def _do():
            loop = asyncio.get_running_loop()
            devs = await loop.run_in_executor(None, self.myo.scan)
            if not devs:
                self.status_lbl.setText("No MYO found")
                return

            # build a QInputDialog instance so we can rename the OK button
            from PySide6.QtWidgets import QInputDialog, QDialog
            items = [f"{d['name']}  ({d['address']})" for d in devs]
            dlg = QInputDialog(self)
            dlg.setWindowTitle("Select MYO")
            dlg.setLabelText("Choose device:")
            dlg.setComboBoxItems(items)
            dlg.setOkButtonText("Connect")
            dlg.setCancelButtonText("Cancel")

            if dlg.exec() != QDialog.Accepted:
                self.status_lbl.setText("Scan cancelled")
                return

            choice = dlg.textValue()
            idx = items.index(choice)
            addr = devs[idx]["address"]

            # --- connect in background ---
            self.status_lbl.setText("Connecting…")
            try:
                await loop.run_in_executor(
                    None, lambda: self.myo.connect(addr))
                self.current_dev = devs[idx]["name"]
                self.status_lbl.setText(f"Streaming from {self.current_dev}")
                self.disc_act.setEnabled(True)
            except Exception as exc:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Connect failed", str(exc))
                self.status_lbl.setText("Disconnected")

        asyncio.create_task(_do())

    # ------------------------------------------------------------------ manual disconnect
    def _disconnect(self):
        self.disc_act.setEnabled(False)
        self.status_lbl.setText("Disconnecting…")
        self.myo.disconnect_async()
        # give Bleak a moment, then update label
        QTimer.singleShot(300, lambda: self.status_lbl.setText("Disconnected"))

    # ------------------------------------------------------------------ turn off (deep-sleep)
    def _turn_off(self):
        self.status_lbl.setText("Turning off…")
        self.myo.deep_sleep_async()
        self.disc_act.setEnabled(False)
        QTimer.singleShot(600, lambda: self.status_lbl.setText("Disconnected"))

    # ------------------------------------------------------------------ pause / resume plotting
    def _toggle_pause(self):
        self._paused = not self._paused
        self.pause_act.setText("Resume Stream" if self._paused else "Pause Stream")
        # clear backlog so we don’t dump a huge burst when resuming
        if self._paused:
            self._frame_q.clear()