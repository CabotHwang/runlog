"""Plot stored sway tags and the catalog response curve."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/runlog-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from runlog import load_record, query


def _plot_timeline(axis, dataset: Path, record: dict) -> None:
    record_id = record["record_id"]
    frame, _ = load_record(dataset, record_id)
    segments = query(dataset, "SELECT * FROM segments WHERE record_id=? AND channel=? "
                     "ORDER BY start_s", (record_id, "sway"))
    failed = query(dataset, "SELECT check_name FROM checks WHERE record_id=? AND status='fail'",
                   (record_id,))
    colors = {"quiet": "#e0e6eb", "buildup": "#f9df9b", "steady": "#b8dfc5", "decay": "#c8c4e5"}
    for segment in segments:
        axis.axvspan(segment["start_s"], segment["end_s"], color=colors[segment["tag"]], zorder=0)
    signal, = axis.plot(frame.time, frame.sway, color="#234963", linewidth=0.8, label="Sway")
    qc = ", ".join(row["check_name"] for row in failed) if failed else "no failed checks"
    axis.set_title(f"(a) {record_id} · Vr = {record['vr']:.2f} · QC: {qc}", loc="left")
    axis.set(xlabel="Time [s]", ylabel="Sway [m]",
             xlim=(float(frame.time.iloc[0]), float(frame.time.iloc[-1])))
    axis.legend(handles=[signal] + [Patch(color=color, label=tag) for tag, color in colors.items()],
                loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False)
    axis.grid(alpha=0.2)


def _plot_response(axis, dataset: Path, clean: list[dict]) -> None:
    axis.plot([row["vr"] for row in clean], [row["rms"] for row in clean],
              "o-", color="#234963", markersize=5, label="No failed checks")
    faulty = query(dataset, "SELECT DISTINCT c.record_id, c.check_name, a.value_num AS vr "
                   "FROM checks c JOIN attrs a ON a.record_id=c.record_id AND a.key='vr' "
                   "WHERE c.status='fail' ORDER BY a.value_num")
    markers = ["X", "s", "^", "D", "v"]
    colors = ["#b34d00", "#824b99", "#b52635", "#397c56", "#746400"]
    for run, marker, color in zip(faulty, markers, colors):
        segments = query(dataset, "SELECT rms FROM segments WHERE record_id=? "
                         "AND channel='sway' AND tag='steady' ORDER BY start_s", (run["record_id"],))
        axis.scatter([run["vr"]] * len(segments), [row["rms"] for row in segments],
                     marker=marker, color=color, s=65, zorder=3,
                     label=f"{run['record_id']}: {run['check_name']}")
    axis.set_title("(b) Stored steady-segment RMS", loc="left")
    axis.set(xlabel="Reduced velocity, Vr [dimensionless]", ylabel="Steady sway RMS [m]", ylim=(0, None))
    axis.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False)
    axis.grid(alpha=0.2)


def plot_record() -> Path:
    """Write the README figure from the generated demo dataset."""
    root = Path(__file__).resolve().parents[1]
    dataset = root / "examples/output/dataset"
    clean = query(dataset, "SELECT s.record_id, a.value_num AS vr, s.rms FROM segments s "
                  "JOIN attrs a ON a.record_id=s.record_id AND a.key='vr' "
                  "WHERE s.tag='steady' AND s.channel='sway' AND NOT EXISTS "
                  "(SELECT 1 FROM checks c WHERE c.record_id=s.record_id AND c.status='fail') "
                  "ORDER BY a.value_num")
    peak = max(clean, key=lambda row: row["rms"])
    fig, (timeline, response) = plt.subplots(2, 1, figsize=(12, 8), layout="constrained")
    _plot_timeline(timeline, dataset, peak)
    _plot_response(response, dataset, clean)
    destination = root / "docs/figures/record_timeline.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=160)
    plt.close(fig)
    return destination


if __name__ == "__main__":
    print(plot_record().relative_to(Path(__file__).resolve().parents[1]))
