"""Сканер BLE-устройств через bleak (мульти-датчиковый)."""

import asyncio
import logging
from typing import Callable

from bleak import BleakScanner

import config
from collector.registry import SensorRegistry, SensorConfig

logger = logging.getLogger(__name__)


def _find_service_data(service_data: dict) -> tuple[bytes, str]:
    """Ищет payload ATC Custom (UUID 0x181A) среди service data.

    Returns:
        (payload_bytes, matched_uuid) или (b"", "").
    """
    atc = config.ATC_SERVICE_UUID.lower()

    for uuid, value in service_data.items():
        if str(uuid).lower() == atc:
            return bytes(value), str(uuid)

    return b"", ""


async def run_scanner(
    registry: SensorRegistry,
    packet_callback: Callable[[SensorConfig, bytes, int, str], None],
) -> None:
    """
    Непрерывно сканирует BLE и вызывает packet_callback на каждый пакет
    любого из BLE-датчиков реестра.

    Args:
        registry: реестр датчиков.
        packet_callback: колбэк(sensor, raw_data, rssi, service_uuid).
    """
    mac_map = registry.by_mac()
    if not mac_map:
        logger.warning("No BLE sensors configured, scanner idle")
        return

    logger.info("BLE scanner started for %d sensors: %s",
                len(mac_map), ", ".join(mac_map.keys()))

    def detection_callback(device, advertisement_data):
        mac = device.address.upper()
        sensor = mac_map.get(mac)
        if sensor is None:
            return

        data, service_uuid = _find_service_data(advertisement_data.service_data)
        if not data:
            return

        packet_callback(sensor, data, advertisement_data.rssi, service_uuid)

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await scanner.stop()
        logger.info("BLE scanner stopped")
