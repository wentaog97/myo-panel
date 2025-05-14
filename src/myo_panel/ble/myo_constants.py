"""
myo_constants.py
----------------
All UUIDs and command payloads for the Thalmic Labs MYO armband, split out so
they can be shared by multiple modules (e.g. GUI app, CLI tools, unit tests).

Ref: https://github.com/thalmiclabs/myo-bluetooth/blob/master/myohw.h
"""

# ── GATT characteristic UUIDs ─────────────────────────────────────────────
COMMAND_UUID      = "d5060401-a904-deb9-4748-2c7f4a124842"
VOLT_UUID         = "d5060404-a904-deb9-4748-2c7f4a124842"
BATTERY_UUID      = "00002a19-0000-1000-8000-00805f9b34fb"
MYO_INFO_UUID     = "d5060101-a904-deb9-4748-2c7f4a124842"
MYO_FW_UUID       = "d5060201-a904-deb9-4748-2c7f4a124842"
MYO_SERVICE_PREFIX = "d506"  # first 16‑bit word common to all MYO services

EMG_UUIDS = [
    "d5060105-a904-deb9-4748-2c7f4a124842",
    "d5060205-a904-deb9-4748-2c7f4a124842",
    "d5060305-a904-deb9-4748-2c7f4a124842",
    "d5060405-a904-deb9-4748-2c7f4a124842",
]
IMU_UUID = "d5060402-a904-deb9-4748-2c7f4a124842"

# ── command types ─────────────────────────────────────────────────────────
CMD_SET_MODE      = 0x01  # Set EMG and IMU modes
CMD_VIBRATE       = 0x03  # Vibration command
CMD_DEEP_SLEEP    = 0x04  # Put Myo into deep sleep
CMD_VIBRATE2      = 0x07  # Extended vibration command
CMD_SET_SLEEP     = 0x09  # Set sleep mode
CMD_UNLOCK        = 0x0a  # Unlock Myo
CMD_USER_ACTION   = 0x0b  # Notify user that an action has been recognized

# ── EMG modes ────────────────────────────────────────────────────────────
EMG_MODE_NONE     = 0x00  # Do not send EMG data
EMG_MODE_SEND_EMG = 0x02  # Send filtered EMG data
EMG_MODE_SEND_RAW = 0x03  # Send raw (unfiltered) EMG data

# ── IMU modes ────────────────────────────────────────────────────────────
IMU_MODE_NONE        = 0x00  # Do not send IMU data or events
IMU_MODE_SEND_DATA   = 0x01  # Send IMU data streams (accelerometer, gyroscope, and orientation)
IMU_MODE_SEND_EVENTS = 0x02  # Send motion events detected by the IMU (e.g. taps)
IMU_MODE_SEND_ALL    = 0x03  # Send both IMU data streams and motion events
IMU_MODE_SEND_RAW    = 0x04  # Send raw IMU data streams

# ── sleep modes ──────────────────────────────────────────────────────────
SLEEP_MODE_NORMAL     = 0x00  # Normal sleep mode
SLEEP_MODE_NEVER_SLEEP = 0x01  # Never go to sleep

# ── vibration types ──────────────────────────────────────────────────────
VIBRATION_NONE   = 0x00  # Do not vibrate
VIBRATION_SHORT  = 0x01  # Vibrate for a short amount of time
VIBRATION_MEDIUM = 0x02  # Vibrate for a medium amount of time
VIBRATION_LONG   = 0x03  # Vibrate for a long amount of time

# ── command payloads ─────────────────────────────────────────────────────
SET_MODE_CMD      = bytearray([CMD_SET_MODE, 3, EMG_MODE_SEND_RAW, IMU_MODE_SEND_ALL, 0x00])   # raw EMG + all IMU
NEVER_SLEEP_CMD   = bytearray([CMD_SET_SLEEP, 0x01, SLEEP_MODE_NEVER_SLEEP])         # silent keep‑alive
VIB_CMDS = {
    "short":  bytearray([CMD_VIBRATE, 0x01, VIBRATION_SHORT]),
    "medium": bytearray([CMD_VIBRATE, 0x01, VIBRATION_MEDIUM]),
    "long":   bytearray([CMD_VIBRATE, 0x01, VIBRATION_LONG]),
}
DEEP_SLEEP_CMD    = bytearray([CMD_DEEP_SLEEP, 0x00])

# ── hardware info constants ───────────────────────────────────────────────
MYO_HW_TYPE_MYO        = 0  # Original black Myo
MYO_HW_TYPE_MYO_WHITE  = 1  # White Myo
MYO_HW_TYPE_MYO_BLACK  = 2  # Black Myo
MYO_HW_TYPE_MYO_ALPHA  = 3  # Alpha (prototype) Myo

# Model names mapping
MYO_MODEL_NAMES = {
    MYO_HW_TYPE_MYO_BLACK: "MYO Black",
    MYO_HW_TYPE_MYO_WHITE: "MYO White",
    MYO_HW_TYPE_MYO_ALPHA: "MYOD5",
    0: "Unknown"
}

# ── packet sizes ─────────────────────────────────────────────────────────
EMG_PACKET_SIZE = 16   # Size of EMG data packet (8 sensors × 2 bytes)
IMU_PACKET_SIZE = 20   # Size of IMU data packet (10 values × 2 bytes)

# ── packet formats and data structures ──────────────────────────────────────
"""
EMG Data Format (16 bytes total):
--------------------------------
Each EMG packet contains 8 EMG sensor values, 2 bytes per sensor.
Byte order: Little-endian
Range: -128 to 127 (signed 8-bit)

Bytes 0-7:   First sample from sensors 1-8
Bytes 8-15:  Second sample from sensors 1-8

IMU Data Format (20 bytes total):
--------------------------------
Quaternion (8 bytes):
- w, x, y, z: int16, little-endian
- Scale: Divide by 16384 for normalized values

Accelerometer (6 bytes):
- x, y, z: int16, little-endian
- Scale: Multiply by 2048 for g units

Gyroscope (6 bytes):
- x, y, z: int16, little-endian
- Scale: Multiply by 16 for deg/s
"""

# ── scaling factors ─────────────────────────────────────────────────────────
MYOHW_ORIENTATION_SCALE = 16384.0  # For converting orientation data to normalized values
MYOHW_ACCELEROMETER_SCALE = 2048.0  # For converting accelerometer data to g units
MYOHW_GYROSCOPE_SCALE = 16.0  # For converting gyroscope data to deg/s
