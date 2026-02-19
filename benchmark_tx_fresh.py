import json
import os
import random
import struct
import time
import zlib
from serial import Serial

PORT = "COM4"
BAUDRATE = 9600
OUTPUT_FILE = "rf433_results_fresh.json"

MTU_SIZES = [16, 32, 64, 128, 160, 256, 512, 1024, 1500]
GAP_MS_LIST = [0, 1, 2, 3, 5, 7, 10]
PACKETS_PER_TEST = 100
REPEATS = 3
WINDOW_SIZE = 12
MAX_ROUNDS = 20
ACK_TIMEOUT = 5.0
MAGIC = 0xA55A
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
        f"{icon} [{status:<13}] recv={entry['packets_received']:>3}/{entry['packets_expected']:<3}  "
        f"loss={entry['loss']:>5.1f}%  thr={entry['rf_throughput']:>7.1f} B/s  "
        f"crc={entry['crc_failure_percent']:>5.1f}%  to={entry['timeouts']:>3}"
    )


def send_msg(ser: Serial, obj: dict) -> None:
    ser.write((json.dumps(obj) + "\n").encode("utf-8"))
    ser.flush()


def read_line(ser: Serial, timeout_s: float) -> str | None:
    deadline = time.monotonic() + timeout_s
    buf = bytearray()
    while time.monotonic() < deadline:
        b = ser.read(1)
        if not b:
            continue
        if b == b"\n":
            return buf.decode("utf-8", errors="ignore").strip()
        buf.extend(b)
    return None


def recv_msg(ser: Serial, timeout_s: float) -> dict | None:
    line = read_line(ser, timeout_s)
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def build_frame(run_id: int, seq: int, total: int, payload_size: int) -> bytes:
    payload = os.urandom(payload_size)
    header = struct.pack(">HHHHH", MAGIC, run_id, seq, total, payload_size)
    frame_wo_crc = header + payload
    crc = zlib.crc32(frame_wo_crc) & 0xFFFFFFFF
    return frame_wo_crc + struct.pack(">I", crc)


