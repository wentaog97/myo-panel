"""Recording panel for data collection."""
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
        super().__init__(parent)
        self.myo = myo_manager
        v = QVBoxLayout(self)

        # buffer for CSV export and IMU samples
        self._recording = []  # Main recording buffer
        self._last_imu = {    # Cache the latest IMU data
            "quat": None,
            "acc": None,
            "gyro": None
        }

        # Path field and browse button
        path_layout = QHBoxLayout()
        # Set default save path to workspace_root/output
        default_save_path = os.path.join(os.getcwd(), "output") 
        self.path_edit = QLineEdit(placeholderText="Save path", text=default_save_path)
        self.browse_btn = QPushButton("📁")
        self.browse_btn.setFixedWidth(30)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_btn)

        # Combine gesture, limb, and side into one line
        gesture_layout = QHBoxLayout()
        
        gesture_group = QVBoxLayout()
        gesture_group.addWidget(QLabel("Gesture"))
        self.gesture_edit = QLineEdit(placeholderText="e.g. fist")
        gesture_group.addWidget(self.gesture_edit)
        gesture_layout.addLayout(gesture_group)
        
        limb_group = QVBoxLayout()
        limb_group.addWidget(QLabel("Limb"))
        self.limb_edit = QLineEdit(placeholderText="e.g. arm/leg")
        limb_group.addWidget(self.limb_edit)
        gesture_layout.addLayout(limb_group)

        side_group_box = QVBoxLayout()
        side_group_box.addWidget(QLabel("Side"))
        self.side_group = QButtonGroup()
        side_radio_layout = QHBoxLayout()
        self.left_radio = QRadioButton("Left")
        self.right_radio = QRadioButton("Right")
        self.left_radio.setChecked(True)
        side_radio_layout.addWidget(self.left_radio)
        side_radio_layout.addWidget(self.right_radio)
        for r in (self.left_radio, self.right_radio): self.side_group.addButton(r)
        side_group_box.addLayout(side_radio_layout)
        gesture_layout.addLayout(side_group_box)

        # Combine output format and raw hex checkbox into one line
        output_layout = QHBoxLayout()
        
        format_group = QVBoxLayout()
        format_group.addWidget(QLabel("Output Format"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["CSV", "PKL"])
        format_group.addWidget(self.format_combo)
        output_layout.addLayout(format_group)
        
        raw_group = QVBoxLayout()
        raw_group.addWidget(QLabel("Output Type"))
        types_layout = QHBoxLayout()
        self.raw_chk = QCheckBox("Raw hex output")
        self.enable_vision_chk = QCheckBox("Enable CV")
        self.enable_vision_chk.setChecked(False)
        types_layout.addWidget(self.raw_chk)
        types_layout.addWidget(self.enable_vision_chk)
        raw_group.addLayout(types_layout)
        output_layout.addLayout(raw_group)

        # Buttons
        h = QHBoxLayout()
        self.timer_btn = QPushButton("Timed Record")
        self.timer_sec = QSpinBox(minimum=1, maximum=600, value=5)
        self.free_btn  = QPushButton("Free Record")
        for w in (self.timer_btn, self.timer_sec, self.free_btn): h.addWidget(w)

        v.addWidget(QLabel("Save Path"))
        v.addLayout(path_layout)
        v.addLayout(gesture_layout)
        v.addLayout(output_layout)
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
        directory = QFileDialog.getExistingDirectory(self, "Select Save Directory", "")
        if directory:
            self.path_edit.setText(directory)

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
        self._last_imu = {
            "quat": None,
            "acc": None,
            "gyro": None
        }
        self._active = True
        self.rec_indicator.setVisible(True)
        
        # Start vision recording if enabled
        if self.enable_vision_chk.isChecked():
            # Get the parent window to access vision recorder
            parent = self.window()
            if parent and hasattr(parent, "vision_recording") and parent.vision_recording:
                try:
                    # Safely call _start_recording method if it exists
                    if hasattr(parent.vision_recording, "_start_recording"):
                        parent.vision_recording._start_recording()
                    else:
                        print("[Recorder] Warning: vision_recording has no _start_recording method")
                except Exception as e:
                    print(f"[Recorder] Error starting vision recording: {e}")

    def _stop_recording(self):
        self._active = False
        self.rec_indicator.setVisible(False)
        
        # Stop vision recording if it was started
        parent = self.window()
        if parent and hasattr(parent, "vision_recording") and parent.vision_recording:
            # Check if recording attribute exists first
            if hasattr(parent.vision_recording, "recording") and parent.vision_recording.recording:
                try:
                    # Safely call _stop_recording method
                    if hasattr(parent.vision_recording, "_stop_recording"):
                        parent.vision_recording._stop_recording()
                    else:
                        print("[Recorder] Warning: vision_recording has no _stop_recording method")
                except Exception as e:
                    print(f"[Recorder] Error stopping vision recording: {e}")
                
        self._save_file()

    def push_frame(self, frame: list[int], timestamp=None, raw_hex=None):
        """Called by the UI to record one EMG frame."""
        if not getattr(self, "_active", False):
            return
        ts = timestamp or int(time.time() * 1000000)
        label = self.gesture_edit.text().strip() or "unlabeled"

        # Get vision data if enabled
        vision_data = None
        if self.enable_vision_chk.isChecked():
            parent = self.window()
            if parent and hasattr(parent, "vision_recording") and parent.vision_recording:
                try:
                    # Get latest landmarks data from the vision_recording
                    landmarks = parent.vision_recording.get_latest_landmarks()
                    # Process landmarks into a more structured format for CSV export
                    if landmarks and "hands" in landmarks and landmarks["hands"]:
                        vision_data = landmarks
                except Exception as e:
                    print(f"[Recorder] Error getting vision data: {e}")

        if self.raw_chk.isChecked() and raw_hex:
            # Store raw hex data
            self._recording.append({
                "timestamp": ts,
                "type": "EMG",
                "raw_hex": raw_hex,
                "label": label,
                "vision": vision_data
            })
        elif frame is not None:
            # Store processed data with current IMU state
            self._recording.append({
                "timestamp": ts,
                "emg": frame.copy(),
                "imu": self._last_imu.copy(),
                "label": label,
                "vision": vision_data
            })

    def push_imu(self, quat, acc, gyro, timestamp=None, raw_hex=None):
        """Called by the UI to record one IMU sample."""
        if not getattr(self, "_active", False):
            return
        ts = timestamp or int(time.time() * 1000000)
        label = self.gesture_edit.text().strip() or "unlabeled"

        # Update last IMU state
        self._last_imu = {
            "quat": list(quat) if quat is not None else None,
            "acc": list(acc) if acc is not None else None,
            "gyro": list(gyro) if gyro is not None else None
        }

        if self.raw_chk.isChecked() and raw_hex:
            # Store raw hex data
            self._recording.append({
                "timestamp": ts,
                "type": "IMU",
                "raw_hex": raw_hex,
                "label": label
            })

    def _save_file(self):
        directory = self.path_edit.text().strip()
        if not directory:
            print("[Recorder] No directory provided.")
            return

        # Construct filename
        now = datetime.datetime.now()
        datetime_str = now.strftime("%Y%m%d_%H%M%S")
        
        base_filename = f"myo_data_{datetime_str}"
        
        gesture = self.gesture_edit.text().strip()
        if gesture:
            base_filename += f"_{gesture.replace(' ', '_')}"
            
        limb = self.limb_edit.text().strip()
        if limb:
            base_filename += f"_{limb.replace(' ', '_')}"
            
        side = "left" if self.left_radio.isChecked() else "right"
        base_filename += f"_{side}"
        
        ext = self.format_combo.currentText().lower()
        filename = f"{base_filename}.{ext}"
        
        path = os.path.join(directory, filename)

        meta = {
            "gesture": gesture,
            "limb": limb,
            "side": side,
            "timestamp": now.isoformat(),
            "format": ext,
            "filename": filename # Add constructed filename to meta
        }

        try:
            if ext == "csv":
                with open(path, "w", newline="") as f:
                    # Write metadata
                    f.write(f"# Recording started: {meta['timestamp']}\n")
                    f.write(f"# Gesture: {meta['gesture']}\n")
                    f.write(f"# Limb: {meta['limb']}\n")
                    f.write(f"# Side: {meta['side']}\n")
                    
                    # Write device info
                    if hasattr(self.myo, 'firmware') and self.myo.firmware is not None:
                        f.write(f"# Firmware: {self.myo.firmware}\n")
                    else:
                        f.write("# Firmware: unknown\n")
                        
                    if hasattr(self.myo, 'model_name') and self.myo.model_name is not None:
                        f.write(f"# Model: {self.myo.model_name}\n")
                    else:
                        f.write("# Model: unknown\n")
                        
                    # Write EMG/IMU modes
                    f.write(f"# EMG Mode: {getattr(self.myo, '_emg_mode', 'unknown')}\n")
                    f.write(f"# IMU Mode: {getattr(self.myo, '_imu_mode', 'unknown')}\n")

                    writer = csv.writer(f)
                    if self.raw_chk.isChecked():
                        # Write raw hex data
                        f.write("# Format: timestamp,type,raw_hex,label\n")
                        writer.writerow(["timestamp", "type", "raw_hex", "label"])
                        for row in self._recording:
                            writer.writerow([
                                row["timestamp"],
                                row["type"],
                                row["raw_hex"],
                                row["label"]
                            ])
                    else:
                        # Write processed data with EMG and IMU together
                        f.write("# Format: timestamp," + 
                               ",".join(f"emg_{i}" for i in range(8)) +
                               ",quat_w,quat_x,quat_y,quat_z," +
                               "acc_x,acc_y,acc_z," +
                               "gyro_x,gyro_y,gyro_z,label" +
                               ",hand_count,hand1_type" +
                               "".join([f",hand1_landmark{i}_x,hand1_landmark{i}_y,hand1_landmark{i}_z" for i in range(21)]) +
                               ",hand2_type" +
                               "".join([f",hand2_landmark{i}_x,hand2_landmark{i}_y,hand2_landmark{i}_z" for i in range(21)]) +
                               "\n")
                        
                        # Write processed data with EMG and IMU together
                        # Add comment explaining vision data format
                        f.write("# Vision landmark data: hand_count is the number of detected hands (0, 1, or 2).\n")
                        f.write("# Each hand has 21 landmarks representing finger joints and palm features.\n")
                        f.write("# For each landmark, x and y are normalized to [0.0, 1.0] within image coordinates.\n")
                        f.write("# z represents depth (smaller values are closer to camera).\n")
                        f.write("# Format: timestamp," + 
                               ",".join(f"emg_{i}" for i in range(8)) +
                               ",quat_w,quat_x,quat_y,quat_z," +
                               "acc_x,acc_y,acc_z," +
                               "gyro_x,gyro_y,gyro_z,label" +
                               ",hand_count,hand1_type" +
                               "".join([f",hand1_landmark{i}_x,hand1_landmark{i}_y,hand1_landmark{i}_z" for i in range(21)]) +
                               ",hand2_type" +
                               "".join([f",hand2_landmark{i}_x,hand2_landmark{i}_y,hand2_landmark{i}_z" for i in range(21)]) +
                               "\n")

                        writer.writerow(
                            ["timestamp"] +
                            [f"emg_{i}" for i in range(8)] +
                            ["quat_w", "quat_x", "quat_y", "quat_z"] +
                            ["acc_x", "acc_y", "acc_z"] +
                            ["gyro_x", "gyro_y", "gyro_z"] +
                            ["label"] +
                            ["hand_count", "hand1_type"] +
                            [f"hand1_landmark{i}_{coord}" for i in range(21) for coord in ["x", "y", "z"]] +
                            ["hand2_type"] +
                            [f"hand2_landmark{i}_{coord}" for i in range(21) for coord in ["x", "y", "z"]]
                        )

                        for row in self._recording:
                            if "raw_hex" not in row:  # Skip raw hex entries
                                data = [row["timestamp"]]
                                data.extend(row["emg"])
                                
                                # Add IMU data
                                imu = row["imu"]
                                # Add quaternion data
                                if imu["quat"] and len(imu["quat"]) == 4:
                                    data.extend(imu["quat"])
                                else:
                                    data.extend([""]*4)
                                # Add accelerometer data
                                if imu["acc"] and len(imu["acc"]) == 3:
                                    data.extend(imu["acc"])
                                else:
                                    data.extend([""]*3)
                                # Add gyroscope data
                                if imu["gyro"] and len(imu["gyro"]) == 3:
                                    data.extend(imu["gyro"])
                                else:
                                    data.extend([""]*3)
                                
                                # Add label
                                data.append(row["label"])
                                
                                # Process vision data
                                # Default empty values for hand data
                                hand_count = 0
                                hand1_type = ""
                                hand1_landmarks = [""] * (21 * 3)  # 21 landmarks * (x,y,z)
                                hand2_type = ""
                                hand2_landmarks = [""] * (21 * 3)

                                # Add vision data if available
                                if "vision" in row and row["vision"]:
                                    vision = row["vision"]
                                    
                                    # Extract hand data
                                    if "hands" in vision and vision["hands"]:
                                        hands = vision["hands"]
                                        hand_count = len(hands)
                                        
                                        if hand_count > 0:
                                            # First hand data
                                            hand1 = hands[0]
                                            hand1_type = hand1["type"]
                                            landmarks = hand1["landmarks"]
                                            for i, lm in enumerate(landmarks[:21]):  # Ensure we only use up to 21 landmarks
                                                idx = i * 3
                                                hand1_landmarks[idx] = lm["x"]
                                                hand1_landmarks[idx + 1] = lm["y"]
                                                hand1_landmarks[idx + 2] = lm["z"]
                                        
                                        if hand_count > 1:
                                            # Second hand data
                                            hand2 = hands[1]
                                            hand2_type = hand2["type"]
                                            landmarks = hand2["landmarks"]
                                            for i, lm in enumerate(landmarks[:21]):  # Ensure we only use up to 21 landmarks
                                                idx = i * 3
                                                hand2_landmarks[idx] = lm["x"]
                                                hand2_landmarks[idx + 1] = lm["y"]
                                                hand2_landmarks[idx + 2] = lm["z"]
                                
                                # Add vision data to CSV row
                                data.append(hand_count)
                                data.append(hand1_type)
                                data.extend(hand1_landmarks)
                                data.append(hand2_type)
                                data.extend(hand2_landmarks)

                                writer.writerow(data)
            else:
                # Save as pickle with all data
                with open(path, "wb") as f:
                    # Include device info in metadata
                    meta.update({
                        "firmware": self.myo.firmware if hasattr(self.myo, 'firmware') else None,
                        "model": self.myo.model_name if hasattr(self.myo, 'model_name') else None,
                        "emg_mode": getattr(self.myo, '_emg_mode', None),
                        "imu_mode": getattr(self.myo, '_imu_mode', None),
                        "vision_enabled": self.enable_vision_chk.isChecked()
                    })
                    pickle.dump({
                        "metadata": meta,
                        "recording": self._recording
                    }, f)
            print(f"[Recorder] Saved {len([r for r in self._recording if 'raw_hex' not in r])} frames to {path}")
        except Exception as e:
            print("[Recorder] Save failed:", e)
            import traceback
            traceback.print_exc()
