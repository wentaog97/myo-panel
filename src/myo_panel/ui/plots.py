# plots.py
from PySide6.QtWidgets import QWidget, QGridLayout
import pyqtgraph as pg, numpy as np

# Default values that can be overridden
DEFAULT_SAMPLES = 500
SIGNAL_RANGE = 150
CHANNEL_NAMES = [f"EMG_{i}" for i in range(8)]

class _Ring:
    """Shared circular buffer so grid & composite read the same data."""
    def __init__(self, sample_size=DEFAULT_SAMPLES):
        self.sample_size = sample_size
        self.buf = np.zeros((8, self.sample_size), dtype=np.int16)
        self.ptr = 0
        
    def insert(self, frames: np.ndarray):         # frames (8, N)
        n = frames.shape[1]; end = self.ptr + n
        if end <= self.sample_size:
            self.buf[:, self.ptr:end] = frames
        else:
            k = self.sample_size - self.ptr
            self.buf[:, self.ptr:] = frames[:, :k]
            self.buf[:, : end % self.sample_size] = frames[:, k:]
        self.ptr = end % self.sample_size
        
    def resize(self, new_size):
        """Resize the buffer, preserving as much data as possible."""
        if new_size == self.sample_size:
            return  # No change needed
            
        # Create new buffer
        new_buf = np.zeros((8, new_size), dtype=np.int16)
        
        # Determine how much data to copy
        if self.ptr == 0:
            # Buffer is empty or just reset
            pass
        elif new_size >= self.sample_size:
            # New buffer is larger - copy all existing data
            # First the data from ptr to end
            copy_size = min(self.sample_size - self.ptr, self.sample_size)
            new_buf[:, 0:copy_size] = self.buf[:, self.ptr:self.ptr+copy_size]
            
            # Then from beginning to ptr if wrapped around
            if self.ptr > 0:
                new_buf[:, copy_size:copy_size+self.ptr] = self.buf[:, 0:self.ptr]
                
            # Update ptr to end of copied data
            self.ptr = min(self.sample_size, copy_size + self.ptr)
        else:
            # New buffer is smaller - copy most recent data
            data_to_copy = min(new_size, self.sample_size)
            
            # Calculate where the most recent data starts
            if self.ptr < data_to_copy:
                # Need to wrap around
                # First copy from end of buffer
                end_size = data_to_copy - self.ptr
                new_buf[:, 0:end_size] = self.buf[:, self.sample_size-end_size:self.sample_size]
                
                # Then copy from beginning to ptr
                new_buf[:, end_size:data_to_copy] = self.buf[:, 0:self.ptr]
                
                # Set ptr to end of buffer (will wrap to 0)
                self.ptr = new_size
            else:
                # No wrap needed, just copy the most recent data
                start = self.ptr - data_to_copy
                new_buf[:, 0:data_to_copy] = self.buf[:, start:self.ptr]
                
                # Set ptr to 0 (will wrap to 0)
                self.ptr = data_to_copy
        
        # Update buffer and size
        self.buf = new_buf
        self.sample_size = new_size
        
        # Make sure ptr is within bounds
        self.ptr = self.ptr % self.sample_size

class EMGGrid(QWidget):
    """2x4 grid, each with its own line, but sharing one ring buffer."""
    def __init__(self, ring: _Ring, parent=None):
        super().__init__(parent); self.ring = ring
        self._layout = QGridLayout(self); self._layout.setSpacing(4)
        self._plots, self._x = [], np.arange(ring.sample_size)
        self._downsample = 4  # Default downsample value
        
        for row in range(4):
            for col in range(2):
                ch = row*2 + col
                w = pg.PlotWidget(background="k"); w.setMouseEnabled(False, False); w.hideButtons()
                vb = w.getViewBox()
                vb.setXRange(0, ring.sample_size, padding=0); vb.setYRange(-SIGNAL_RANGE, SIGNAL_RANGE, padding=0)
                vb.disableAutoRange()
                w.setTitle(CHANNEL_NAMES[ch], color='w', size='8pt')
                line = w.plot(pen=pg.intColor(ch))
                self._plots.append((ch, w, line)); self._layout.addWidget(w, row, col)
                
    def set_downsample(self, value):
        """Set the downsample ratio for plotting."""
        self._downsample = value
                
    def update_buffer_size(self, size):
        """Update the display after buffer size changes."""
        self._x = np.arange(size)
        for ch, w, ln in self._plots:
            vb = w.getViewBox()
            vb.setXRange(0, size, padding=0)

    def refresh(self):
        for ch, w, ln in self._plots:
            y = (self.ring.buf[ch] if self.ring.ptr == 0
                 else np.concatenate((self.ring.buf[ch, self.ring.ptr:],
                                      self.ring.buf[ch, :self.ring.ptr])))
            ln.setData(self._x, y, downsample=self._downsample, autoDownsample=False)

class EMGComposite(QWidget):
    """Single plot with 8 coloured lines + toggleable legend."""
    def __init__(self, ring: _Ring, parent=None):
        super().__init__(parent); self.ring = ring
        self._x = np.arange(ring.sample_size)
        self._pw = pg.PlotWidget(background="k"); self._pw.hideButtons()
        self._pw.setMouseEnabled(False, False)
        self._pw.getViewBox().setXRange(0, ring.sample_size, padding=0)
        self._pw.getViewBox().setYRange(-SIGNAL_RANGE, SIGNAL_RANGE, padding=0)
        self._pw.addLegend()
        self.lines = []
        self._downsample = 4  # Default downsample value
        
        for ch in range(8):
            ln = self._pw.plot(pen=pg.intColor(ch), name=CHANNEL_NAMES[ch])
            self.lines.append(ln)
        lay = QGridLayout(self); lay.addWidget(self._pw, 0, 0)
        
    def set_downsample(self, value):
        """Set the downsample ratio for plotting."""
        self._downsample = value
        
    def update_buffer_size(self, size):
        """Update the display after buffer size changes."""
        self._x = np.arange(size)
        vb = self._pw.getViewBox()
        vb.setXRange(0, size, padding=0)

    def refresh(self):
        for ch, ln in enumerate(self.lines):
            y = (self.ring.buf[ch] if self.ring.ptr == 0
                 else np.concatenate((self.ring.buf[ch, self.ring.ptr:],
                                      self.ring.buf[ch, :self.ring.ptr])))
            ln.setData(self._x, y, downsample=self._downsample, autoDownsample=False)
