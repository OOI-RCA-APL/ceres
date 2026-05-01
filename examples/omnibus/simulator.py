"""TCP server simulators that mimic submarine instrument feeds.

These simulators let you run the omnibus example without real hardware. Each
simulator extends TCPServer, which is a Component that binds a TCP listener
and calls handle() once per connected client. The driver connects to each
simulator as a regular TCP client.
"""

import math
from datetime import timedelta
from random import gauss, uniform
from typing import override

from ceres import TCPClient, TCPServer
from ceres.concurrency import sleep, spawn
from ceres.data import PositiveTimeDelta


class NavigationSimulator(TCPServer):
    """Simulate a submarine navigation system sending periodic telemetry.

    Sends line-delimited position reports and accepts steering commands:

        Output: NAV <lat> <lon> <depth_m> <heading_deg> <speed_kn>
        Input:  NAV_TO <lat> <lon>
        Input:  NAV_STOP
    """

    # PositiveTimeDelta accepts duration strings like "1s" or "500ms" from YAML.
    interval: PositiveTimeDelta = timedelta(seconds=1)

    @override
    async def handle(self, client: TCPClient) -> None:
        # Starting position near Seattle.
        latitude = 47.6062
        longitude = -122.3321
        depth = 50.0
        heading = 90.0
        speed = 2.5

        # When set, the simulator steers toward this (lat, lon) waypoint.
        target: tuple[float, float] | None = None
        receive_buffer = b""

        # Spawn a concurrent task to read commands from the driver while the
        # main loop continues sending telemetry.
        async def receive_commands() -> None:
            nonlocal target, receive_buffer
            while True:
                chunk = await client.receive()
                receive_buffer += chunk
                while b"\n" in receive_buffer:
                    line, receive_buffer = receive_buffer.split(b"\n", 1)
                    line = line.strip()
                    if line == b"NAV_STOP":
                        target = None
                    elif line.startswith(b"NAV_TO "):
                        parts = line.split()
                        if len(parts) == 3:
                            target = (float(parts[1]), float(parts[2]))

        spawn(receive_commands)

        while True:
            if target is not None:
                # Steer toward the target waypoint, turning at most 5 degrees
                # per tick with a small random wobble for realism.
                target_heading = (
                    math.degrees(
                        math.atan2(target[1] - longitude, target[0] - latitude)
                    )
                    % 360
                )
                delta = (target_heading - heading + 540) % 360 - 180
                heading = (heading + max(-5, min(5, delta)) + gauss(0, 0.5)) % 360
                speed = max(1, min(8, speed + gauss(0, 0.1)))

                # Clear the waypoint once we arrive.
                distance_to_target = math.sqrt(
                    (target[0] - latitude) ** 2 + (target[1] - longitude) ** 2
                )
                if distance_to_target < 0.0001:
                    target = None
            else:
                # Drift randomly when no waypoint is set.
                heading = (heading + gauss(0, 2)) % 360
                speed = max(0, min(8, speed + gauss(0, 0.1)))

            depth = max(5, min(500, depth + gauss(0, 1)))

            # Convert speed in knots to a lat/lon displacement per tick.
            distance = speed * self.interval.total_seconds() / 3600 / 60
            latitude += distance * math.cos(math.radians(heading))
            longitude += distance * math.sin(math.radians(heading))

            line = (
                f"NAV {latitude:.6f} {longitude:.6f} "
                f"{depth:.1f} {heading:.1f} {speed:.2f}\n"
            )
            await client.send(line.encode())
            await sleep(self.interval)


class EnvironmentSimulator(TCPServer):
    """Simulate a submarine environment sensor sending CSV-formatted readings.

    Output: <temperature_c>,<salinity_psu>,<pressure_dbar>,<dissolved_oxygen_ml_l>
    """

    interval: PositiveTimeDelta = timedelta(seconds=2)

    @override
    async def handle(self, client: TCPClient) -> None:
        temperature = 7.5
        salinity = 34.0
        dissolved_oxygen = 6.0
        depth = 50.0

        while True:
            # Random walk each value within realistic ocean bounds.
            temperature = max(-2, min(30, temperature + gauss(0, 0.2)))
            salinity = max(30, min(38, salinity + gauss(0, 0.05)))
            dissolved_oxygen = max(0, min(12, dissolved_oxygen + gauss(0, 0.1)))
            depth = max(5, min(500, depth + gauss(0, 1)))
            pressure = uniform(0.98, 1.02) * depth * 1.01325

            line = (
                f"{temperature:.2f},{salinity:.3f},"
                f"{pressure:.1f},{dissolved_oxygen:.2f}\n"
            )
            await client.send(line.encode())
            await sleep(self.interval)
