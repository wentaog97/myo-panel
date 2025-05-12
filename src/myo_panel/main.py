# main.py  (entry-point for `python -m myo_panel` or `myo-panel` script)
import sys, asyncio, pathlib
from PySide6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop, asyncSlot
from .ble.myo_manager import MyoManager
from .ui.windows import MainWindow

import pyqtgraph as pg


def main():
    pg.setConfigOptions(useOpenGL=True, antialias=False)     

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    mgr = MyoManager()                 # callbacks added below
    win = MainWindow(mgr)
    win.show()

    # bind EMG events to both UI plots and the recording panel
    def _emg_handler(bank, two_frames, timestamp, raw_hex):
        win.on_emg(bank, two_frames)
        if raw_hex:
            # For raw hex mode, pass the complete raw data
            win.record_panel.push_frame(None, timestamp, raw_hex)
        else:
            # For processed mode, pass the frames
            win.record_panel.push_frame(two_frames[0], timestamp)
            win.record_panel.push_frame(two_frames[1], timestamp)
    mgr._emg_handler = _emg_handler

    # bind IMU events to feed recording panel
    def _imu_handler(quat, acc, gyro, timestamp, raw_hex):
        win.record_panel.push_imu(quat, acc, gyro, timestamp, raw_hex)
    mgr._imu_handler = _imu_handler

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()
