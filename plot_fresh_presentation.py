import json
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt
import numpy as np

INPUT_FILE = "rf433_results_fresh.json"
OUT_OVERVIEW = "rf433_presentation_overview.png"
OUT_TOP = "rf433_presentation_top_configs.png"
FONT_FAMILY = "Niramit"
LOSS_LIMIT = 2.0


def load_rows(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for mtu_key, tests in data.items():
        mtu = int(mtu_key)
        by_gap: dict[int, list[dict]] = {}
        for item in tests:
            gap = int(item["gap_ms"])
            by_gap.setdefault(gap, []).append(item)

        for gap, items in by_gap.items():
            avg_thr = mean(x["rf_throughput"] for x in items)
            avg_loss = mean(x["loss"] for x in items)
            avg_crc = mean(x.get("crc_failure_percent", 0.0) for x in items)
            avg_to = mean(x.get("timeouts", 0) for x in items)
            goodput = avg_thr * (1.0 - avg_loss / 100.0)
            robust_goodput = goodput * (1.0 - avg_crc / 100.0)
            rows.append(
                {
                    "mtu": mtu,
                    "gap_ms": gap,
                    "avg_throughput": avg_thr,
                    "avg_loss": avg_loss,
                    "avg_crc": avg_crc,
                    "avg_timeouts": avg_to,
                    "goodput": goodput,
                    "robust_goodput": robust_goodput,
                }
            )
    return rows


def build_matrix(rows: list[dict], key: str, mtus: list[int], gaps: list[int]) -> np.ndarray:
    matrix = np.full((len(gaps), len(mtus)), np.nan)
    index = {(r["gap_ms"], r["mtu"]): r for r in rows}
    for gi, gap in enumerate(gaps):
        for mi, mtu in enumerate(mtus):
            row = index.get((gap, mtu))
            if row:
                matrix[gi, mi] = row[key]
    return matrix


def add_heatmap(ax, matrix: np.ndarray, title: str, mtus: list[int], gaps: list[int], cmap: str):
    im = ax.imshow(matrix, cmap=cmap, aspect="auto")
    ax.set_title(title, fontweight="bold", fontsize=12)
    ax.set_xlabel("MTU (bytes)", fontweight="bold")
    ax.set_ylabel("Gap (ms)", fontweight="bold")
    ax.set_xticks(range(len(mtus)))
    ax.set_xticklabels(mtus)
    ax.set_yticks(range(len(gaps)))
    ax.set_yticklabels(gaps)

    for i in range(len(gaps)):
        for j in range(len(mtus)):
            value = matrix[i, j]
            if not np.isnan(value):
                ax.text(j, i, f"{value:.0f}", ha="center", va="center", fontsize=8)

    return im


def make_overview(rows: list[dict], out_path: str) -> None:
    mtus = sorted({r["mtu"] for r in rows})
    gaps = sorted({r["gap_ms"] for r in rows})

    thr_matrix = build_matrix(rows, "avg_throughput", mtus, gaps)
    robust_matrix = build_matrix(rows, "robust_goodput", mtus, gaps)
    crc_matrix = build_matrix(rows, "avg_crc", mtus, gaps)
    to_matrix = build_matrix(rows, "avg_timeouts", mtus, gaps)

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle("RF433 AS32 Benchmark Overview (9600 baud)", fontsize=18, fontweight="bold")

    im1 = add_heatmap(axes[0, 0], thr_matrix, "Avg Throughput (B/s)", mtus, gaps, "YlGn")
    plt.colorbar(im1, ax=axes[0, 0], fraction=0.046, pad=0.04)

    im2 = add_heatmap(axes[0, 1], robust_matrix, "Robust Goodput (B/s)", mtus, gaps, "viridis")
    plt.colorbar(im2, ax=axes[0, 1], fraction=0.046, pad=0.04)

    im3 = add_heatmap(axes[1, 0], crc_matrix, "Avg CRC Fail (%)", mtus, gaps, "OrRd")
    plt.colorbar(im3, ax=axes[1, 0], fraction=0.046, pad=0.04)

    im4 = add_heatmap(axes[1, 1], to_matrix, "Avg Timeouts", mtus, gaps, "PuRd")
    plt.colorbar(im4, ax=axes[1, 1], fraction=0.046, pad=0.04)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def make_top_configs(rows: list[dict], out_path: str) -> None:
    viable = [r for r in rows if r["avg_loss"] <= LOSS_LIMIT]
    source = viable if viable else rows

    top = sorted(source, key=lambda x: x["robust_goodput"], reverse=True)[:10]
    labels = [f"MTU {r['mtu']} / {r['gap_ms']}ms" for r in top]
    robust_vals = [r["robust_goodput"] for r in top]
    thr_vals = [r["avg_throughput"] for r in top]

    fig, ax = plt.subplots(figsize=(14, 7))
    y = np.arange(len(labels))

    ax.barh(y, thr_vals, alpha=0.35, color="#66b3ff", label="Avg Throughput")
    ax.barh(y, robust_vals, alpha=0.95, color="#1f77b4", label="Robust Goodput")

    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("B/s", fontweight="bold")
    ax.set_title("Top 10 Configurations (Throughput + Robustness)", fontsize=15, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.legend(loc="lower right")

    for i, r in enumerate(top):
        ax.text(
            robust_vals[i] + 3,
            i,
            f"crc={r['avg_crc']:.1f}% to={r['avg_timeouts']:.1f}",
            va="center",
            fontsize=9,
        )

    plt.tight_layout()
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    plt.rcParams["font.family"] = FONT_FAMILY
    plt.rcParams["font.size"] = 10

    rows = load_rows(INPUT_FILE)
    if not rows:
        raise RuntimeError("No rows available to plot.")

    make_overview(rows, OUT_OVERVIEW)
    make_top_configs(rows, OUT_TOP)

    best = max(rows, key=lambda x: x["robust_goodput"])
    print("Generated:")
    print(f"- {Path(OUT_OVERVIEW).resolve()}")
    print(f"- {Path(OUT_TOP).resolve()}")
    print(
        "Best (robust): "
        f"MTU={best['mtu']} gap={best['gap_ms']}ms "
        f"robust_goodput={best['robust_goodput']:.1f} B/s "
        f"thr={best['avg_throughput']:.1f} B/s crc={best['avg_crc']:.1f}%"
    )


if __name__ == "__main__":
    main()
