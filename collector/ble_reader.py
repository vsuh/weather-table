"""Сканер BLE-устройств через bleak (мульти-датчиковый).

Сканер устойчив к проблемам с Bluetooth: если адаптер выключен/пропал или
датчики надолго замолчали, исключение не выходит наружу (иначе падает весь
коллектор и systemd спамит рестартами), а сканер перезапускается с
нарастающей паузой. В лог пишется одно предупреждение при потере BLE,
напоминание раз в час и одно сообщение при восстановлении.
"""

import asyncio
import logging
import time
from typing import Callable

from bleak import BleakScanner
from bleak.exc import BleakBluetoothNotAvailableError

import config
from collector.registry import SensorRegistry, SensorConfig

logger = logging.getLogger(__name__)

RETRY_MIN_S = 30        # первая пауза между попытками перезапуска сканера
RETRY_MAX_S = 600       # потолок экспоненциальной паузы
REMINDER_S = 3600       # как часто напоминать, что BLE всё ещё недоступен
STALL_TIMEOUT_S = 300   # нет ни одного пакета от датчиков столько секунд -> перезапуск


class _BleStalled(Exception):
    """Сканер запущен, но пакеты от датчиков не приходят."""


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


async def _scan_once(
    mac_map: dict[str, SensorConfig],
    packet_callback: Callable[[SensorConfig, bytes, int, str], None],
    on_alive: Callable[[], None],
) -> None:
    """Один сеанс сканирования. Завершается только исключением (или отменой)."""
    state = {"last_packet": time.monotonic()}

    def detection_callback(device, advertisement_data):
        mac = device.address.upper()
        sensor = mac_map.get(mac)
        if sensor is None:
            return

        data, service_uuid = _find_service_data(advertisement_data.service_data)
        if not data:
            return

        state["last_packet"] = time.monotonic()
        on_alive()
        packet_callback(sensor, data, advertisement_data.rssi, service_uuid)

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(1)
            if time.monotonic() - state["last_packet"] > STALL_TIMEOUT_S:
                raise _BleStalled(
                    f"нет пакетов от датчиков более {STALL_TIMEOUT_S} с"
                )
    finally:
        try:
            await scanner.stop()
        except Exception:  # noqa: BLE001 - адаптер мог пропасть, это не критично
            logger.debug("Ошибка при остановке BLE-сканера", exc_info=True)
        logger.debug("BLE scanner stopped")


async def run_scanner(
    registry: SensorRegistry,
    packet_callback: Callable[[SensorConfig, bytes, int, str], None],
) -> None:
    """
    Непрерывно сканирует BLE и вызывает packet_callback на каждый пакет
    любого из BLE-датчиков реестра.

    При ошибках Bluetooth не падает: ждёт и перезапускает сканер
    (пауза 30 -> 60 -> ... -> 600 с), не засоряя лог.

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

    health = {"down_since": None, "delay": RETRY_MIN_S}

    def on_alive() -> None:
        """Вызывается на каждый пакет: BLE работает, сбрасываем состояние сбоя."""
        if health["down_since"] is not None:
            minutes = (time.monotonic() - health["down_since"]) / 60
            logger.info("BLE восстановлен, простой около %.0f мин", minutes)
            health["down_since"] = None
        health["delay"] = RETRY_MIN_S

    last_reminder = 0.0

    while True:
        try:
            await _scan_once(mac_map, packet_callback, on_alive)
            reason = "сканер завершился без ошибки"
        except asyncio.CancelledError:
            raise
        except BleakBluetoothNotAvailableError:
            reason = ("адаптер Bluetooth выключен или недоступен "
                      "(sudo rfkill unblock bluetooth; bluetoothctl power on)")
        except _BleStalled as exc:
            reason = str(exc)
        except Exception as exc:  # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
            logger.debug("Подробности ошибки BLE", exc_info=True)

        now = time.monotonic()
        if health["down_since"] is None:
            health["down_since"] = now
            last_reminder = now
            logger.warning(
                "BLE недоступен: %s. Повторные попытки с паузой %d-%d с ",
                reason, RETRY_MIN_S, RETRY_MAX_S,
            )
        elif now - last_reminder >= REMINDER_S:
            last_reminder = now
            logger.warning(
                "BLE всё ещё недоступен уже %.0f мин: %s",
                (now - health["down_since"]) / 60, reason,
            )
        else:
            logger.debug("BLE по-прежнему недоступен: %s", reason)

        await asyncio.sleep(health["delay"])
        health["delay"] = min(health["delay"] * 2, RETRY_MAX_S)
