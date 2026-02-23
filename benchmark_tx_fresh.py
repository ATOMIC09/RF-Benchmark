import hashlib
import json
import random
import time
from pathlib import Path

from rf433lib.transmitter import RF433Transmitter, TransmitterConfig

PORT = "COM4"
BAUDRATE = 9600
OUTPUT_FILE = "rf433_results_fresh.json"
INPUT_FILE: str | None = None

MTU_SIZES = [64, 128, 256, 384, 448, 512, 1024, 1500]
GAP_MS_LIST = [0, 1, 3, 5, 7, 10]
REPEATS = 5
FILE_SIZES_BYTES = [1 * 1024, 10 * 1024, 100 * 1024, 500 * 1024, 1000 * 1024, 2 * 1024 * 1024, 4 * 1024 * 1024]
WINDOW_SIZE = 12
MAX_ROUNDS = 40
ACK_TIMEOUT = 5.0
DEBUG = True
LINE = "-" * 78


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    BLUE = "\033[34m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"


def paint(text: str, *styles: str) -> str:
    return "".join(styles) + text + C.RESET


def progress_bar(done: int, total: int, width: int = 26) -> str:
    if total <= 0:
        return "[" + ("-" * width) + "]"
    ratio = min(max(done / total, 0.0), 1.0)
    fill = int(width * ratio)
    return "[" + ("█" * fill) + ("░" * (width - fill)) + "]"


def print_card(title: str, subtitle: str | None = None) -> None:
    print(paint("┌" + "─" * 76 + "┐", C.CYAN))
    print(paint(f"│ {title:<74} │", C.CYAN, C.BOLD))
    if subtitle:
        print(paint(f"│ {subtitle:<74} │", C.CYAN))
    print(paint("└" + "─" * 76 + "┘", C.CYAN))


def print_section(title: str) -> None:
    print()
    print(paint(LINE, C.BLUE))
    print(paint(title, C.BOLD, C.BLUE))
    print(paint(LINE, C.BLUE))


def fmt_run_result(entry: dict) -> str:
    status_ok = not entry["aborted"]
    status = paint("OK", C.BOLD, C.GREEN) if status_ok else paint("ABORT", C.BOLD, C.RED)
    icon = "✅" if status_ok else "❌"
    return (
        f"{icon} [{status:<13}] recv={entry['chunks_received']:>4}/{entry['chunks_expected']:<4}  "
        f"bytes={entry['bytes_sent']:>7}  loss={entry['loss']:>5.1f}%  "
        f"thr={entry['rf_throughput']:>7.1f} B/s  crc={entry['crc_failure_percent']:>5.1f}%  "
        f"to={entry['timeouts']:>3}"
    )


def build_test_payload(file_path: Path | None, file_size: int, seed: int = 1337) -> tuple[bytes, str]:
    if file_path is not None:
        raw = file_path.read_bytes()
        if file_size > 0:
            if file_size > len(raw):
                raise ValueError(
                    f"Requested file_size={file_size} exceeds source file size ({len(raw)} bytes)"
                )
            raw = raw[:file_size]
        source = f"file:{file_path.name}"
        return raw, source

    if file_size <= 0:
        raise ValueError("file_size must be > 0 when no input file is provided")

    rng = random.Random(seed)
    payload = rng.randbytes(file_size)
    return payload, "generated"


def payload_sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def build_expected_throughput(mtu: int, gap_ms: int, baudrate: int) -> float:
    payload_size = mtu - 14
    tx_time_per_frame = (mtu * 10) / max(baudrate, 1)
    return payload_size / max(tx_time_per_frame + (gap_ms / 1000.0), 1e-6)


