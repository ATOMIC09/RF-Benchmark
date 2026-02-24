import json
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt
import numpy as np

INPUT_FILE = "rf433_results_fresh_ded_at_512_7ms_1024000.json"
OUTPUT_DIR = "rf433_plots_fresh_ded_at_512_7ms_1024000"
FONT_FAMILY = "Niramit"
LOSS_LIMIT = 2.0
BASE_FONT_SIZE = 14


def load_rows(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for mtu_key, tests in data.items():
        mtu = int(mtu_key)
        by_size_gap: dict[tuple[int, int], list[dict]] = {}
        for item in tests:
            file_size = int(item.get("file_size_bytes", item.get("bytes_sent", 0)))
            gap = int(item["gap_ms"])
            by_size_gap.setdefault((file_size, gap), []).append(item)

        for (file_size, gap), items in by_size_gap.items():
            avg_thr = mean(x["rf_throughput"] for x in items)
            avg_loss = mean(x["loss"] for x in items)
            avg_crc = mean(x.get("crc_failure_percent", 0.0) for x in items)
            avg_to = mean(x.get("timeouts", 0) for x in items)
            avg_rounds = mean(x.get("rounds", 0) for x in items)
            goodput = avg_thr * (1.0 - avg_loss / 100.0)
            robust_goodput = goodput * (1.0 - avg_crc / 100.0)
            rows.append(
                {
                    "file_size_bytes": file_size,
                    "mtu": mtu,
                    "gap_ms": gap,
                    "avg_throughput": avg_thr,
                    "avg_loss": avg_loss,
                    "avg_crc": avg_crc,
                    "avg_timeouts": avg_to,
                    "avg_rounds": avg_rounds,
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
    ax.set_title(title, fontweight="bold", fontsize=20)
    ax.set_xlabel("MTU (bytes)", fontweight="bold", fontsize=16)
    ax.set_ylabel("Gap (ms)", fontweight="bold", fontsize=16)
    ax.set_xticks(range(len(mtus)))
    ax.set_xticklabels(mtus)
    ax.set_yticks(range(len(gaps)))
    ax.set_yticklabels(gaps)
    ax.tick_params(axis="both", labelsize=14)

    for i in range(len(gaps)):
        for j in range(len(mtus)):
            value = matrix[i, j]
            if not np.isnan(value):
                ax.text(j, i, f"{value:.0f}", ha="center", va="center", fontsize=12)

    return im


def size_label(file_size: int) -> str:
    if file_size % (1024 * 1024) == 0 and file_size >= 1024 * 1024:
        return f"{file_size // (1024 * 1024)}MB"
    if file_size % 1024 == 0 and file_size >= 1024:
        return f"{file_size // 1024}KB"
    return f"{file_size}B"


def make_overview(rows: list[dict], file_size: int, out_path: str) -> None:
    mtus = sorted({r["mtu"] for r in rows})
    gaps = sorted({r["gap_ms"] for r in rows})

    thr_matrix = build_matrix(rows, "avg_throughput", mtus, gaps)
    robust_matrix = build_matrix(rows, "robust_goodput", mtus, gaps)
    crc_matrix = build_matrix(rows, "avg_crc", mtus, gaps)
    to_matrix = build_matrix(rows, "avg_timeouts", mtus, gaps)

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(
        f"RF433 Benchmark Overview (size={size_label(file_size)}, 9600 baud)",
        fontsize=28,
        fontweight="bold",
    )

    im1 = add_heatmap(axes[0, 0], thr_matrix, "Avg Throughput (B/s)", mtus, gaps, "YlGn")
    plt.colorbar(im1, ax=axes[0, 0], fraction=0.046, pad=0.04)

    im2 = add_heatmap(axes[0, 1], robust_matrix, "Robust Goodput (B/s)", mtus, gaps, "viridis")
    plt.colorbar(im2, ax=axes[0, 1], fraction=0.046, pad=0.04)

    im3 = add_heatmap(axes[1, 0], crc_matrix, "Avg CRC Fail (%)", mtus, gaps, "OrRd")
    plt.colorbar(im3, ax=axes[1, 0], fraction=0.046, pad=0.04)

    im4 = add_heatmap(axes[1, 1], to_matrix, "Avg Timeouts", mtus, gaps, "PuRd")
    plt.colorbar(im4, ax=axes[1, 1], fraction=0.046, pad=0.04)

    plt.tight_layout(rect=(0.0, 0.0, 1.0, 0.95))
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def make_top_configs(rows: list[dict], file_size: int, out_path: str) -> None:
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
    ax.set_xlabel("B/s", fontweight="bold", fontsize=16)
    ax.set_title(
        f"Top 10 Configurations (size={size_label(file_size)})",
        fontsize=24,
        fontweight="bold",
    )
    ax.tick_params(axis="both", labelsize=14)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.legend(loc="lower right", fontsize=14)

    for i, r in enumerate(top):
        ax.text(
            robust_vals[i] + 3,
            i,
            f"crc={r['avg_crc']:.1f}% to={r['avg_timeouts']:.1f}",
            va="center",
            fontsize=12,
        )

    plt.tight_layout()
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def make_filesize_summary(rows: list[dict], out_path: str) -> None:
    sizes = sorted({r["file_size_bytes"] for r in rows})
    best_per_size: list[dict] = []

    for file_size in sizes:
        subset = [r for r in rows if r["file_size_bytes"] == file_size]
        viable = [r for r in subset if r["avg_loss"] <= LOSS_LIMIT]
        source = viable if viable else subset
        if source:
            best_per_size.append(max(source, key=lambda x: x["robust_goodput"]))

    labels = [size_label(x["file_size_bytes"]) for x in best_per_size]
    robust_vals = [x["robust_goodput"] for x in best_per_size]
    thr_vals = [x["avg_throughput"] for x in best_per_size]

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(labels))
    width = 0.35

    ax.bar(x - width / 2, thr_vals, width=width, label="Avg Throughput", color="#66b3ff")
    ax.bar(x + width / 2, robust_vals, width=width, label="Robust Goodput", color="#1f77b4")

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("B/s", fontweight="bold", fontsize=16)
    ax.set_title("Best Configuration by File Size", fontsize=24, fontweight="bold")
    ax.tick_params(axis="both", labelsize=14)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend(fontsize=14)

    for idx, row in enumerate(best_per_size):
        ax.text(
            x[idx],
            robust_vals[idx] + 5,
            f"MTU {row['mtu']} / {row['gap_ms']}ms",
            ha="center",
            fontsize=12,
        )

    plt.tight_layout()
    plt.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    plt.rcParams["font.family"] = FONT_FAMILY
    plt.rcParams["font.size"] = BASE_FONT_SIZE

    rows = load_rows(INPUT_FILE)
    if not rows:
        raise RuntimeError("No rows available to plot.")

    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    sizes = sorted({r["file_size_bytes"] for r in rows})
    generated: list[Path] = []

    for file_size in sizes:
        subset = [r for r in rows if r["file_size_bytes"] == file_size]
        size_tag = size_label(file_size).lower()

        overview = output_dir / f"overview_{size_tag}.png"
        top_cfg = output_dir / f"top_configs_{size_tag}.png"

        make_overview(subset, file_size, str(overview))
        make_top_configs(subset, file_size, str(top_cfg))

        generated.extend([overview, top_cfg])

    summary = output_dir / "summary_by_file_size.png"
    make_filesize_summary(rows, str(summary))
    generated.append(summary)

    viable = [r for r in rows if r["avg_loss"] <= LOSS_LIMIT]
    best = max((viable if viable else rows), key=lambda x: x["robust_goodput"])

    print("Generated:")
    for file_path in generated:
        print(f"- {file_path.resolve()}")
    print(
        "Best (robust): "
        f"size={size_label(best['file_size_bytes'])} "
        f"MTU={best['mtu']} gap={best['gap_ms']}ms "
        f"robust_goodput={best['robust_goodput']:.1f} B/s "
        f"thr={best['avg_throughput']:.1f} B/s crc={best['avg_crc']:.1f}%"
    )


if __name__ == "__main__":
    main()
