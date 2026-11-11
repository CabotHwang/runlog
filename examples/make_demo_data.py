"""Create seeded synthetic sway logs with five separate injected faults."""

import json
from pathlib import Path

import numpy as np


def _signals(time, vr, rng):
    amplitude = 0.02 + 0.18 * np.exp(-(((vr - 6) / 1.5) ** 2))
    envelope = np.interp(
        time,
        [0, 30, 70, 230, 270, 300],
        [0.002, 0.002, amplitude, amplitude, 0.002, 0.002],
    )
    phase = rng.uniform(0, 2 * np.pi)
    sway = envelope * np.sin(2 * np.pi * 0.2 * time + phase)
    velocity = np.gradient(sway, time)
    speed = vr * 0.1 + 0.001 * np.sin(2 * np.pi * 0.07 * time + phase)
    force = 5 * np.sin(2 * np.pi * 0.2 * time + phase)
    sway += rng.normal(0, 0.0005, len(time))
    velocity += rng.normal(0, 0.01 * amplitude * 2 * np.pi * 0.2, len(time))
    speed += rng.normal(0, 0.01 * vr * 0.1, len(time))
    force += rng.normal(0, 0.05, len(time))
    return sway, velocity, speed, force, amplitude


def make_demo_data(destination: Path) -> None:
    """Write sixteen synthetic runs, channel units and run attributes."""
    destination.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261109)
    attrs = {}
    for index, vr in enumerate(np.linspace(3, 10, 16), 1):
        time = np.arange(0, 300, 0.1)
        sway, velocity, speed, force, amplitude = _signals(time, vr, rng)
        if index == 3:
            time[1500:] += 2
        elif index == 6:
            force[1200:1230] = force[1199]
        elif index == 9:
            sway[[1100, 1500, 1900]] += 10
        elif index == 12:
            sway = np.clip(sway, -amplitude * 0.7, amplitude * 0.7)
        elif index == 15:
            force[1500:1505] = np.nan
        name = f"run_{index:02d}.csv"
        np.savetxt(
            destination / name,
            np.column_stack((time, sway, velocity, speed, force)),
            delimiter=",",
            header="time,sway,sway_velocity,carriage_speed,fx",
            comments="",
        )
        attrs[name] = {"vr": float(vr), "heading_deg": 90, "repeat": 1}
    (destination / "units.json").write_text(
        json.dumps(
            {"sway": "m", "sway_velocity": "m/s", "carriage_speed": "m/s", "fx": "N"},
            indent=2,
        )
        + "\n"
    )
    (destination / "attrs.json").write_text(json.dumps(attrs, indent=2) + "\n")


if __name__ == "__main__":
    make_demo_data(Path(__file__).resolve().parent / "output/raw")
