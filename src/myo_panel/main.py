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
    def _emg_handler(bank, two_frames, timestamp, raw_hex_from_manager):
        # Only update UI if EMG mode is not NONE and we have valid frames
        if mgr._emg_mode != 0 and two_frames is not None:
            win.on_emg(bank, two_frames)
            
        # Handle recording based on UI and mode settings
        if win.record_panel.raw_chk.isChecked():
            # Raw mode is selected in UI: pass raw_hex only if we have it
            if raw_hex_from_manager:
                win.record_panel.push_frame(None, timestamp, raw_hex_from_manager)
        elif two_frames is not None:
            # Processed mode is selected in UI: pass decoded frames
            # raw_hex argument to push_frame will be None by default
            win.record_panel.push_frame(two_frames[0], timestamp)
            win.record_panel.push_frame(two_frames[1], timestamp)
    mgr._emg_handler = _emg_handler

    # bind IMU events to feed recording panel
    def _imu_handler(quat, acc, gyro, timestamp, raw_hex):
        # Only update 3D visualization if IMU mode is not NONE
        if mgr._imu_mode != 0:
            win._on_imu(quat, acc, gyro, timestamp, raw_hex)
    mgr._imu_handler = _imu_handler

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()
