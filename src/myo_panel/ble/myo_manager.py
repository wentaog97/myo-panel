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
from .myo_constants import (
    MYO_HW_TYPE_MYO_BLACK,
    MYO_HW_TYPE_MYO_WHITE,
    MYO_HW_TYPE_MYO_ALPHA,
    MYO_MODEL_NAMES,
)

# ── dedicated background asyncio loop ────────────────────────────────────
_bg_loop = asyncio.new_event_loop()
threading.Thread(target=_bg_loop.run_forever, daemon=True).start()

def run_async(coro, timeout=None):          # blocking helper
    future = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return future.result(timeout) # Wait for result with optional timeout

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
        self._shutting_down = False # Flag to indicate shutdown
        self.model_names = MYO_MODEL_NAMES

    # ── synchronous wrappers ─────────────────────────────────────────────
    def scan(self) -> List[Dict[str, str]]:
        """Return a list of nearby MYO devices (blocking)."""
        if self._shutting_down:
            print("[MyoManager] Scan called during shutdown, ignoring.")
            return []
        return run_async(self._scan())

    def connect(self, address: str, *, emg_mode: int = 3, imu_mode: int = 1) -> None:
        """Blocking connect & start streaming."""
        if self._shutting_down:
            print("[MyoManager] Connect called during shutdown, ignoring.")
            raise ConnectionAbortedError("Shutdown in progress")
        self._emg_mode = emg_mode
        self._imu_mode = imu_mode
        cmd = bytearray([0x01, 3, emg_mode, imu_mode, 0x00])
        run_async(self._connect(address, cmd)) # This can still block if _connect doesn't timeout properly

    def update_modes(self, emg_mode: int = None, imu_mode: int = None) -> None:
        """Update EMG and IMU modes on a connected device."""
        if self._shutting_down or not self._connected: # Added shutdown check
            return False
            
        # Only update modes that are specified
        if emg_mode is not None:
            self._emg_mode = emg_mode
        if imu_mode is not None:
            self._imu_mode = imu_mode
            
        # Send command with updated modes
        cmd = bytearray([0x01, 3, self._emg_mode, self._imu_mode, 0x00])
        return run_async(self._update_modes(cmd))

    def disconnect_async(self) -> None:    fire_and_forget(self._disconnect())
    def vibrate_async(self, pat="medium"): fire_and_forget(self._vibrate(pat))
    def deep_sleep_async(self):
        if self._shutting_down: return # Added shutdown check
        fire_and_forget(self._deep_sleep())
    def refresh_battery_async(self) -> None:
        if self._shutting_down: return # Added shutdown check
        if self._connected:
            fire_and_forget(self._read_battery())

    def shutdown(self, timeout: float = 5.0) -> None:
        """Initiates shutdown of the MyoManager, attempting a graceful disconnect."""
        print("[MyoManager] Shutdown initiated.")
        self._shutting_down = True
        # Stop new operations from starting
        # Try to disconnect if a client exists or might be connecting
        try:
            # We run _disconnect which is async. run_async will block until it's done or timeout.
            run_async(self._disconnect(), timeout=timeout)
            print("[MyoManager] Disconnect attempt in shutdown finished or timed out.")
        except Exception as e:
            # This includes timeout from future.result(timeout) in run_async
            # Using repr(e) or type(e).__name__ for better timeout error logging
            print(f"[MyoManager] Error/Timeout during shutdown disconnect of type {type(e).__name__}: {e}")
        finally:
            # Additional cleanup if needed, though _disconnect should handle client
            print("[MyoManager] Shutdown complete.")

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
        if self._shutting_down: return []
        devs = await BleakScanner.discover(timeout=4.0)
        out: Dict[str, object] = {} # Using object if BLEDevice type hint is problematic, BleakScanner.discover returns BLEDevice instances
        for d in devs:
            name = (d.name or "").lower()
            
            current_service_uuids = []
            if hasattr(d, 'advertisement_data') and d.advertisement_data and hasattr(d.advertisement_data, 'service_uuids'):
                # New recommended way
                current_service_uuids = [str(u).lower() for u in d.advertisement_data.service_uuids]
            elif hasattr(d, 'metadata') and d.metadata:
                # Fallback to the metadata method that previously worked (and gave a FutureWarning)
                # The original code used d.metadata.get("uuids", [])
                raw_uuids_from_meta = d.metadata.get("uuids", []) 
                current_service_uuids = [str(u).lower() for u in raw_uuids_from_meta]
            # If neither is available, current_service_uuids will be an empty list.

            if "myo" in name or any(u.startswith(C.MYO_SERVICE_PREFIX) for u in current_service_uuids):
                out.setdefault(d.address, d)
        return [{"name": d.name or "Myo Armband", "address": d.address} for d in out.values()]

    async def _connect(self, addr, cmd):
        if self._shutting_down:
            print("[MyoManager] _connect called during shutdown, aborting.")
            # Ensure we don't leave things in a weird state; _disconnect might be too much here if no client yet
            # but _disconnect handles self._client being None.
            await self._disconnect() # Ensure any partial setup is cleared
            return

        await self._disconnect() # Ensure any previous connection is cleared
        async with self._lock:
            try:
                if self._shutting_down: # Check again after acquiring lock
                    print("[MyoManager] _connect aborted after lock due to shutdown.")
                    await self._disconnect()
                    return

                self._client = BleakClient(addr)
                # Add a timeout to the connect call (e.g., 15 seconds)
                await asyncio.wait_for(self._client.connect(), timeout=15.0)
                self._client.set_disconnected_callback(self._on_ble_disconnect)

                # Check if shutting down before proceeding with post-connection setup
                if self._shutting_down:
                    print("[MyoManager] Shutdown occurred during connection process, disconnecting.")
                    # Disconnect will be called in the finally block of the caller or here directly
                    # We need to ensure the client is disconnected if it was connected.
                    if self._client and self._client.is_connected:
                        await self._client.disconnect() # Try to disconnect the established client
                    self._connected = False # Ensure connected status is false
                    return # Abort further setup

                await self._client.write_gatt_char(C.COMMAND_UUID, cmd, response=True)
                await self._client.write_gatt_char(C.COMMAND_UUID, C.NEVER_SLEEP_CMD, response=True)

                self._connected = True
                await self._read_battery(); await self._read_model(); await self._read_firmware()
                await self._start_emg(); await self._start_imu()
                print("[MyoManager] connected to", addr)
            except Exception as exc:
                # If shutdown happened, this error might be due to cancellation or timeout, which is expected.
                if not self._shutting_down: # Only log as an unexpected error if not shutting down
                    self._last_error = f"connect failed: {exc}"
                    print(f"[MyoManager] Connect failed: {exc}") # Keep for visibility
                # Always attempt to clean up, regardless of shutdown state
                await self._disconnect() # This will set self._connected = False
                if not self._shutting_down : # Only re-raise if not a shutdown-induced error
                    raise

    async def _disconnect(self):
        # No explicit shutdown check here, as disconnect is part of shutdown.
        async with self._lock:
            if self._client and self._client.is_connected:
                try: 
                    print("[MyoManager] Attempting to disconnect bleak client...")
                    await self._client.disconnect()
                    print("[MyoManager] Bleak client disconnected successfully.")
                except Exception as e:
                    print(f"[MyoManager] Error during bleak client disconnect: {e}")
                    # Do not re-raise, allow rest of cleanup
                    pass # Already catching, but be more verbose
            else:
                print("[MyoManager] No active or connected bleak client to disconnect.")
            self._client = None; self._battery = None; self._connected = False
            # Don't print "[MyoManager] disconnected" if we are in the process of shutting down,
            # as the shutdown method will print its own status.
            if not self._shutting_down:
                print("[MyoManager] disconnected (normal operation)")
            else:
                print("[MyoManager] _disconnect called during shutdown process.")

    async def _vibrate(self, pattern):
        if self._shutting_down or not self._connected: return # Added shutdown check
        await self._client.write_gatt_char(
            C.COMMAND_UUID,
            C.VIB_CMDS.get(pattern, C.VIB_CMDS["medium"]),
            response=True,
        )

    async def _deep_sleep(self):
        if self._shutting_down or not self._connected: return # Added shutdown check
        try:
            await self._client.write_gatt_char(
                C.COMMAND_UUID, C.DEEP_SLEEP_CMD, response=True
            )
        finally:
            await self._disconnect()
            
    async def _update_modes(self, cmd):
        """Send a new command to update the EMG and IMU modes on an already connected device."""
        if self._shutting_down or not self._connected: return False # Added shutdown check
        
        try:
            # Stop notifications to reset the streaming
            try:
                for uuid in C.EMG_UUIDS:
                    await asyncio.wait_for(self._client.stop_notify(uuid), 1.0)  # 1s timeout
                await asyncio.wait_for(self._client.stop_notify(C.IMU_UUID), 1.0)  # 1s timeout
            except (asyncio.TimeoutError, Exception) as e:
                print(f"[MyoManager] Warning: stop_notify timed out or failed: {e}")
                # Continue anyway since we're going to reset the connection
            
            # Small delay to ensure notifications are completely stopped
            await asyncio.sleep(0.2)
            
            # Send new command with updated modes
            await self._client.write_gatt_char(C.COMMAND_UUID, cmd, response=True)
            
            # Small delay to ensure command is processed
            await asyncio.sleep(0.2)
            
            # Restart streaming with new modes
            await self._start_emg()
            await self._start_imu()
            print(f"[MyoManager] Updated modes: EMG={self._emg_mode}, IMU={self._imu_mode}")
            return True
        except Exception as exc:
            print(f"[MyoManager] Failed to update modes: {exc}")
            return False

    # ── streaming helpers ────────────────────────────────────────────────
    async def _start_emg(self):
        if self._shutting_down or not (self._client and self._client.is_connected):  # Added shutdown check
            return
            
        def make_handler(bank):
            def h(_, data: bytearray):
                if len(data) == 16:
                    # Use Unix time with nano precision
                    ts = int(time.time() * 1000000)
                    # Always keep the original bytes for raw mode
                    raw_hex = "".join(f"{b:02x}" for b in data)
                    
                    # Process data based on EMG mode
                    if self._emg_mode == C.EMG_MODE_NONE:
                        samples = None  # No processing in NONE mode
                    else:
                        # For all other modes, decode the values
                        # The difference is in what the device sends, not how we parse it
                        samples = [
                            [int.from_bytes([b], "little", signed=True) for b in data[:8]],
                            [int.from_bytes([b], "little", signed=True) for b in data[8:]]
                        ]
                    
                    if self._emg_handler:
                        self._emg_handler(bank, samples, ts, raw_hex)
            return h
            
        for i, uuid in enumerate(C.EMG_UUIDS):
            await self._client.start_notify(uuid, make_handler(i))

    async def _start_imu(self):
        if self._shutting_down or not (self._client and self._client.is_connected): return # Added shutdown check
        def h(_, d: bytearray):
            if self._shutting_down: return # Check within handler too
            if len(d) == 20 and self._imu_handler:
                # Use Unix time with nanosecond precision
                ts = int(time.time() * 1000000)
                q = [int.from_bytes(d[i:i+2], "little", signed=True) / C.MYOHW_ORIENTATION_SCALE for i in range(0, 8, 2)]
                a = [int.from_bytes(d[i:i+2], "little", signed=True) / C.MYOHW_ACCELEROMETER_SCALE for i in range(8, 14, 2)]
                g = [int.from_bytes(d[i:i+2], "little", signed=True) / C.MYOHW_GYROSCOPE_SCALE for i in range(14, 20, 2)]
                # Pass the raw hex data to the callback
                raw_hex = "".join(f"{b:02x}" for b in d)
                self._imu_handler(q, a, g, ts, raw_hex)
        await self._client.start_notify(C.IMU_UUID, h)
    # ── misc reads ───────────────────────────────────────────────────────
    async def _read_battery(self):
        if self._shutting_down or not self._client: return # Added shutdown check
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
        if self._shutting_down or not self._client: return # Added shutdown check
        try:
            d = await self._client.read_gatt_char(C.MYO_INFO_UUID)
            if len(d) == 20: self._sku = d[12]
        except Exception: self._sku = None

    async def _read_firmware(self):
        if self._shutting_down or not self._client: return # Added shutdown check
        try:
            d = await self._client.read_gatt_char(C.MYO_FW_UUID)
            if len(d) >= 6:
                self._fw = f"{int.from_bytes(d[0:2],'little')}."                            f"{int.from_bytes(d[2:4],'little')}."                            f"{int.from_bytes(d[4:6],'little')}"
        except Exception: self._fw = None

    # ── Bleak disconnect callback ────────────────────────────────────────
    def _on_ble_disconnect(self, _):
        # This is a callback from bleak, can be called unexpectedly
        print("[MyoManager] BLE disconnected callback triggered.")
        self._connected = False
        self._battery = None 
        # Don't re-trigger _disconnect or other async operations from here directly
        # as it's called from bleak's thread/context.
        # If shutting down, this is expected. If not, it's an external disconnect.
        if not self._shutting_down:
            print("[MyoManager] External disconnect detected.")
            # Optionally, schedule a reconnect or notify UI, but be careful about loops.
            # For now, just log it.

    def get_model_name(self, hw_type: int) -> str:
        """Get the model name for a given hardware type."""
        return self.model_names.get(hw_type, self.model_names[0])

