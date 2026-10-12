"""Парсер протокола ATC_MiThermometer firmware (pvvx custom).

Поддерживаемый формат:
  ATC Custom (PVWX) — service UUID 0x181A, фиксированный layout
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
#   0..5   MAC (6 bytes, в обратном порядке)
#   6..7   temperature (2 bytes, signed, /100)
#   8..9   humidity (2 bytes, unsigned, /100)
#   10..11 battery mV (2 bytes, unsigned)
#   12     battery % (1 byte)
#   13     counter (1 byte)
#   14     flags (1 byte)
#   15+    optional extra data
ATC_CUSTOM_MIN_LEN = 15


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
