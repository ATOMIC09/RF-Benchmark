import argparse
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

from rf433lib.receiver import RF433Receiver, ReceiverConfig

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

def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Receive files using RF433 receiver")
    parser.add_argument("--out-dir", default="received_files", help="Directory to save received files")
    parser.add_argument("--port", default="COM5", help="Serial port (default: COM5)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    
    args = parser.parse_args()
    
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config = ReceiverConfig(
        port=args.port,
        baudrate=args.baud,
        sync_timeout=600.0,  # Listen for a long time
        frame_timeout=2.5
    )
    rx = RF433Receiver(config)

    print(paint(f"RF433 File Receiver listening on {args.port}...", C.BOLD, C.CYAN))
    print(f"Saving files to: {out_dir.absolute()}")
    print(paint("Press Ctrl+C to stop.", C.DIM))

    # Stats tracking
    stats = {
        "start_time": 0.0,
        "total_chunks": 0,
        "chunk_size": 256 - 14  # Approximation until sync
    }

    def on_event(event_type: str, payload: dict):
        if event_type == "sync":
            stats["start_time"] = time.time()
            stats["total_chunks"] = int(payload.get("chunks", 0))
            stats["chunk_size"] = int(payload.get("mtu", 256)) - 14
            print(paint(f"\n▶ Incoming transfer detected (Run ID: {payload.get('run_id')})", C.MAGENTA))
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
            
            print(f"\r  {pct:>5.1f}% | {display_speed:>10} | ETA: {eta_str} | Missing: {missing:>4} | CRC Err: {crc_fail}   ", end="")
            
        elif event_type == "final":
            print() 

    try:
        while True:
            # receive_once waits for a SYNC message
            result = rx.receive_once(on_event=on_event)
            
            if not result:
                # Timeout or invalid sync, just continue listening
                continue

            # Process the result
            meta = result.get("metadata", {})
            filename = meta.get("filename", f"received_{int(time.time())}.bin")
            # Sanitize filename
            filename = Path(filename).name 
            
            data = result.get("data", b"")
            success = result.get("success", False)
            
            # Verify checksum if available
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

    except KeyboardInterrupt:
        print(paint("\nStopping receiver...", C.YELLOW))
    except Exception as e:
        print(paint(f"\nError: {e}", C.RED))
        sys.exit(1)

if __name__ == "__main__":
    main()
