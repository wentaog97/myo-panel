"""
myo_constants.py
----------------
All UUIDs and command payloads for the Thalmic Labs MYO armband, split out so
they can be shared by multiple modules (e.g. GUI app, CLI tools, unit tests).
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

# ── command payloads ─────────────────────────────────────────────────────
SET_MODE_CMD      = bytearray([0x01, 3, 0x03, 0x04, 0x00])   # raw EMG + raw IMU
NEVER_SLEEP_CMD   = bytearray([0x09, 0x01, 0x01])            # silent keep‑alive
VIB_CMDS = {
    "short":  bytearray([0x03, 0x01, 0x01]),
    "medium": bytearray([0x03, 0x01, 0x02]),
    "long":   bytearray([0x03, 0x01, 0x03]),
}
DEEP_SLEEP_CMD    = bytearray([0x04, 0x00])
