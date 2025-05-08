# plots.py
from PySide6.QtWidgets import QWidget, QGridLayout
import pyqtgraph as pg, numpy as np

SAMPLES = 500

class EMGGrid(QWidget):
    """2x4 grid of fast PyQtGraph plots that share the same ring buffer."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setSpacing(4)
        self._buf = np.zeros((8, SAMPLES), dtype=np.int16)
        self._ptr = 0
        self._plots = []
        self._x = np.arange(SAMPLES)        # ← cache once
        self._dirty = [False]*8   

        for row in range(4):
            for col in range(2):
                ch = row * 2 + col
                w = pg.PlotWidget(background="k")
                # Set ranges here
                vb = w.getViewBox()
                vb.setXRange(0, SAMPLES, padding=0)
                vb.setYRange(-128, 128, padding=0)
                # Ensure autorange is off if you manually set ranges
                vb.disableAutoRange()

                line = w.plot(pen=pg.intColor(ch))
                self._plots.append((w, line))
                self._layout.addWidget(w, row, col)

    def push_frames(self, frames: np.ndarray):
        """frames shape = (8, N).  Vectorised circular write."""
        n = frames.shape[1]
        end = self._ptr + n
        if end <= SAMPLES:
            self._buf[:, self._ptr:end] = frames
        else:                                # wrap-around once
            k = SAMPLES - self._ptr
            self._buf[:, self._ptr:] = frames[:, :k]
            self._buf[:, : end % SAMPLES] = frames[:, k:]
        self._ptr = end % SAMPLES
        self._dirty[:] = [True]*8 

    def refresh(self):
        x = np.arange(SAMPLES)
        for ch, (w, ln) in enumerate(self._plots):
            ln.setData(x, np.roll(self._buf[ch], -self._ptr),
                       downsample=2, autoDownsample=True)
        if not any(self._dirty):
            return
        for ch, (w, ln) in enumerate(self._plots):
            if not self._dirty[ch]:
                continue
            # contiguous view without np.roll copy
            y = (self._buf[ch] if self._ptr == 0
                 else np.concatenate((self._buf[ch, self._ptr:],
                                      self._buf[ch, :self._ptr])))
            ln.setData(self._x, y, downsample=4, autoDownsample=True)
            self._dirty[ch] = False
