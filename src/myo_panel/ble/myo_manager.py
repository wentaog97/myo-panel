"""
myo_manager.py
--------------
BLE helper that turns a MYO armband into decoded EMG / IMU callbacks.

This is the same logic that was in *myo‑app.py*, but with all web‑framework
code removed, and with constants pulled in from *myo_constants.py*.
"""

from __future__ import annotations

import asyncio, threading, time
from typing import Callable, Dict, List, Optional

from bleak import BleakClient, BleakScanner   # pip install bleak

from . import myo_constants as C

# ── dedicated background asyncio loop ────────────────────────────────────
_bg_loop = asyncio.new_event_loop()
threading.Thread(target=_bg_loop.run_forever, daemon=True).start()

def run_async(coro):          # blocking helper
    return asyncio.run_coroutine_threadsafe(coro, _bg_loop).result()
def fire_and_forget(coro):    # schedule without awaiting
    asyncio.run_coroutine_threadsafe(coro, _bg_loop)

# ─────────────────────────────────────────────────────────────────────────
class MyoManager:
    """Connects to the MYO and streams decoded data via callbacks."""

    def __init__(
        self,
        *,
        emg_handler: Optional[Callable[[int, List[List[int]]], None]] = None,
        imu_handler: Optional[Callable[[List[float], List[int], List[int], str], None]] = None,
    ) -> None:
        self._client: Optional[BleakClient] = None
        self._lock = asyncio.Lock()
        self._connected = False
        self._battery: Optional[int] = None
        self._sku = None
        self._emg_mode = 3
        self._imu_mode = 1
        self._fw = None
        self._last_error: Optional[str] = None
        self._emg_handler, self._imu_handler = emg_handler, imu_handler

    # ── synchronous wrappers ─────────────────────────────────────────────
    def scan(self) -> List[Dict[str, str]]:
        """Return a list of nearby MYO devices (blocking)."""
        return run_async(self._scan())

    def connect(self, address: str, *, emg_mode: int = 3, imu_mode: int = 1) -> None:
        """Blocking connect & start streaming."""
        self._emg_mode = emg_mode
        self._imu_mode = imu_mode
        cmd = bytearray([0x01, 3, emg_mode, imu_mode, 0x00])
        run_async(self._connect(address, cmd))

    def disconnect_async(self) -> None:    fire_and_forget(self._disconnect())
    def vibrate_async(self, pat="medium"): fire_and_forget(self._vibrate(pat))
    def deep_sleep_async(self):            fire_and_forget(self._deep_sleep())
    def refresh_battery_async(self) -> None:
        if self._connected:
            fire_and_forget(self._read_battery())

    # ── public read‑only props ───────────────────────────────────────────
    @property
    def connected(self): return self._connected
    @property
    def battery(self):   return self._battery
    @property
    def firmware(self):  return self._fw
    @property
    def model_name(self):
        models = {1: "MYO Black", 2: "MYO White", 3: "MYOD5", 0: "Unknown"}
        return models.get(self._sku, f"SKU {self._sku}" if self._sku else None)

    # ── internal coroutines ──────────────────────────────────────────────
    async def _scan(self):
        devs = await BleakScanner.discover(timeout=4.0)
        out: Dict[str, BleakScanner] = {}
        for d in devs:
            name = (d.name or "").lower()
            uuids = [u.lower() for u in d.metadata.get("uuids", [])]
            if "myo" in name or any(u.startswith(C.MYO_SERVICE_PREFIX) for u in uuids):
                out.setdefault(d.address, d)
        return [{"name": d.name or "Myo Armband", "address": d.address} for d in out.values()]

    async def _connect(self, addr, cmd):
        await self._disconnect()
        async with self._lock:
            try:
                self._client = BleakClient(addr)
                await self._client.connect()
                self._client.set_disconnected_callback(self._on_ble_disconnect)

                await self._client.write_gatt_char(C.COMMAND_UUID, cmd, response=True)
                await self._client.write_gatt_char(C.COMMAND_UUID, C.NEVER_SLEEP_CMD, response=True)

                self._connected = True
                await self._read_battery(); await self._read_model(); await self._read_firmware()
                await self._start_emg(); await self._start_imu()
                print("[MyoManager] connected to", addr)
            except Exception as exc:
                await self._disconnect()
                self._last_error = f"connect failed: {exc}"
                raise

    async def _disconnect(self):
        async with self._lock:
            if self._client and self._client.is_connected:
                try: await self._client.disconnect()
                except Exception: pass
            self._client = None; self._battery = None; self._connected = False
            print("[MyoManager] disconnected")

    async def _vibrate(self, pattern):
        if not self._connected: return
        await self._client.write_gatt_char(
            C.COMMAND_UUID,
            C.VIB_CMDS.get(pattern, C.VIB_CMDS["medium"]),
            response=True,
        )

    async def _deep_sleep(self):
        if not self._connected:
            return
        try:
            await self._client.write_gatt_char(
                C.COMMAND_UUID, C.DEEP_SLEEP_CMD, response=True
            )
        finally:
            await self._disconnect()

    # ── streaming helpers ────────────────────────────────────────────────
    async def _start_emg(self):
        if not (self._client and self._client.is_connected): return
        def make_handler(bank):
            def h(_, data: bytearray):
                if len(data) == 16:
                    # Use Unix time with nano precision
                    ts = int(time.time() * 1000000)
                    # For raw mode, keep the original bytes
                    raw_hex = "".join(f"{b:02x}" for b in data)
                    # For processed mode, decode the values
                    samples = [[int.from_bytes([b], "little", signed=True) for b in data[:8]],
                             [int.from_bytes([b], "little", signed=True) for b in data[8:]]]
                    if self._emg_handler: 
                        self._emg_handler(bank, samples, ts, raw_hex)
            return h
        for i, uuid in enumerate(C.EMG_UUIDS):
            await self._client.start_notify(uuid, make_handler(i))

    async def _start_imu(self):
        if not (self._client and self._client.is_connected): return
        def h(_, d: bytearray):
            if len(d) == 20 and self._imu_handler:
                # Use Unix time with nanosecond precision
                ts = int(time.time() * 1000000)
                q = [int.from_bytes(d[i:i+2], "little", signed=True) / 16384 for i in range(0, 8, 2)]
                a = [int.from_bytes(d[i:i+2], "little", signed=True)          for i in range(8, 14, 2)]
                g = [int.from_bytes(d[i:i+2], "little", signed=True)          for i in range(14, 20, 2)]
                # Pass the raw hex data to the callback
                raw_hex = "".join(f"{b:02x}" for b in d)
                self._imu_handler(q, a, g, ts, raw_hex)
        await self._client.start_notify(C.IMU_UUID, h)

    # ── misc reads ───────────────────────────────────────────────────────
    async def _read_battery(self):
        try:
            d = await self._client.read_gatt_char(C.BATTERY_UUID)
            if d: self._battery = d[0]; return
        except Exception: pass
        try:
            v = await self._client.read_gatt_char(C.VOLT_UUID)
            if v and len(v) >= 2:
                mv = int.from_bytes(v[:2], "little"); v = mv / 1000
                self._battery = round(min(max((v-3.7)/0.5, 0), 1)*100)
        except Exception: self._battery = None

    async def _read_model(self):
        try:
            d = await self._client.read_gatt_char(C.MYO_INFO_UUID)
            if len(d) == 20: self._sku = d[12]
        except Exception: self._sku = None

    async def _read_firmware(self):
        try:
            d = await self._client.read_gatt_char(C.MYO_FW_UUID)
            if len(d) >= 6:
                self._fw = f"{int.from_bytes(d[0:2],'little')}."                            f"{int.from_bytes(d[2:4],'little')}."                            f"{int.from_bytes(d[4:6],'little')}"
        except Exception: self._fw = None

    # ── Bleak disconnect callback ────────────────────────────────────────
    def _on_ble_disconnect(self, _):
        if _bg_loop.is_running():
            _bg_loop.call_soon_threadsafe(lambda: asyncio.create_task(self._disconnect()))
