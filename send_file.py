import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

from rf433lib.transmitter import RF433Transmitter, TransmitterConfig

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

def progress_bar(done: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return "[" + ("-" * width) + "]"
    ratio = min(max(done / total, 0.0), 1.0)
    fill = int(width * ratio)
    return "[" + ("█" * fill) + ("░" * (width - fill)) + "]"

def fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} B"

def main():
    parser = argparse.ArgumentParser(description="Send a file using RF433 transmitter")
    parser.add_argument("file", help="Path to the file to send")
    parser.add_argument("--port", default="COM4", help="Serial port (default: COM4)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--mtu", type=int, default=256, help="MTU size (default: 256)")
    parser.add_argument("--gap", type=int, default=0, help="Inter-frame gap in ms (default: 0)")
    parser.add_argument("--window", type=int, default=12, help="Window size (default: 12)")
    parser.add_argument("--max-rounds", type=int, default=100, help="Max transmission rounds (default: 100)")
    
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(paint(f"Error: File '{args.file}' not found.", C.RED))
        sys.exit(1)

    file_content = file_path.read_bytes()
    file_size = len(file_content)
    file_sha1 = hashlib.sha1(file_content).hexdigest()

    print(paint(f"\nPreparing to send: {file_path.name}", C.BOLD, C.CYAN))
    print(f"Size: {fmt_size(file_size)} ({file_size} bytes)")
    print(f"SHA1: {file_sha1}")
    print(f"Config: Port={args.port}, Baud={args.baud}, MTU={args.mtu}, Gap={args.gap}ms")
    print(paint("-" * 60, C.DIM))

    config = TransmitterConfig(
        port=args.port,
        baudrate=args.baud,
        window_size=args.window,
        max_rounds=args.max_rounds
    )
    tx = RF433Transmitter(config)

    # Statistics tracking
    stats = {
        "start_time": 0.0,
        "bytes_total": file_size,
        "chunk_size": args.mtu - 14
    }

    def on_event(event_type: str, payload: dict):
        if event_type == "sync_sent":
            stats["start_time"] = time.time()
            
        elif event_type == "report":
            round_idx = int(payload.get("round", 0))
            pending = int(payload.get("pending", 0))
            
            total_chunks = (stats["bytes_total"] + stats["chunk_size"] - 1) // stats["chunk_size"]
            chunks_done = max(total_chunks - pending, 0)
            bytes_done = min(chunks_done * stats["chunk_size"], stats["bytes_total"])
            
            elapsed = time.time() - stats["start_time"]
            speed = bytes_done / elapsed if elapsed > 0 else 0.0
            
            if speed > 0:
                eta_s = (stats["bytes_total"] - bytes_done) / speed
                eta_str = f"{int(eta_s // 60)}:{int(eta_s % 60):02d}"
            else:
                eta_str = "--:--"
                
            bar = progress_bar(chunks_done, total_chunks)
            pct = (chunks_done / max(total_chunks, 1)) * 100.0
            
            display_speed = f"{speed:.1f} B/s"
            if speed > 1024:
                display_speed = f"{speed/1024:.1f} KB/s"
            
            print(f"\rRound {round_idx:02d}: {bar} {pct:>5.1f}% | {display_speed:>10} | ETA: {eta_str} | Pending: {pending:>4}   ", end="")

    try:
        start_time = time.time()
        result = tx.send_bytes(
            file_content,
            mtu=args.mtu,
            gap_ms=args.gap,
            metadata={
                "filename": file_path.name,
                "payload_sha1": file_sha1
            },
            on_event=on_event
        )
        duration = time.time() - start_time
        print() 

        if result.get("success"):
            print(paint("\n✅ Transfer Complete!", C.BOLD, C.GREEN))
            print(f"Time: {duration:.2f}s")
            print(f"Speed: {result.get('effective_bps', 0):.1f} B/s")
            print(f"Rounds: {result.get('rounds')}")
            print(f"Loss: {result.get('loss_percent'):.1f}%")
        else:
            print(paint("\n❌ Transfer Failed/Aborted", C.BOLD, C.RED))
            print(f"Success: {result.get('success')}")
            print(f"Aborted: {result.get('aborted')}")

    except Exception as e:
        print(paint(f"\nError: {e}", C.RED))
        sys.exit(1)

if __name__ == "__main__":
    main()
