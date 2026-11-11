"""Plot the prescribed force and integrated displacement of the controlled example."""

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/runlog-matplotlib")
import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from runlog import load_record, query


def plot_record() -> Path:
    root = Path(__file__).resolve().parents[1]
    dataset = root / "examples/output/forced_oscillator"
    frame, meta = load_record(dataset, "forced_oscillator")
    metadata = json.loads(
        (root / "examples/output/forced_oscillator_input/metadata.json").read_text(encoding="utf-8")
    )
    if meta.attrs["input_sha256"] != metadata["csv_sha256"]:
        raise ValueError("processed record and input metadata do not match")
    params = metadata["params"]
    segments = query(dataset, "SELECT * FROM segments WHERE channel='x' ORDER BY start_s")
    checks = query(dataset, "SELECT status FROM checks")
    passed = sum(row["status"] == "pass" for row in checks)
    colors = {"quiet": "#e0e6eb", "buildup": "#f9df9b", "steady": "#b8dfc5", "decay": "#c8c4e5"}
    fig, (drive_axis, response_axis) = plt.subplots(
        2,
        1,
        figsize=(11, 5.5),
        sharex=True,
        layout="constrained",
        gridspec_kw={"height_ratios": [0.7, 1.3]},
    )
    drive_axis.plot(frame.time, frame.force, color="#6c7278", linewidth=0.8)
    drive_axis.set(title="Input: prescribed harmonic force", ylabel="Force [N]")
    for time, label in [(params["drive_on_s"], "Drive on"), (params["drive_off_s"], "Drive off")]:
        for axis in (drive_axis, response_axis):
            axis.axvline(time, color="#6c7278", linestyle="--", linewidth=0.8)
        drive_axis.text(
            time + 3,
            0.8 * params["force_amplitude_n"],
            label,
            fontsize=9,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85},
        )
    present = []
    for segment in segments:
        response_axis.axvspan(
            segment["start_s"],
            min(segment["end_s"], frame.time.iloc[-1]),
            color=colors[segment["tag"]],
            zorder=0,
        )
        if segment["tag"] not in present:
            present.append(segment["tag"])
    response_axis.plot(frame.time, frame.x, color="#234963", linewidth=0.85)
    response_axis.set(
        title=f"Output: integrated displacement · {passed}/{len(checks)} checks pass",
        ylabel="Displacement [m]",
        xlabel="Time [s]",
        xlim=(frame.time.iloc[0], frame.time.iloc[-1]),
    )
    response_axis.legend(
        handles=[Patch(color=colors[tag], label=tag) for tag in present],
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        frameon=False,
    )
    fig.suptitle("Controlled forced/damped oscillator — numerical demonstration", fontsize=12)
    for axis in (drive_axis, response_axis):
        axis.grid(alpha=0.2)
    destination = root / "docs/figures/record_timeline.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=160)
    plt.close(fig)
    return destination


if __name__ == "__main__":
    print(plot_record().relative_to(Path(__file__).resolve().parents[1]))
