import argparse
import hashlib
import sys
import time
from pathlib import Path

from serial import Serial

from rf433lib.protocol import recv_msg, send_msg
from rf433lib.receiver import RF433Receiver, ReceiverConfig


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"


def paint(text: str, *styles: str) -> str:
    return "".join(styles) + text + C.RESET


def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ground-driven request + receive")
    parser.add_argument("file", nargs="?", help="File name to request (optional if using --capture)")
    parser.add_argument("--port", default="COM4", help="UART port (default: COM4)")
    parser.add_argument("--baud", type=int, default=9600, help="UART baud (default: 9600)")
    parser.add_argument("--out-dir", default="received_files", help="Directory to save received files")
    parser.add_argument("--capture", action="store_true", help="Send CAPTURE command before requesting")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(args.file).name if args.file else ""

    ser = Serial(args.port, baudrate=args.baud, timeout=0.5)
    try:
        if args.capture:
            print(paint("Sending CAPTURE command...", C.CYAN))
            send_msg(ser, {"type": "CAPTURE"})
            info = recv_msg(ser, timeout_s=5.0)
            if not info or info.get("type") != "FILE_INFO" or not info.get("filename"):
                reason = info.get("reason") if isinstance(info, dict) else "no_info"
                print(paint(f"Capture failed: {reason}", C.RED))
                sys.exit(1)
            filename = Path(str(info.get("filename"))).name
            print(paint("File ready:", C.GREEN))
            print(f"  Name: {filename}")
            print(f"  Size: {info.get('size', 0)} bytes")
            if info.get("sha1"):
                print(f"  SHA1: {info.get('sha1')}")

        if not filename:
            print(paint("No file specified. Provide a filename or use --capture.", C.RED))
            sys.exit(1)

        print(paint("Sending request...", C.CYAN))
        send_msg(ser, {"type": "REQUEST", "filename": filename})
        ack = recv_msg(ser, timeout_s=2.0)
    finally:
        ser.close()

    if not ack or ack.get("type") != "REQUEST_ACK" or not ack.get("ok"):
        reason = ack.get("reason") if isinstance(ack, dict) else "no_ack"
        print(paint(f"Request failed: {reason}", C.RED))
        sys.exit(1)

    print(paint("Request accepted. Waiting for downlink...", C.MAGENTA))

    rx_config = ReceiverConfig(
        port=args.port,
        baudrate=args.baud,
        sync_timeout=600.0,
        frame_timeout=2.5,
    )
    rx = RF433Receiver(rx_config)

    stats = {
        "start_time": 0.0,
        "total_chunks": 0,
        "chunk_size": 256 - 14,
    }

    def on_event(event_type: str, payload: dict) -> None:
        if event_type == "sync":
            stats["start_time"] = time.time()
            stats["total_chunks"] = int(payload.get("chunks", 0))
            stats["chunk_size"] = int(payload.get("mtu", 256)) - 14
            print(paint(f"\n▶ Incoming transfer (Run ID: {payload.get('run_id')})", C.MAGENTA))
            print(f"  Total chunks: {stats['total_chunks']} (MTU: {payload.get('mtu')})")
        elif event_type == "report":
            chunks_recv = int(payload.get("received_total", 0))
            missing = len(payload.get("missing", []))
            crc_fail = int(payload.get("crc_fail", 0))

            elapsed = time.time() - stats["start_time"]
            bytes_done = chunks_recv * stats["chunk_size"]
            speed = bytes_done / elapsed if elapsed > 0 else 0.0

            total_bytes = stats["total_chunks"] * stats["chunk_size"]
            if speed > 0:
                eta_s = (total_bytes - bytes_done) / speed
                eta_str = f"{int(eta_s // 60)}:{int(eta_s % 60):02d}"
            else:
                eta_str = "--:--"

            display_speed = f"{speed:.1f} B/s"
            if speed > 1024:
                display_speed = f"{speed/1024:.1f} KB/s"

            pct = (chunks_recv / max(stats["total_chunks"], 1)) * 100.0
            print(
                f"\r  {pct:>5.1f}% | {display_speed:>10} | ETA: {eta_str} | Missing: {missing:>4} | CRC Err: {crc_fail}   ",
                end="",
            )
        elif event_type == "final":
            print()

    result = rx.receive_once(on_event=on_event)
    if not result:
        print(paint("No transfer received (timeout).", C.RED))
        sys.exit(1)

    meta = result.get("metadata", {})
    filename = Path(meta.get("filename", f"received_{int(time.time())}.bin")).name

    data = result.get("data", b"")
    success = result.get("success", False)

    expected_sha1 = meta.get("payload_sha1")
    actual_sha1 = sha1_hex(data) if data else ""
    hash_match = (expected_sha1 == actual_sha1) if expected_sha1 else True

    status_color = C.GREEN if (success and hash_match) else C.RED
    status_text = "SUCCESS" if (success and hash_match) else "PARTIAL/CORRUPT"

    print(paint(f"  Transfer Finished: {status_text}", status_color, C.BOLD))

    save_path = out_dir / filename
    if not success:
        save_path = out_dir / f"{filename}.partial"

    print(f"  Saving to: {save_path}")
    save_path.write_bytes(data)

    if expected_sha1:
        print(f"  SHA1 Check: {'MATCH' if hash_match else 'MISMATCH'}")
        if not hash_match:
            print(f"   Expected: {expected_sha1}")
            print(f"   Actual:   {actual_sha1}")

    print(paint("-" * 50, C.DIM))


if __name__ == "__main__":
    main()
