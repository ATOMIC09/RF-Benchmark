import json
import struct
import time
import zlib
from serial import Serial

MAGIC = 0xA55A


def send_msg(ser: Serial, obj: dict) -> None:
    ser.write((json.dumps(obj) + "\n").encode("utf-8"))
    ser.flush()


def read_line(ser: Serial, timeout_s: float) -> str | None:
    deadline = time.monotonic() + timeout_s
    buf = bytearray()
    while time.monotonic() < deadline:
        byte = ser.read(1)
        if not byte:
            continue
        if byte == b"\n":
            return buf.decode("utf-8", errors="ignore").strip()
        buf.extend(byte)
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


def build_frame(run_id: int, seq: int, total: int, payload: bytes, mtu: int) -> bytes:
    payload_capacity = mtu - 14
    if payload_capacity <= 0:
        raise ValueError("MTU must be at least 14 bytes")
    if len(payload) > payload_capacity:
        raise ValueError("Payload chunk exceeds MTU payload capacity")

    payload_len = len(payload)
    padded_payload = payload + (b"\x00" * (payload_capacity - payload_len))

    header = struct.pack(">HHHHH", MAGIC, run_id, seq, total, payload_len)
    frame_wo_crc = header + padded_payload
    crc = zlib.crc32(frame_wo_crc) & 0xFFFFFFFF
    return frame_wo_crc + struct.pack(">I", crc)


def decode_frame(frame: bytes, mtu: int) -> dict:
    if len(frame) != mtu or mtu < 14:
        return {"ok": False}

    try:
        magic, run_id, seq, total, payload_len = struct.unpack(">HHHHH", frame[:10])
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
