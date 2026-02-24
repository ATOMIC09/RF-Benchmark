import argparse
import hashlib
import sys
import time
from pathlib import Path

from serial import Serial

from rf433lib.protocol import recv_msg, send_msg
from rf433lib.transmitter import RF433Transmitter, TransmitterConfig


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve files on request (ground-driven)")
    parser.add_argument("--port", default="COM5", help="UART port (default: COM5)")
    parser.add_argument("--baud", type=int, default=9600, help="UART baud (default: 9600)")
    parser.add_argument("--dir", default=".", help="Directory to serve files from")
    parser.add_argument("--capture-file", help="File to serve after CAPTURE (defaults to newest in --dir)")
    parser.add_argument("--once", action="store_true", help="Serve a single request then exit")
    parser.add_argument("--mtu", type=int, default=256, help="MTU size (default: 256)")
    parser.add_argument("--gap", type=int, default=0, help="Inter-frame gap in ms (default: 0)")
    parser.add_argument("--window", type=int, default=12, help="Window size (default: 12)")
    parser.add_argument("--max-rounds", type=int, default=100, help="Max transmission rounds (default: 100)")
    parser.add_argument("--start-delay", type=float, default=0.5, help="Delay before downlink in seconds (default: 0.5)")
    args = parser.parse_args()

    base_dir = Path(args.dir)
    if not base_dir.exists():
        print(paint(f"Directory not found: {base_dir}", C.RED))
        sys.exit(1)

    tx_config = TransmitterConfig(
        port=args.port,
        baudrate=args.baud,
        window_size=args.window,
        max_rounds=args.max_rounds,
    )
    tx = RF433Transmitter(tx_config)

    print(paint("Listening for requests...", C.CYAN))

    while True:
        ser = Serial(args.port, baudrate=args.baud, timeout=0.5)
        try:
            msg = recv_msg(ser, timeout_s=1.0)
            if not msg:
                continue
            msg_type = msg.get("type")

            if msg_type == "CAPTURE":
                if args.capture_file:
                    file_path = base_dir / Path(args.capture_file).name
                else:
                    files = [p for p in base_dir.iterdir() if p.is_file()]
                    file_path = max(files, key=lambda p: p.stat().st_mtime) if files else None

                if not file_path or not file_path.exists():
                    send_msg(ser, {"type": "FILE_INFO", "ok": False, "reason": "not_found"})
                    print(paint("Capture failed: no file", C.YELLOW))
                    if args.once:
                        break
                    continue

                data = file_path.read_bytes()
                sha1 = hashlib.sha1(data).hexdigest()
                total_chunks = (len(data) + (args.mtu - 14) - 1) // (args.mtu - 14)
                send_msg(
                    ser,
                    {
                        "type": "FILE_INFO",
                        "ok": True,
                        "filename": file_path.name,
                        "size": len(data),
                        "sha1": sha1,
                        "mtu": args.mtu,
                        "chunks": total_chunks,
                    },
                )
                print(paint(f"Capture ready: {file_path.name}", C.MAGENTA))
                continue

            if msg_type != "REQUEST":
                continue

            filename = Path(str(msg.get("filename", ""))).name
            file_path = base_dir / filename
            if not filename or not file_path.exists():
                send_msg(ser, {"type": "REQUEST_ACK", "ok": False, "reason": "not_found"})
                print(paint(f"Request rejected: {filename}", C.YELLOW))
                if args.once:
                    break
                continue

            send_msg(ser, {"type": "REQUEST_ACK", "ok": True})
            print(paint(f"Request accepted: {filename}", C.MAGENTA))
        finally:
            ser.close()

        data = file_path.read_bytes()
        sha1 = hashlib.sha1(data).hexdigest()

        if args.start_delay > 0:
            time.sleep(args.start_delay)

        result = tx.send_bytes(
            data,
            mtu=args.mtu,
            gap_ms=args.gap,
            metadata={
                "filename": file_path.name,
                "payload_sha1": sha1,
            },
        )

        if result.get("success"):
            print(paint("Downlink complete", C.GREEN))
        else:
            print(paint("Downlink failed/aborted", C.RED))

        if args.once:
            break


if __name__ == "__main__":
    main()
