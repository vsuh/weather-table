"""Парсеры протоколов ATC_MiThermometer firmware.

Поддерживаемые форматы:
  1. ATC Custom (PVWX) — service UUID 0x181A, фиксированный layout
  2. BTHome v2 — service UUID 0x181C, LEB128 encoding
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SensorReading:
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    battery_mv: Optional[int] = None
    battery: Optional[int] = None
    counter: Optional[int] = None
    flags: Optional[int] = None
    rssi: Optional[int] = None


# ============================================================
# ATC Custom format (PVWX) — service UUID 0x181A
# ============================================================
# Layout (15+ байт):
#   0..5   MAC (6 bytes)
#   6..7   temperature (2 bytes, signed, /100)
#   8..9   humidity (2 bytes, unsigned, /100)
#   10..11 battery mV (2 bytes, unsigned)
#   12     battery % (1 byte)
#   13     counter (1 byte)
#   14     flags (1 byte)
#   15+    optional extra data
ATC_CUSTOM_MIN_LEN = 15

# ============================================================
# BTHome v2 format — service UUID 0x181C
# ============================================================
BTHOME_TEMPERATURE_ID = 0x0001    # Temperature, 2 bytes signed, 0.01°C
BTHOME_HUMIDITY_ID = 0x0002       # Relative humidity, 2 bytes unsigned, 0.01%
BTHOME_BATTERY_ID = 0x000B        # Battery, 1 byte, %


def _decode_leb128(data: bytes, offset: int) -> tuple[int, int]:
    """Decode LEB128-encoded integer. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        result |= (byte & 0x7F) << shift
        offset += 1
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, offset


def parse_atc_custom(data: bytes) -> Optional[SensorReading]:
    """Парсит ATC Custom payload (service UUID 0x181A).

    Формат:
      [0:6]   MAC
      [6:8]   temperature (int16 LE, /100)
      [8:10]  humidity (uint16 LE, /100)
      [10:12] battery mV (uint16 LE)
      [12]    battery %
      [13]    counter
      [14]    flags
    """
    if not data or len(data) < ATC_CUSTOM_MIN_LEN:
        logger.debug("ATC Custom: too short (%d bytes)", len(data) if data else 0)
        return None

    reading = SensorReading()

    # Temperature: int16 LE, /100
    reading.temperature = int.from_bytes(data[6:8], "little", signed=True) / 100.0

    # Humidity: uint16 LE, /100
    reading.humidity = int.from_bytes(data[8:10], "little") / 100.0

    # Battery mV: uint16 LE
    reading.battery_mv = int.from_bytes(data[10:12], "little")

    # Battery %
    reading.battery = data[12]

    # Counter (для dedup)
    reading.counter = data[13]

    # Flags
    reading.flags = data[14]

    logger.debug(
        "ATC Custom: T=%.2f RH=%.2f BAT=%dmV(%d%%) CNT=%d FLG=0x%02X",
        reading.temperature, reading.humidity,
        reading.battery_mv, reading.battery,
        reading.counter, reading.flags,
    )

    return reading


def parse_bthome_v2(data: bytes) -> Optional[SensorReading]:
    """Парсит BTHome v2 payload (service UUID 0x181C).

    Формат:
      Control byte (1B) + Data objects (variable)
      Data object: Data ID (LEB128) + Length (LEB128) + Value (variable)
    """
    if not data or len(data) < 1:
        logger.debug("Empty or too short BTHome data")
        return None

    control_byte = data[0]
    version = (control_byte >> 4) & 0x0F
    if version != 2:
        logger.warning(
            "Expected BTHome v2 (control=0x%02X), got version %d",
            control_byte, version,
        )
        return None

    offset = 1
    reading = SensorReading()
    data_len = len(data)

    while offset < data_len:
        # Decode data ID (LEB128)
        try:
            data_id, offset = _decode_leb128(data, offset)
        except Exception as e:
            logger.warning("Failed to decode data ID at offset %d: %s", offset, e)
            break

        # Decode data length (LEB128)
        try:
            data_length, offset = _decode_leb128(data, offset)
        except Exception as e:
            logger.warning("Failed to decode data length at offset %d: %s", offset, e)
            break

        if offset + data_length > data_len:
            break

        value_bytes = data[offset:offset + data_length]
        offset += data_length

        if data_id == BTHOME_TEMPERATURE_ID:
            reading.temperature = int.from_bytes(value_bytes, "little", signed=True) / 100.0
        elif data_id == BTHOME_HUMIDITY_ID:
            reading.humidity = int.from_bytes(value_bytes, "little") / 100.0
        elif data_id == BTHOME_BATTERY_ID:
            reading.battery = value_bytes[0]

    return reading