def load_results() -> dict:
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_results(data: dict) -> None:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def run_one_test(
    tx: RF433Transmitter,
    payload: bytes,
    payload_hash: str,
    payload_source: str,
    mtu: int,
    gap_ms: int,
    repeat_idx: int,
) -> dict:
    payload_capacity = mtu - 14
    if payload_capacity <= 0:
        raise ValueError(f"MTU={mtu} is too small (must be >= 14)")

    chunks_total = (len(payload) + payload_capacity - 1) // payload_capacity
    min_rounds = (chunks_total + WINDOW_SIZE - 1) // WINDOW_SIZE
    effective_max_rounds = max(MAX_ROUNDS, min_rounds + 8)
    tx.config.max_rounds = effective_max_rounds

    if DEBUG:
        print(
            paint(
                f"\n  ▶ TX file payload  mtu={mtu}  gap={gap_ms}ms  repeat={repeat_idx}  "
                f"chunks={chunks_total}  max_rounds={effective_max_rounds}",
                C.BOLD,
                C.MAGENTA,
            )
        )

    result = tx.send_bytes(
        payload,
        mtu=mtu,
        gap_ms=gap_ms,
        metadata={
            "benchmark": "fresh_file",
            "payload_sha1": payload_hash,
            "payload_source": payload_source,
            "payload_size": len(payload),
            "repeat": repeat_idx,
        },
    )

    chunks_total = int(result.get("chunks_total", 0))
    chunks_received = int(result.get("chunks_received", 0))
    crc_fail_count = int(result.get("crc_fail_count", 0))

    crc_failure_percent = (
        (crc_fail_count / max(chunks_total, 1)) * 100
        if chunks_total > 0
        else 100.0
    )

    return {
        "gap_ms": gap_ms,
        "repeat": repeat_idx,
        "file_size_bytes": len(payload),
        "payload_source": payload_source,
        "payload_sha1": payload_hash,
        "rf_throughput": float(result.get("effective_bps", 0.0)),
        "expected_throughput": build_expected_throughput(mtu, gap_ms, BAUDRATE),
        "loss": float(result.get("loss_percent", 100.0)),
        "chunks_received": chunks_received,
        "chunks_expected": chunks_total,
        "packets_received": chunks_received,
        "packets_expected": chunks_total,
        "bytes_sent": int(result.get("bytes_total", len(payload))),
        "crc_fail_count": crc_fail_count,
        "crc_failure_percent": crc_failure_percent,
        "timeouts": int(result.get("timeouts", 0)),
        "duration_s": float(result.get("duration_s", 0.0)),
        "rounds": int(result.get("rounds", 0)),
        "aborted": bool(result.get("aborted", True)),
    }


def main() -> None:
    input_path = Path(INPUT_FILE) if INPUT_FILE else None
    if input_path is not None and not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if not FILE_SIZES_BYTES:
        raise ValueError("FILE_SIZES_BYTES cannot be empty")

    tx = RF433Transmitter(
        TransmitterConfig(
            port=PORT,
            baudrate=BAUDRATE,
            serial_timeout=0.2,
            ack_timeout=ACK_TIMEOUT,
            window_size=WINDOW_SIZE,
            max_rounds=MAX_ROUNDS,
        )
    )
    results = load_results()

    time.sleep(2)
    print_card(
        "RF433 Fresh Benchmark TX",
        f"Port={PORT}  Baud={BAUDRATE}  FileSizes={FILE_SIZES_BYTES}  Repeats={REPEATS}",
    )
    print(paint(f"Output file: {OUTPUT_FILE}", C.CYAN))
    print(paint(f"MTU set: {MTU_SIZES}", C.CYAN))
    print(paint(f"Gap set (ms): {GAP_MS_LIST}", C.CYAN))

    for target_size in FILE_SIZES_BYTES:
        payload, payload_source = build_test_payload(input_path, target_size)
        payload_hash = payload_sha1(payload)

        print_section(f"FILE SIZE {len(payload)} bytes")
        print(paint(f"Payload source: {payload_source}", C.CYAN))
        print(paint(f"Payload sha1: {payload_hash}", C.CYAN))

        for mtu in MTU_SIZES:
            print_section(f"MTU {mtu} bytes")
            mtu_key = str(mtu)
            results.setdefault(mtu_key, [])

            for gap_ms in GAP_MS_LIST:
                for repeat in range(1, REPEATS + 1):
                    print(
                        paint(
                            f"size={len(payload):>7}B  gap={gap_ms:>3}ms  repeat={repeat}/{REPEATS}",
                            C.BOLD,
                            C.CYAN,
                        ),
                        flush=True,
                    )
                    entry = run_one_test(
                        tx,
                        payload=payload,
                        payload_hash=payload_hash,
                        payload_source=payload_source,
                        mtu=mtu,
                        gap_ms=gap_ms,
                        repeat_idx=repeat,
                    )
                    results[mtu_key].append(entry)
                    save_results(results)

                    print(f"  {fmt_run_result(entry)}")
                    time.sleep(0.8)

    print_card("Benchmark Complete", f"Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
