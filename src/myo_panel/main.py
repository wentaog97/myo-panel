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


    # bind callbacks after window exists
    mgr._emg_handler = win.on_emg
    mgr._imu_handler = lambda *_: None   # fill when you add IMU widget

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()
