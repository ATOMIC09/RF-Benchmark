import hashlib
import json
import struct
import time
import zlib
from pathlib import Path
from serial import Serial

PORT = "COM5"
BAUDRATE = 9600
READ_TIMEOUT = 0.2
MAGIC = 0xA55A
DEBUG = True
SAVE_RECEIVED_FILE = True
SAVE_PARTIAL_FILE = False
RECEIVED_DIR = "rx_received_files"


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


def print_card(title: str, subtitle: str | None = None) -> None:
    print(paint("┌" + "─" * 76 + "┐", C.CYAN))
    print(paint(f"│ {title:<74} │", C.CYAN, C.BOLD))
    if subtitle:
        print(paint(f"│ {subtitle:<74} │", C.CYAN))
    print(paint("└" + "─" * 76 + "┘", C.CYAN))


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


def read_exact(ser: Serial, size: int, timeout_s: float) -> bytes | None:
    deadline = time.monotonic() + timeout_s
    out = bytearray()
    while len(out) < size and time.monotonic() < deadline:
        chunk = ser.read(size - len(out))
        if chunk:
            out.extend(chunk)
    return bytes(out) if len(out) == size else None


def decode_frame(frame: bytes, mtu: int) -> dict:
    if len(frame) != mtu or mtu < 14:
        return {"ok": False}

    try:
        magic, run_id, seq, total, payload_len = struct.unpack(">HHHHH", frame[:10]
        )
    except struct.error:
        return {"ok": False}

    if magic != MAGIC:
        return {"ok": False}

    payload = frame[10:-4]
    if payload_len > len(payload):
        return {"ok": False}

    expected_crc = zlib.crc32(frame[:-4]) & 0xFFFFFFFF
    actual_crc = struct.unpack(">I", frame[-4:])[0]
    if expected_crc != actual_crc:
        return {"ok": False, "seq": seq, "run_id": run_id}

    return {
        "ok": True,
        "run_id": run_id,
        "seq": seq,
        "total": total,
        "payload_len": payload_len,
        "payload": payload[:payload_len],
    }


