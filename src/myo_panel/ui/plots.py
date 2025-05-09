# plots.py
from PySide6.QtWidgets import QWidget, QGridLayout
import pyqtgraph as pg, numpy as np

SAMPLES = 500
SIGNAL_RANGE = 150
CHANNEL_NAMES = [f"EMG_{i}" for i in range(8)]

class _Ring:
    """Shared circular buffer so grid & composite read the same data."""
    def __init__(self):
        self.buf = np.zeros((8, SAMPLES), dtype=np.int16)
        self.ptr = 0
    def insert(self, frames: np.ndarray):         # frames (8, N)
        n = frames.shape[1]; end = self.ptr + n
        if end <= SAMPLES:
            self.buf[:, self.ptr:end] = frames
        else:
            k = SAMPLES - self.ptr
            self.buf[:, self.ptr:] = frames[:, :k]
            self.buf[:, : end % SAMPLES] = frames[:, k:]
        self.ptr = end % SAMPLES

class EMGGrid(QWidget):
    """2x4 grid, each with its own line, but sharing one ring buffer."""
    def __init__(self, ring: _Ring, parent=None):
        super().__init__(parent); self.ring = ring
        self._layout = QGridLayout(self); self._layout.setSpacing(4)
        self._plots, self._x = [], np.arange(SAMPLES)
        for row in range(4):
            for col in range(2):
                ch = row*2 + col
                w = pg.PlotWidget(background="k"); w.setMouseEnabled(False, False); w.hideButtons()
                vb = w.getViewBox()
                vb.setXRange(0, SAMPLES, padding=0); vb.setYRange(-SIGNAL_RANGE, SIGNAL_RANGE, padding=0)
                vb.disableAutoRange()
                w.setTitle(CHANNEL_NAMES[ch], color='w', size='8pt')
                line = w.plot(pen=pg.intColor(ch))
                self._plots.append((ch, w, line)); self._layout.addWidget(w, row, col)

    def refresh(self):
        for ch, w, ln in self._plots:
            y = (self.ring.buf[ch] if self.ring.ptr == 0
                 else np.concatenate((self.ring.buf[ch, self.ring.ptr:],
                                      self.ring.buf[ch, :self.ring.ptr])))
            ln.setData(self._x, y, downsample=4, autoDownsample=True)

class EMGComposite(QWidget):
    """Single plot with 8 coloured lines + toggleable legend."""
    def __init__(self, ring: _Ring, parent=None):
        super().__init__(parent); self.ring = ring
        self._x = np.arange(SAMPLES)
        self._pw = pg.PlotWidget(background="k"); self._pw.hideButtons()
        self._pw.setMouseEnabled(False, False)
        self._pw.getViewBox().setXRange(0, SAMPLES, padding=0)
        self._pw.getViewBox().setYRange(-SIGNAL_RANGE, SIGNAL_RANGE, padding=0)
        self._pw.addLegend()
        self.lines = []
        for ch in range(8):
            ln = self._pw.plot(pen=pg.intColor(ch), name=CHANNEL_NAMES[ch])
            self.lines.append(ln)
        lay = QGridLayout(self); lay.addWidget(self._pw, 0, 0)

    def refresh(self):
        for ch, ln in enumerate(self.lines):
            y = (self.ring.buf[ch] if self.ring.ptr == 0
                 else np.concatenate((self.ring.buf[ch, self.ring.ptr:],
                                      self.ring.buf[ch, :self.ring.ptr])))
            ln.setData(self._x, y, downsample=4, autoDownsample=True)
