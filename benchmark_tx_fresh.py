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

MTU_SIZES = [16, 32, 64, 128, 160, 192, 256, 384, 512, 768, 1024, 1280, 1492, 1500]
GAP_MS_LIST = [0, 1, 2, 3, 5, 7, 10]
PACKETS_PER_TEST = 10
REPEATS = 1
WINDOW_SIZE = 12
MAX_ROUNDS = 80
ACK_TIMEOUT = 5.0
MAGIC = 0xA55A
DEBUG = True
LINE = "-" * 78


def print_section(title: str) -> None:
    print(f"\n{LINE}")
    print(title)
    print(LINE)


def fmt_run_result(entry: dict) -> str:
    status = "OK" if not entry["aborted"] else "ABORT"
    return (
        f"[{status:<5}] recv={entry['packets_received']:>3}/{entry['packets_expected']:<3}  "
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
        print(f"\n  • run={run_id}  SYNC  mtu={mtu}  gap={gap_ms}ms  repeat={repeat_idx}")

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
            print(f"    ! SYNC failed (timeout/invalid): {ack}")
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
            print(
                f"    · r{rounds + 1:02d}/{MAX_ROUNDS:02d}  "
                f"pending={len(pending):>3}  burst={seqs[0]:>3}..{seqs[-1]:<3}  "
                f"progress={progress:>5.1f}%"
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
                print(f"    ! REPORT timeout/invalid: {report}")
            continue
        if int(report.get("run_id", -1)) != run_id:
            if DEBUG:
                print(f"    ! REPORT for other run: {report.get('run_id')}")
            continue

        missing = set(int(x) for x in report.get("missing", []))
        crc_fail = int(report.get("crc_fail", crc_fail))
        timeouts = int(report.get("timeouts", timeouts))
        if DEBUG:
            print(
                f"      report  missing={len(missing):>2}  recv_total={int(report.get('received_total', 0)):>3}  "
                f"crc_fail={crc_fail:>3}  timeouts={timeouts:>3}"
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
            print(f"    ! FINAL timeout/invalid: {final}")
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
    print_section("RF433 Fresh Benchmark TX")
    print(f"Port: {PORT}  Baud: {BAUDRATE}  Output: {OUTPUT_FILE}")
    print(
        f"MTU: {MTU_SIZES}  Gap(ms): {GAP_MS_LIST}  "
        f"Packets/test: {PACKETS_PER_TEST}  Repeats: {REPEATS}"
    )

    try:
        for mtu in MTU_SIZES:
            print_section(f"MTU {mtu} bytes")
            mtu_key = str(mtu)
            results.setdefault(mtu_key, [])

            for gap_ms in GAP_MS_LIST:
                for repeat in range(1, REPEATS + 1):
                    print(f"gap={gap_ms:>3}ms  repeat={repeat}/{REPEATS}", flush=True)
                    entry = run_one_test(ser, mtu, gap_ms, repeat)
                    results[mtu_key].append(entry)
                    save_results(results)

                    print(f"  {fmt_run_result(entry)}")
                    time.sleep(0.8)
    finally:
        ser.close()

    print_section("Benchmark Complete")
    print(f"Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
