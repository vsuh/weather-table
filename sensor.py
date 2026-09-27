import asyncio
import time

from bleak import BleakScanner


TARGET_MAC = "A4:C1:38:20:64:92"
SERVICE_UUID = "0000181a-0000-1000-8000-00805f9b34fb"

last_counter = None


def detection_callback(device, advertisement_data):
    global last_counter

    # Только наш датчик
    if device.address.upper() != TARGET_MAC:
        return

    # Ищем Service Data 0x181A
    data = advertisement_data.service_data.get(SERVICE_UUID)

    # На случай другого представления UUID в Bleak
    if data is None:
        for uuid, value in advertisement_data.service_data.items():
            if str(uuid).lower().startswith("0000181a"):
                data = value
                break

    if data is None:
        return

    data = bytes(data)

    # Custom PVWX payload:
    # 0..5   MAC
    # 6..7   temperature
    # 8..9   humidity
    # 10..11 battery mV
    # 12     battery %
    # 13     counter
    # 14     flags

    if len(data) < 15:
        return

    temperature = int.from_bytes(
        data[6:8], "little", signed=True
    ) / 100.0

    humidity = int.from_bytes(
        data[8:10], "little"
    ) / 100.0

    battery_mv = int.from_bytes(
        data[10:12], "little"
    )

    battery_percent = data[12]
    counter = data[13]
    flags = data[14]

    # Датчик передаёт несколько одинаковых рекламных пакетов.
    # Показываем только новое измерение.
    if counter == last_counter:
        return

    last_counter = counter

    now = time.strftime("%H:%M:%S")

    print(
        f"{now}  "
        f"T={temperature:5.2f}°C  "
        f"RH={humidity:5.2f}%  "
        f"BAT={battery_mv:4d}mV  "
        f"{battery_percent:3d}%  "
        f"CNT={counter:3d}  "
        f"FLAGS=0x{flags:02X}",
        flush=True
    )


async def main():
    scanner = BleakScanner(
        detection_callback=detection_callback
    )

    print("Waiting for sensor...")
    print(f"MAC: {TARGET_MAC}")
    print()

    await scanner.start()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await scanner.stop()


asyncio.run(main())
