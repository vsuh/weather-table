#!/usr/bin/env python3
"""Сканирование BLE для поиска датчика и парсинг его пакетов.

Использование:
    python scan.py                    # сканировать 10 секунд
    python scan.py --duration 30      # сканировать 30 секунд
    python scan.py --continuous       # непрерывный режим
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone

from bleak import BleakScanner
from collector.registry import load_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# UUID сервиса ATC firmware (pvvx custom)
ATC_SERVICE_UUID = "0000181a-0000-1000-8000-00805f9b34fb"


def parse_atc_custom(data: bytes):
    """Парсит ATC Custom payload (service UUID 0x181A)."""
    if not data or len(data) < 15:
        return None

    result = {}
    result["temperature"] = int.from_bytes(data[6:8], "little", signed=True) / 100.0
    result["humidity"] = int.from_bytes(data[8:10], "little") / 100.0
    result["battery_mv"] = int.from_bytes(data[10:12], "little")
    result["battery"] = data[12]
    result["counter"] = data[13]
    result["flags"] = data[14]
    return result


def format_packet(mac: str, rssi: int, raw: bytes, service_uuid: str) -> str:
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"  MAC:     {mac}")
    lines.append(f"  RSSI:    {rssi} dBm")
    lines.append(f"  Service: {service_uuid}")
    lines.append(f"  Время:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append(f"{'='*60}")

    lines.append(f"\nСырые байты ({len(raw)} байт):")
    for i in range(0, len(raw), 16):
        chunk = raw[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        lines.append(f"  {i:04x}: {hex_part}")

    # Пробуем ATC Custom
    reading = parse_atc_custom(raw)
    if reading:
        lines.append(f"\nРаспаршено (ATC Custom / 0x181A):")
        lines.append(f"  Температура: {reading['temperature']}°C")
        lines.append(f"  Влажность:   {reading['humidity']}%")
        lines.append(f"  Батарея:     {reading['battery_mv']}mV ({reading['battery']}%)")
        lines.append(f"  Counter:     {reading['counter']}")
        lines.append(f"  Flags:       0x{reading['flags']:02X}")
        return "\n".join(lines)

    lines.append(f"\n[!] Не удалось распознать формат")
    return "\n".join(lines)


async def scan_bcast(duration: int = 10) -> bool:
    registry = load_registry()
    mac_map = registry.by_mac()
    if not mac_map:
        logger.error("В sensors.yaml нет BLE-датчиков")
        return False

    logger.info("BLE sensors: %s", ", ".join(mac_map.keys()))
    found = []

    def callback(device, advertisement_data):
        mac = device.address.upper()
        if mac not in mac_map:
            return

        service_data = advertisement_data.service_data
        packet_data = b""
        matched_uuid = ""

        for uuid, value in service_data.items():
            uuid_str = str(uuid).lower()
            if uuid_str == ATC_SERVICE_UUID.lower():
                packet_data = value
                matched_uuid = uuid
                break

        if packet_data:
            sensor = mac_map[mac]
            found.append(mac)
            header = f"\n### Датчик: {sensor.id} ({sensor.name})"
            print(header)
            print(format_packet(mac, advertisement_data.rssi, packet_data, str(matched_uuid)))

    logger.info("BLE scan (%ds)...", duration)
    async with BleakScanner(detection_callback=callback):
        await asyncio.sleep(duration)

    if found:
        logger.info("Найдено пакетов: %d", len(found))
        return True
    return False


async def main():
    parser = argparse.ArgumentParser(description="BLE Scanner for Weather Sensor")
    parser.add_argument("--duration", "-d", type=int, default=10,
                        help="Время сканирования (сек, по умолчанию: 10)")
    parser.add_argument("--continuous", "-c", action="store_true",
                        help="Непрерывный режим")
    parser.add_argument("--interval", "-i", type=int, default=10,
                        help="Интервал в непрерывном режиме (сек)")
    args = parser.parse_args()

    if args.continuous:
        logger.info("Непрерывный режим (Ctrl+C для выхода)...")
        while True:
            try:
                await scan_bcast(duration=5)
                logger.info("Пауза %ds...", args.interval)
                await asyncio.sleep(args.interval)
            except KeyboardInterrupt:
                logger.info("Прервано.")
                break
    else:
        ok = await scan_bcast(duration=args.duration)
        if not ok:
            logger.warning(
                "Датчик не найден.\n"
                "Проверьте: датчик включён, BLE-адаптер работает"
            )
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