def load_results() -> dict:
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_results(data: dict) -> None:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def run_one_test(ser: Serial, mtu: int, gap_ms: int, repeat_idx: int) -> dict:
    payload_size = mtu - 14
    if payload_size <= 0:
        raise ValueError("MTU too small")

    run_id = random.randint(1, 65535)
    if DEBUG:
        print(
            paint(
                f"\n  ▶ run={run_id}  SYNC  mtu={mtu}  gap={gap_ms}ms  repeat={repeat_idx}",
                C.BOLD,
                C.MAGENTA,
            )
        )

    send_msg(
        ser,
        {
            "type": "SYNC",
            "run_id": run_id,
            "mtu": mtu,
            "count": PACKETS_PER_TEST,
            "window": WINDOW_SIZE,
        },
    )

    ack = recv_msg(ser, timeout_s=ACK_TIMEOUT)
    if not ack or ack.get("type") != "SYNC_ACK" or int(ack.get("run_id", -1)) != run_id:
        if DEBUG:
            print(paint(f"    ⚠ SYNC failed (timeout/invalid): {ack}", C.YELLOW, C.BOLD))
        return {
            "gap_ms": gap_ms,
            "repeat": repeat_idx,
            "rf_throughput": 0.0,
            "expected_throughput": payload_size / ((mtu * 10) / BAUDRATE),
            "loss": 100.0,
            "packets_received": 0,
            "packets_expected": PACKETS_PER_TEST,
            "crc_failure_percent": 100.0,
            "timeouts": 0,
            "aborted": True,
        }

    pending = set(range(PACKETS_PER_TEST))
    rounds = 0
    crc_fail = 0
    timeouts = 0
    start = time.time()

    while pending and rounds < MAX_ROUNDS:
        seqs = sorted(pending)[:WINDOW_SIZE]
        if DEBUG:
            done = PACKETS_PER_TEST - len(pending)
            progress = (done / max(PACKETS_PER_TEST, 1)) * 100
            bar = progress_bar(done, PACKETS_PER_TEST)
            print(
                f"    · r{rounds + 1:02d}/{MAX_ROUNDS:02d}  {bar} {progress:>5.1f}%  "
                f"pending={len(pending):>3}  burst={seqs[0]:>3}..{seqs[-1]:<3}"
            )
        send_msg(ser, {"type": "BURST", "run_id": run_id, "seqs": seqs})

        for seq in seqs:
            ser.write(build_frame(run_id, seq, PACKETS_PER_TEST, payload_size))
            ser.flush()
            if gap_ms > 0:
                time.sleep(gap_ms / 1000.0)

        report = recv_msg(ser, timeout_s=ACK_TIMEOUT)
        rounds += 1
        if not report or report.get("type") != "REPORT":
            if DEBUG:
                print(paint(f"    ⚠ REPORT timeout/invalid: {report}", C.YELLOW))
            continue
        if int(report.get("run_id", -1)) != run_id:
            if DEBUG:
                print(paint(f"    ⚠ REPORT for other run: {report.get('run_id')}", C.YELLOW))
            continue

        missing = set(int(x) for x in report.get("missing", []))
        crc_fail = int(report.get("crc_fail", crc_fail))
        timeouts = int(report.get("timeouts", timeouts))
        if DEBUG:
            print(
                paint(
                    f"      report  missing={len(missing):>2}  recv_total={int(report.get('received_total', 0)):>3}  "
                    f"crc_fail={crc_fail:>3}  timeouts={timeouts:>3}",
                    C.DIM,
                )
            )

        for seq in seqs:
            if seq not in missing and seq in pending:
                pending.remove(seq)

    elapsed = max(time.time() - start, 1e-6)

    send_msg(ser, {"type": "END", "run_id": run_id})
    final = recv_msg(ser, timeout_s=ACK_TIMEOUT)

    if final and final.get("type") == "FINAL" and int(final.get("run_id", -1)) == run_id:
        packets_received = int(final.get("received", PACKETS_PER_TEST - len(pending)))
        loss = float(final.get("loss", ((PACKETS_PER_TEST - packets_received) / PACKETS_PER_TEST) * 100))
        crc_fail = int(final.get("crc_fail", crc_fail))
        timeouts = int(final.get("timeouts", timeouts))
    else:
        if DEBUG:
            print(paint(f"    ⚠ FINAL timeout/invalid: {final}", C.YELLOW))
        packets_received = PACKETS_PER_TEST - len(pending)
        loss = ((PACKETS_PER_TEST - packets_received) / PACKETS_PER_TEST) * 100

    rf_throughput = (packets_received * payload_size) / elapsed
    tx_time_per_pkt = (mtu * 10) / BAUDRATE
    expected_throughput = payload_size / max(tx_time_per_pkt + (gap_ms / 1000.0), 1e-6)
    crc_failure_percent = (crc_fail / max(PACKETS_PER_TEST, 1)) * 100

    return {
        "gap_ms": gap_ms,
        "repeat": repeat_idx,
        "rf_throughput": rf_throughput,
        "expected_throughput": expected_throughput,
        "loss": loss,
        "packets_received": packets_received,
        "packets_expected": PACKETS_PER_TEST,
        "crc_failure_percent": crc_failure_percent,
        "timeouts": timeouts,
        "aborted": bool(pending),
    }


def main() -> None:
    results = load_results()

    time.sleep(2)
    ser = Serial(PORT, baudrate=BAUDRATE, timeout=0.2)
    print_card(
        "RF433 Fresh Benchmark TX",
        f"Port={PORT}  Baud={BAUDRATE}  Packets/test={PACKETS_PER_TEST}  Repeats={REPEATS}",
    )
    print(paint(f"Output file: {OUTPUT_FILE}", C.CYAN))
    print(paint(f"MTU set: {MTU_SIZES}", C.CYAN))
    print(paint(f"Gap set (ms): {GAP_MS_LIST}", C.CYAN))

    try:
        for mtu in MTU_SIZES:
            print_section(f"MTU {mtu} bytes")
            mtu_key = str(mtu)
            results.setdefault(mtu_key, [])

            for gap_ms in GAP_MS_LIST:
                for repeat in range(1, REPEATS + 1):
                    print(
                        paint(
                            f"gap={gap_ms:>3}ms  repeat={repeat}/{REPEATS}",
                            C.BOLD,
                            C.CYAN,
                        ),
                        flush=True,
                    )
                    entry = run_one_test(ser, mtu, gap_ms, repeat)
                    results[mtu_key].append(entry)
                    save_results(results)

                    print(f"  {fmt_run_result(entry)}")
                    time.sleep(0.8)
    finally:
        ser.close()

    print_card("Benchmark Complete", f"Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
