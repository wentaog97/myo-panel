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
_bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True)
_bg_thread.start()

def run_async(coro, timeout=None):          # blocking helper
    future = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return future.result(timeout) # Wait for result with optional timeout

def fire_and_forget(coro):    # schedule without awaiting
    asyncio.run_coroutine_threadsafe(coro, _bg_loop)

# For clean shutdown
def stop_bg_loop():
    """Stop the background event loop and clean up resources."""
    if _bg_loop.is_running():
        print("[MyoManager] Forcefully stopping background loop...")
        
        # Cancel all running tasks
        for task in asyncio.all_tasks(_bg_loop):
            if not task.done():
                task.cancel()
        
        # Stop the loop directly
        _bg_loop.call_soon_threadsafe(_bg_loop.stop)
        
        # Give it a short time to stop
        timeout = 1.0  # shorter timeout - we're being forceful
        start_time = time.time()
        while _bg_loop.is_running() and (time.time() - start_time) < timeout:
            time.sleep(0.1)
        
        print("[MyoManager] Background loop stopped.")

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
        self._connection_changed_callback = None  # Callback for connection state changes

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
        try:
            # This can still block if _connect doesn't timeout properly
            run_async(self._connect(address, cmd))
        except Exception as e:
            # Ensure we're fully disconnected on any error
            fire_and_forget(self._disconnect(silent=True))
            # Convert common BLE errors to more user-friendly messages
            if "not found" in str(e).lower() or "no device" in str(e).lower():
                raise ConnectionError(f"Device {address} was not found") from e
            elif "timeout" in str(e).lower():
                raise ConnectionError(f"Connection to device {address} timed out") from e
            else:
                # Propagate original error
                raise

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

    def disconnect_async(self) -> None:    fire_and_forget(self._disconnect(silent=False))
    def vibrate_async(self, pat="medium"): fire_and_forget(self._vibrate(pat))
    def deep_sleep_async(self):
        if self._shutting_down: return # Added shutdown check
        fire_and_forget(self._deep_sleep())
    def refresh_battery_async(self) -> None:
        if self._shutting_down: return # Added shutdown check
        if self._connected:
            fire_and_forget(self._read_battery())

    def shutdown(self, timeout: float = 3.0) -> None:
        """Initiates shutdown of the MyoManager, attempting a graceful disconnect."""
        print("[MyoManager] Shutdown initiated.")
        
        # Already shutting down - avoid duplicate calls
        if self._shutting_down:
            print("[MyoManager] Already in shutdown process.")
            return
            
        # Set state first to prevent new operations
        self._shutting_down = True
        
        # 1. Cancel any in-progress background tasks immediately
        for task in asyncio.all_tasks(_bg_loop):
            if not task.done() and task != asyncio.current_task(_bg_loop):
                task.cancel()
        
        # 2. Clear connection callback to prevent UI updates during shutdown
        self._connection_changed_callback = None
        
        # 3. Force client disconnection synchronously if client exists
        if self._client:
            print("[MyoManager] Forcefully disconnecting client during shutdown...")
            try:
                # Direct synchronous cleanup - no awaiting
                self._client = None  # Release the client reference first
                self._connected = False  # Ensure we're marked as disconnected
            except Exception as e:
                print(f"[MyoManager] Error during forceful disconnect: {e}")
        else:
            print("[MyoManager] No client to disconnect during shutdown.")
        
        # 4. Release all other resources
        self._battery = None
        self._emg_handler = None
        self._imu_handler = None
        
        # Set final shutdown state
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
            await self._disconnect(silent=True) # Ensure any partial setup is cleared
            return

        await self._disconnect(silent=True) # Ensure any previous connection is cleared with no callback
        async with self._lock:
            try:
                if self._shutting_down: # Check again after acquiring lock
                    print("[MyoManager] _connect aborted after lock due to shutdown.")
                    await self._disconnect()
                    return

                self._client = BleakClient(addr)
                # Add a timeout to the connect call (e.g., 15 seconds)
                try:
                    # Explicit timeout for the connect call
                    await asyncio.wait_for(self._client.connect(), timeout=15.0)
                except asyncio.TimeoutError:
                    self._last_error = "Connection timed out after 15 seconds"
                    print(f"[MyoManager] Connect timeout: {addr}")
                    await self._disconnect()
                    raise ConnectionError(f"Connection to device {addr} timed out")
                except Exception as connect_exc:
                    self._last_error = f"connect failed: {connect_exc}"
                    if "not found" in str(connect_exc).lower() or "no device" in str(connect_exc).lower():
                        print(f"[MyoManager] Device not found: {addr}")
                        await self._disconnect()  
                        raise ConnectionError(f"Device {addr} was not found")
                    else:
                        print(f"[MyoManager] Connect error: {connect_exc}")
                        await self._disconnect()
                        raise

                # Set disconnect callback
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
                
                # Notify UI about successful connection
                if self._connection_changed_callback:
                    try:
                        self._connection_changed_callback(True, "connected")
                    except Exception as e:
                        print(f"[MyoManager] Error in connection changed callback: {e}")
                        
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

    async def _disconnect(self, silent=False):
        """Disconnect from the MYO device.
        
        Args:
            silent: If True, don't trigger the connection_changed_callback.
                   This is useful for routine disconnects during a connection attempt.
        """
        # No explicit shutdown check here, as disconnect is part of shutdown.
        async with self._lock:
            was_connected = self._connected and self._client and self._client.is_connected
            
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
                
                # Notify about disconnection if callback is set, not shutting down, and not silent
                # Only trigger callback if we were actually connected before (avoid spurious callbacks)
                if self._connection_changed_callback and not silent and was_connected:
                    try:
                        self._connection_changed_callback(False, "disconnect")
                    except Exception as e:
                        print(f"[MyoManager] Error in connection changed callback: {e}")
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
            # Use normal disconnect with callbacks since this is an intentional disconnect
            # that should update the UI
            await self._disconnect(silent=False)
            
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

    # ── Bleak disconnect callback ────────────────────────────────────────────
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
            # Could notify UI or handle disconnection here if needed
            # But be careful about threading since this is called from bleak's thread
            self._last_error = "Device disconnected unexpectedly"
            
            # Notify UI about disconnection if callback is set
            if self._connection_changed_callback:
                try:
                    self._connection_changed_callback(False, "unexpected_disconnect")
                except Exception as e:
                    print(f"[MyoManager] Error in connection changed callback: {e}")

    def get_model_name(self, hw_type: int) -> str:
        """Get the model name for a given hardware type."""
        return self.model_names.get(hw_type, self.model_names[0])

    def set_connection_callback(self, callback):
        """Set a callback to be called when connection state changes.
        
        The callback should accept two parameters:
        - connected: bool - whether the device is now connected
        - reason: str - reason for the state change (e.g., "connected", "disconnect", "unexpected_disconnect")
        """
        self._connection_changed_callback = callback

