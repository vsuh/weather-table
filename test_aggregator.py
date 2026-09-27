"""Тест логики агрегатора (запуск: python test_aggregator.py)."""

import asyncio
import sys

sys.path.insert(0, ".")

from collector.parser import parse_atc_custom
from collector.aggregator import SensorAggregator
from collector.registry import SensorConfig

# packet: counter=05, T=24.12, RH=62.20, BAT=13884mV, 87%
PKT_A = bytes.fromhex("92642038c1a46c094c183c36570500")
# packet: counter=06, T=24.50, RH=62.00, BAT=13884mV, 87%
PKT_B = bytes.fromhex("92642038c1a492264026 3c36570600".replace(" ", ""))


async def main():
    sensor = SensorConfig(
        id="living_room", name="Комната", location="living_room",
        source="ble", mac="A4:C1:38:20:64:92", protocol="atc",
    )
    agg = SensorAggregator(sensor, window_seconds=60)

    ra = parse_atc_custom(PKT_A)
    print(f"Packet A: T={ra.temperature} RH={ra.humidity} CNT={ra.counter}")

    statuses = [agg.add_packet(ra, -70) for _ in range(3)]
    print(f"Same counter x3 -> statuses: {statuses}")

    rb = parse_atc_custom(PKT_B)
    print(f"Packet B: T={rb.temperature} RH={rb.humidity} CNT={rb.counter}")
    statuses2 = [agg.add_packet(rb, -68) for _ in range(2)]
    print(f"New counter x2 -> statuses: {statuses2}")

    print(f"\nUnique measurements: {len(agg._measurements)} (expected 2)")
    print(f"Total packets: {agg._total_packets} (expected 5)")
    print(f"Duplicates: {agg._total_duplicates} (expected 3)")
    print(f"should_flush immediately: {agg.should_flush()} (expected False)")

    ok = (len(agg._measurements) == 2 and agg._total_duplicates == 3)
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")


asyncio.run(main())
