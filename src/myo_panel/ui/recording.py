from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QLineEdit,
    QCheckBox, QPushButton, QSpinBox, QHBoxLayout,
    QFileDialog, QComboBox, QRadioButton, QButtonGroup
)
from PySide6.QtCore import QTimer
import datetime, os, csv, pickle
import time
import numpy as np

class RecordingPanel(QGroupBox):
    def __init__(self, myo_manager, parent=None):
        super().__init__("Data Collection", parent)
        self.myo = myo_manager
        v = QVBoxLayout(self)

        # buffer for CSV export and IMU samples
        self._recording: list[dict] = []
        self._emg_buffer = []
        self._imu_buffer = []
        self._last_imu = {
            "quat": None,
            "acc": None,
            "gyro": None
        }

        # Path field and browse button
        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(placeholderText="Save path")
        self.browse_btn = QPushButton("📁")
        self.browse_btn.setFixedWidth(30)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_btn)

        self.gesture_edit = QLineEdit(placeholderText="e.g. fist")
        self.limb_edit = QLineEdit(placeholderText="e.g. arm/leg")

        self.side_group = QButtonGroup()
        self.left_radio = QRadioButton("Left"); self.right_radio = QRadioButton("Right")
        self.left_radio.setChecked(True)
        side_layout = QHBoxLayout()
        side_layout.addWidget(QLabel("Side:"))
        side_layout.addWidget(self.left_radio)
        side_layout.addWidget(self.right_radio)
        for r in (self.left_radio, self.right_radio): self.side_group.addButton(r)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["CSV", "PKL"])

        self.raw_chk = QCheckBox("Raw hex output")

        # Buttons
        h = QHBoxLayout()
        self.timer_btn = QPushButton("Timed Record")
        self.timer_sec = QSpinBox(minimum=1, maximum=600, value=5)
        self.free_btn  = QPushButton("Free Record")
        for w in (self.timer_btn, self.timer_sec, self.free_btn): h.addWidget(w)

        v.addWidget(QLabel("Save Path"));     v.addLayout(path_layout)
        v.addWidget(QLabel("Gesture"));       v.addWidget(self.gesture_edit)
        v.addWidget(QLabel("Limb"));          v.addWidget(self.limb_edit)
        v.addLayout(side_layout)
        v.addWidget(QLabel("Output Format")); v.addWidget(self.format_combo)
        v.addWidget(self.raw_chk)
        v.addLayout(h)

        self.rec_indicator = QLabel("● Recording")
        self.rec_indicator.setStyleSheet("color: red;")
        self.rec_indicator.setVisible(False)
        v.addWidget(self.rec_indicator)

        # Wire file dialog
        self.browse_btn.clicked.connect(self._choose_path)
        self._active = False

        self.timer_btn.clicked.connect(self._start_timed)
        self.free_btn.clicked.connect(self._toggle_free)

    def _choose_path(self):
        file, _ = QFileDialog.getSaveFileName(self, "Save File", "", "All Files (*)")
        if file:
            self.path_edit.setText(file)

    def _start_timed(self):
        self._start_recording()
        QTimer.singleShot(self.timer_sec.value() * 1000, self._stop_recording)

    def _toggle_free(self):
        if self._active:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        self._recording = []
        self._emg_buffer = []
        self._imu_buffer = []
        self._last_imu = {
            "quat": None,
            "acc": None,
            "gyro": None
        }
        self._active = True
        self.rec_indicator.setVisible(True)

    def _stop_recording(self):
        self._active = False
        self.rec_indicator.setVisible(False)
        self._save_file()

    def push_frame(self, frame: list[int], timestamp=None, raw_hex=None):
        """Called by the UI to record one EMG frame."""
        if not getattr(self, "_active", False):
            return
        ts = timestamp or int(time.time() * 1000)
        label = self.gesture_edit.text().strip() or "unlabeled"

        # Store EMG frame with timestamp
        if frame is not None:
            self._emg_buffer.append({
                "timestamp": ts,
                "emg": frame.copy(),
                "label": label
            })

        # Process and store in main recording buffer
        if self.format_combo.currentText().lower() == "csv":
            if self.raw_chk.isChecked() and raw_hex:
                # Use provided raw hex data
                self._recording.append({
                    "timestamp": ts,
                    "type": "EMG",
                    "raw_hex": raw_hex,
                    "label": label
                })
            elif not self.raw_chk.isChecked() and frame is not None:
                # Include latest IMU data with EMG frame
                self._recording.append({
                    "timestamp": ts,
                    "emg": frame.copy(),
                    "imu": self._last_imu.copy(),
                    "label": label
                })
        else:
            # Store raw data for pickle format
            if frame is not None:
                self._recording.append({
                    "timestamp": ts,
                    "emg": frame.copy(),
                    "imu": self._last_imu.copy(),
                    "label": label
                })

    def push_imu(self, quat, acc, gyro, timestamp=None, raw_hex=None):
        """Called by the UI to record one IMU sample."""
        if not getattr(self, "_active", False):
            return
        ts = timestamp or int(time.time() * 1000)
        label = self.gesture_edit.text().strip() or "unlabeled"
        
        # Update last IMU state - ensure we have lists/arrays
        self._last_imu = {
            "quat": list(quat) if quat is not None else None,
            "acc": list(acc) if acc is not None else None,
            "gyro": list(gyro) if gyro is not None else None
        }

        # Store IMU data with timestamp
        self._imu_buffer.append({
            "timestamp": ts,
            "quat": list(quat) if quat is not None else None,
            "acc": list(acc) if acc is not None else None,
            "gyro": list(gyro) if gyro is not None else None,
            "label": label
        })

        # Always record IMU data in raw hex mode if raw_hex is provided
        if self.format_combo.currentText().lower() == "csv" and self.raw_chk.isChecked():
            self._recording.append({
                "timestamp": ts,
                "type": "IMU",
                "raw_hex": raw_hex,
                "label": label
            })

    def _save_file(self):
        path = self.path_edit.text().strip()
        if not path:
            print("[Recorder] No path provided.")
            return

        meta = {
            "gesture": self.gesture_edit.text().strip(),
            "limb": self.limb_edit.text().strip(),
            "side": "left" if self.left_radio.isChecked() else "right",
            "timestamp": datetime.datetime.now().isoformat(),
            "format": self.format_combo.currentText().lower(),
        }

        ext = meta["format"]
        if not path.lower().endswith(f".{ext}"):
            path += f".{ext}"

        try:
            if ext == "csv":
                with open(path, "w", newline="") as f:
                    # Write metadata
                    f.write(f"# Recording started: {meta['timestamp']}\n")
                    f.write(f"# Gesture: {meta['gesture']}\n")
                    f.write(f"# Limb: {meta['limb']}\n")
                    f.write(f"# Side: {meta['side']}\n")
                    
                    # Write device info - handle missing attributes gracefully
                    if hasattr(self.myo, 'firmware') and self.myo.firmware is not None:
                        f.write(f"# Firmware: {self.myo.firmware}\n")
                    else:
                        f.write("# Firmware: unknown\n")
                        
                    if hasattr(self.myo, 'model_name') and self.myo.model_name is not None:
                        f.write(f"# Model: {self.myo.model_name}\n")
                    else:
                        f.write("# Model: unknown\n")
                        
                    # Write EMG/IMU modes - these are internal attributes
                    f.write(f"# EMG Mode: {getattr(self.myo, '_emg_mode', 'unknown')}\n")
                    f.write(f"# IMU Mode: {getattr(self.myo, '_imu_mode', 'unknown')}\n")

                    # Write data based on format
                    if self.raw_chk.isChecked():
                        f.write("# Format: timestamp,type,raw_hex,label\n")
                        writer = csv.writer(f)
                        writer.writerow(["timestamp", "type", "raw_hex", "label"])
                        for row in self._recording:
                            writer.writerow([
                                row["timestamp"],
                                row["type"],
                                row["raw_hex"],
                                row["label"]
                            ])
                    else:
                        f.write(
                            "# Format: timestamp,"
                            + ",".join(f"emg_{i}" for i in range(8))
                            + ",quat_w,quat_x,quat_y,quat_z,"
                              "acc_x,acc_y,acc_z,"
                              "gyro_x,gyro_y,gyro_z,label\n"
                        )
                        writer = csv.writer(f)
                        headers = (
                            ["timestamp"]
                            + [f"emg_{i}" for i in range(8)]
                            + ["quat_w", "quat_x", "quat_y", "quat_z"]
                            + ["acc_x", "acc_y", "acc_z"]
                            + ["gyro_x", "gyro_y", "gyro_z"]
                            + ["label"]
                        )
                        writer.writerow(headers)
                        for row in self._recording:
                            if "raw_hex" not in row:  # Skip raw hex entries
                                data = [row["timestamp"]]
                                data.extend(row["emg"])
                                
                                # Handle IMU data carefully
                                imu = row.get("imu", {})
                                quat_data = imu.get("quat", None)
                                acc_data = imu.get("acc", None)
                                gyro_data = imu.get("gyro", None)
                                
                                # Add quaternion data
                                if quat_data and len(quat_data) == 4:
                                    data.extend(quat_data)
                                else:
                                    data.extend([""]*4)
                                    
                                # Add accelerometer data
                                if acc_data and len(acc_data) == 3:
                                    data.extend(acc_data)
                                else:
                                    data.extend([""]*3)
                                    
                                # Add gyroscope data
                                if gyro_data and len(gyro_data) == 3:
                                    data.extend(gyro_data)
                                else:
                                    data.extend([""]*3)
                                
                                data.append(row["label"])
                                writer.writerow(data)
            else:
                # Save as pickle with all data
                with open(path, "wb") as f:
                    # Include device info in metadata
                    meta.update({
                        "firmware": self.myo.firmware if hasattr(self.myo, 'firmware') else None,
                        "model": self.myo.model_name if hasattr(self.myo, 'model_name') else None,
                        "emg_mode": getattr(self.myo, '_emg_mode', None),
                        "imu_mode": getattr(self.myo, '_imu_mode', None)
                    })
                    pickle.dump({
                        "metadata": meta,
                        "emg_data": self._emg_buffer,
                        "imu_data": self._imu_buffer,
                        "raw_recording": self._recording
                    }, f)
            print(f"[Recorder] Saved {len(self._recording)} frames to {path}")
        except Exception as e:
            print("[Recorder] Save failed:", e)
            # Print more detailed error info for debugging
            import traceback
            traceback.print_exc()
