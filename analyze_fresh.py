import json
from statistics import mean

INPUT_FILE = "rf433_results_fresh.json"
LOSS_LIMIT = 2.0


def main() -> None:
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for mtu_key, tests in data.items():
        mtu = int(mtu_key)
        by_gap = {}
        for t in tests:
            gap = int(t["gap_ms"])
            by_gap.setdefault(gap, []).append(t)

        for gap, items in by_gap.items():
            avg_thr = mean(x["rf_throughput"] for x in items)
            avg_loss = mean(x["loss"] for x in items)
            avg_crc = mean(x.get("crc_failure_percent", 0.0) for x in items)
            goodput = avg_thr * (1.0 - avg_loss / 100.0)
            rows.append(
                {
                    "mtu": mtu,
                    "gap_ms": gap,
                    "avg_throughput": avg_thr,
                    "avg_loss": avg_loss,
                    "avg_crc": avg_crc,
                    "goodput": goodput,
                }
            )

    viable = [r for r in rows if r["avg_loss"] <= LOSS_LIMIT]
    if viable:
        best = max(viable, key=lambda r: (r["goodput"], -r["mtu"]))
    else:
        best = max(rows, key=lambda r: r["goodput"])

    print("\n=== TOP 10 (by goodput) ===")
    for r in sorted(rows, key=lambda x: x["goodput"], reverse=True)[:10]:
        print(
            f"MTU={r['mtu']:>3} gap={r['gap_ms']:>3}ms "
            f"goodput={r['goodput']:.1f}B/s thr={r['avg_throughput']:.1f}B/s "
            f"loss={r['avg_loss']:.2f}% crc={r['avg_crc']:.2f}%"
        )

    print("\n=== RECOMMENDED POINT ===")
    print(
        f"MTU={best['mtu']} gap={best['gap_ms']}ms "
        f"goodput={best['goodput']:.1f}B/s "
        f"throughput={best['avg_throughput']:.1f}B/s "
        f"loss={best['avg_loss']:.2f}% crc={best['avg_crc']:.2f}%"
    )


if __name__ == "__main__":
    main()
