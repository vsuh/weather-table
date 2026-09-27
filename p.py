#!/usr/bin/env python3
"""Тестовый скрипт: парсит ATC Custom пакет и выводит в консоль.

ATC Custom format (UUID 0x181A):
  [0:6]   MAC (6 bytes)
  [6:8]   temperature (int16 LE, /100)
  [8:10]  humidity (uint16 LE, /100)
  [10:12] battery mV (uint16 LE)
  [12]    battery %
  [13]    counter
  [14]    flags

Использование:
    python p.py                         # встроенный пробный пакет
    python p.py <hex-строка>            # произвольный пакет
"""

import sys
from collector.parser import parse_atc_custom, parse_bthome_v2

# Пробный ATC Custom пакет (15 байт):
#   MAC: 92 64 20 38 c1 a4
#   T:   6c 09 → 2412 → 24.12°C
#   RH:  4c 18 → 6220 → 62.20%
#   BAT: 3c 36 → 13756 mV
#   BAT%: 87 (0x57)
#   CNT: 05
#   FLG: 00
PROBE_PACKET_HEX = "92642038c1a46c094c183c36570500"

if len(sys.argv) > 1:
    hex_str = sys.argv[1].replace(" ", "").replace(":", "")
else:
    hex_str = PROBE_PACKET_HEX
    print(f"[пробный пакет ATC Custom] {hex_str}\n")

print(f"Пакет: {hex_str}")
print(f"Длина: {len(hex_str) // 2} байт\n")

raw_data = bytes.fromhex(hex_str)

# Сырые байты
print("Сырые байты:")
for i in range(0, len(raw_data), 16):
    chunk = raw_data[i:i+16]
    hex_part = " ".join(f"{b:02x}" for b in chunk)
    lines = [hex_part]
    print(f"  {i:04x}: {hex_part}")

# Парсим ATC Custom
reading = parse_atc_custom(raw_data)
if reading:
    print(f"\n{'='*40}")
    print("Распаршено (ATC Custom):")
    if reading.temperature is not None:
        print(f"  Температура: {reading.temperature}°C")
    if reading.humidity is not None:
        print(f"  Влажность:   {reading.humidity}%")
    if reading.battery_mv is not None:
        print(f"  Батарея:     {reading.battery_mv}mV")
    if reading.battery is not None:
        print(f"  Батарея:     {reading.battery}%")
    if reading.counter is not None:
        print(f"  Counter:     {reading.counter}")
    if reading.flags is not None:
        print(f"  Flags:       0x{reading.flags:02X}")
    print(f"{'='*40}")
else:
    # Пробуем BTHome v2
    reading = parse_bthome_v2(raw_data)
    if reading:
        print(f"\n{'='*40}")
        print("Распаршено (BTHome v2):")
        if reading.temperature is not None:
            print(f"  Температура: {reading.temperature}°C")
        if reading.humidity is not None:
            print(f"  Влажность:   {reading.humidity}%")
        if reading.battery is not None:
            print(f"  Батарея:     {reading.battery}%")
        print(f"{'='*40}")
    else:
        print("\n[!] Не удалось распарсить пакет")
        sys.exit(1)
