# recording.py
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QLabel, QLineEdit,
                               QCheckBox, QPushButton, QSpinBox, QHBoxLayout)

class RecordingPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Data Collection", parent)
        v = QVBoxLayout(self)

        self.path_edit  = QLineEdit(placeholderText="Save path")
        self.label_edit = QLineEdit(placeholderText="Label")
        self.raw_chk    = QCheckBox("Raw hex output")
        h = QHBoxLayout()
        self.timer_btn  = QPushButton("Timed Record")
        self.timer_sec  = QSpinBox(minimum=1, maximum=600, value=5)
        self.free_btn   = QPushButton("Free Record")
        for w in (self.timer_btn, self.timer_sec, self.free_btn): h.addWidget(w)

        v.addWidget(QLabel("Save Path"));  v.addWidget(self.path_edit)
        v.addWidget(QLabel("Label"));      v.addWidget(self.label_edit)
        v.addWidget(self.raw_chk)
        v.addLayout(h)

        self.rec_indicator = QLabel("● Recording")
        self.rec_indicator.setStyleSheet("color: red;")
        self.rec_indicator.setVisible(False)
        v.addWidget(self.rec_indicator)