def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def main() -> None:
    ser = Serial(PORT, baudrate=BAUDRATE, timeout=READ_TIMEOUT)
    print_card("RF433 Fresh Benchmark RX", f"Listening on {PORT} @ {BAUDRATE}")

    state = None

    try:
        while True:
            msg = recv_msg(ser, timeout_s=120)
            if not msg:
                continue

            msg_type = msg.get("type")

            if msg_type == "SYNC":
                run_id = int(msg["run_id"])
                mtu = int(msg["mtu"])
                total = int(msg["count"])
                total_size = int(msg.get("total_size", 0))
                meta = msg.get("meta", {}) or {}
                state = {
                    "run_id": run_id,
                    "mtu": mtu,
                    "total": total,
                    "total_size": total_size,
                    "meta": meta,
                    "received": set(),
                    "chunks": [None] * total,
                    "crc_fail": 0,
                    "timeouts": 0,
                }
                send_msg(ser, {"type": "SYNC_ACK", "run_id": run_id})
                print(
                    paint(
                        f"\n▶ SYNC  run={run_id}  mtu={mtu}  total={total}  size={total_size}",
                        C.BOLD,
                        C.MAGENTA,
                    )
                )
                continue

            if state is None:
                continue

            if msg_type == "BURST":
                run_id = int(msg.get("run_id", -1))
                seqs = [int(x) for x in msg.get("seqs", [])]
                if run_id != state["run_id"]:
                    continue

                if DEBUG and seqs:
                    print(
                        paint(
                            f"  · BURST run={run_id} size={len(seqs)} seq={seqs[0]}..{seqs[-1]} "
                            f"recv_total={len(state['received'])}",
                            C.BLUE,
                        )
                    )

                missing = set(seqs)
                for idx, _ in enumerate(seqs, start=1):
                    raw = read_exact(ser, state["mtu"], timeout_s=2.5)
                    if raw is None:
                        state["timeouts"] += 1
                        if DEBUG:
                            print(
                                paint(
                                    f"    ⚠ timeout while reading frame {idx}/{len(seqs)} "
                                    f"(timeouts={state['timeouts']})",
                                    C.YELLOW,
                                )
                            )
                        break

                    decoded = decode_frame(raw, state["mtu"])
                    if not decoded.get("ok"):
                        state["crc_fail"] += 1
                        if DEBUG:
                            print(
                                paint(
                                    f"    ✖ crc/frame error (crc_fail={state['crc_fail']})",
                                    C.RED,
                                )
                            )
                        continue

                    if decoded["run_id"] != state["run_id"]:
                        continue

                    seq = decoded["seq"]
                    if seq in missing:
                        missing.discard(seq)
                        state["received"].add(seq)
                    if 0 <= seq < state["total"]:
                        state["chunks"][seq] = decoded["payload"]

                send_msg(
                    ser,
                    {
                        "type": "REPORT",
                        "run_id": state["run_id"],
                        "missing": sorted(missing),
                        "received_total": len(state["received"]),
                        "crc_fail": state["crc_fail"],
                        "timeouts": state["timeouts"],
                    },
                )
                if DEBUG:
                    preview = sorted(missing)[:6]
                    print(
                        paint(
                            f"  report run={run_id} missing={len(missing)} preview={preview} "
                            f"recv_total={len(state['received'])} crc_fail={state['crc_fail']} "
                            f"timeouts={state['timeouts']}",
                            C.DIM,
                        )
                    )
                continue

            if msg_type == "END":
                if int(msg.get("run_id", -1)) != state["run_id"]:
                    continue

                received = len(state["received"])
                total = state["total"]
                loss = ((total - received) / total) * 100 if total else 100.0

                reconstructed = b""
                if received == total:
                    reconstructed = b"".join(chunk or b"" for chunk in state["chunks"])
                    if state["total_size"] > 0:
                        reconstructed = reconstructed[: state["total_size"]]

                expected_sha1 = str(state["meta"].get("payload_sha1", ""))
                actual_sha1 = sha1_hex(reconstructed) if reconstructed else ""
                hash_ok = bool(reconstructed) and bool(expected_sha1) and expected_sha1 == actual_sha1

                should_save = False
                if SAVE_RECEIVED_FILE:
                    if received == total:
                        should_save = True
                    elif SAVE_PARTIAL_FILE:
                        reconstructed = b"".join(chunk or b"" for chunk in state["chunks"])
                        if state["total_size"] > 0:
                            reconstructed = reconstructed[: state["total_size"]]
                        should_save = True

                saved_path = None
                if should_save:
                    out_dir = Path(RECEIVED_DIR)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    status = "ok" if received == total else "partial"
                    filename = f"run_{state['run_id']}_{status}.bin"
                    out_path = out_dir / filename
                    out_path.write_bytes(reconstructed)
                    saved_path = str(out_path)

                send_msg(
                    ser,
                    {
                        "type": "FINAL",
                        "run_id": state["run_id"],
                        "received": received,
                        "expected": total,
                        "loss": loss,
                        "crc_fail": state["crc_fail"],
                        "timeouts": state["timeouts"],
                    },
                )
                if saved_path:
                    print(
                        paint(
                            f"💾 saved: {saved_path}",
                            C.CYAN,
                        )
                    )

                hash_note = ""
                if expected_sha1:
                    if received == total:
                        hash_note = f" sha1={'OK' if hash_ok else 'MISMATCH'}"
                    else:
                        hash_note = " sha1=SKIP(incomplete)"

                print(
                    paint(
                        f"✅ DONE run={state['run_id']} recv={received}/{total} "
                        f"loss={loss:.1f}% crc_fail={state['crc_fail']}{hash_note}",
                        C.BOLD,
                        C.GREEN,
                    )
                )
                state = None
    finally:
        ser.close()


if __name__ == "__main__":
    main()
