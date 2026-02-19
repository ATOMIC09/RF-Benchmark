import json
import struct
import time
import zlib
from serial import Serial

PORT = "COM5"
BAUDRATE = 9600
READ_TIMEOUT = 0.2
MAGIC = 0xA55A
DEBUG = True


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
    if payload_len != len(payload):
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
    }


def main() -> None:
    ser = Serial(PORT, baudrate=BAUDRATE, timeout=READ_TIMEOUT)
    print(f"Fresh RX listening on {PORT} @ {BAUDRATE}")

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
                state = {
                    "run_id": run_id,
                    "mtu": mtu,
                    "total": total,
                    "received": set(),
                    "crc_fail": 0,
                    "timeouts": 0,
                }
                send_msg(ser, {"type": "SYNC_ACK", "run_id": run_id})
                print(f"SYNC run={run_id} mtu={mtu} total={total}")
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
                        f"  BURST run={run_id} size={len(seqs)} seq={seqs[0]}..{seqs[-1]} "
                        f"recv_total={len(state['received'])}"
                    )

                missing = set(seqs)
                for idx, _ in enumerate(seqs, start=1):
                    raw = read_exact(ser, state["mtu"], timeout_s=2.5)
                    if raw is None:
                        state["timeouts"] += 1
                        if DEBUG:
                            print(
                                f"    timeout while reading frame {idx}/{len(seqs)} "
                                f"(timeouts={state['timeouts']})"
                            )
                        break

                    decoded = decode_frame(raw, state["mtu"])
                    if not decoded.get("ok"):
                        state["crc_fail"] += 1
                        if DEBUG:
                            print(f"    crc/frame error (crc_fail={state['crc_fail']})")
                        continue

                    if decoded["run_id"] != state["run_id"]:
                        continue

                    seq = decoded["seq"]
                    if seq in missing:
                        missing.discard(seq)
                        state["received"].add(seq)

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
                        f"  REPORT run={run_id} missing={len(missing)} preview={preview} "
                        f"recv_total={len(state['received'])} crc_fail={state['crc_fail']} "
                        f"timeouts={state['timeouts']}"
                    )
                continue

            if msg_type == "END":
                if int(msg.get("run_id", -1)) != state["run_id"]:
                    continue

                received = len(state["received"])
                total = state["total"]
                loss = ((total - received) / total) * 100 if total else 100.0
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
                print(
                    f"DONE run={state['run_id']} recv={received}/{total} "
                    f"loss={loss:.1f}% crc_fail={state['crc_fail']}"
                )
                state = None
    finally:
        ser.close()


if __name__ == "__main__":
    main()
