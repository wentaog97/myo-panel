import pytest, asyncio
from myo_panel.ble.myo_manager import MyoManager

class Dummy:
    """Pretend-Bleak client that returns a fixed battery value."""
    async def read_gatt_char(self, uuid):
        return bytes([87])          # 87 %

@pytest.mark.asyncio
async def test_read_battery(monkeypatch):
    monkeypatch.setattr(
        "myo_panel.ble.myo_manager.BleakClient", lambda *_: Dummy()
    )
    m = MyoManager()
    # Pretend we're already connected
    m._client = Dummy()
    m._connected = True

    await m._read_battery()
    assert m.battery == 87
