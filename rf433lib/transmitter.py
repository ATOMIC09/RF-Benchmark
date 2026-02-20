import random
import time
from dataclasses import dataclass

from serial import Serial

from .protocol import build_frame, recv_msg, send_msg


@dataclass
class TransmitterConfig:
    port: str = "COM4"
    baudrate: int = 9600
    serial_timeout: float = 0.2
    ack_timeout: float = 5.0
    window_size: int = 12
    max_rounds: int = 40


class RF433Transmitter:
    def __init__(self, config: TransmitterConfig | None = None):
        self.config = config or TransmitterConfig()

    def send_bytes(
        self,
        data: bytes,
        mtu: int = 256,
        gap_ms: int = 0,
        metadata: dict | None = None,
        on_event=None,
    ) -> dict:
        payload_capacity = mtu - 14
        if payload_capacity <= 0:
            raise ValueError("MTU must be >= 14")

        total_chunks = (len(data) + payload_capacity - 1) // payload_capacity
        chunks = [
            data[i * payload_capacity : (i + 1) * payload_capacity]
            for i in range(total_chunks)
        ]

        run_id = random.randint(1, 65535)
        ser = Serial(
            self.config.port,
            baudrate=self.config.baudrate,
            timeout=self.config.serial_timeout,
        )

        try:
            sync_msg = {
                "type": "SYNC",
                "mode": "DATA",
                "run_id": run_id,
                "mtu": mtu,
                "count": total_chunks,
                "total_size": len(data),
                "window": self.config.window_size,
                "meta": metadata or {},
            }
            send_msg(ser, sync_msg)
            if on_event:
                on_event("sync_sent", sync_msg)

            ack = recv_msg(ser, timeout_s=self.config.ack_timeout)
            if not ack or ack.get("type") != "SYNC_ACK" or int(ack.get("run_id", -1)) != run_id:
                return {
                    "success": False,
                    "reason": "sync_failed",
                    "run_id": run_id,
                    "bytes_total": len(data),
                    "chunks_total": total_chunks,
                }

            pending = set(range(total_chunks))
            rounds = 0
            crc_fail = 0
            timeouts = 0
            start = time.time()

            while pending and rounds < self.config.max_rounds:
                seqs = sorted(pending)[: self.config.window_size]
                send_msg(ser, {"type": "BURST", "run_id": run_id, "seqs": seqs})

                for seq in seqs:
                    frame = build_frame(run_id, seq, total_chunks, chunks[seq], mtu)
                    ser.write(frame)
                    ser.flush()
                    if gap_ms > 0:
                        time.sleep(gap_ms / 1000.0)

                report = recv_msg(ser, timeout_s=self.config.ack_timeout)
                rounds += 1

                if not report or report.get("type") != "REPORT":
                    continue
                if int(report.get("run_id", -1)) != run_id:
                    continue

                missing = set(int(x) for x in report.get("missing", []))
                crc_fail = int(report.get("crc_fail", crc_fail))
                timeouts = int(report.get("timeouts", timeouts))

                if on_event:
                    on_event(
                        "report",
                        {
                            "run_id": run_id,
                            "round": rounds,
                            "pending": len(pending),
                            "missing": len(missing),
                            "crc_fail": crc_fail,
                            "timeouts": timeouts,
                        },
                    )

                for seq in seqs:
                    if seq not in missing:
                        pending.discard(seq)

            elapsed = max(time.time() - start, 1e-6)

            send_msg(ser, {"type": "END", "run_id": run_id})
            final = recv_msg(ser, timeout_s=self.config.ack_timeout)

            if final and final.get("type") == "FINAL" and int(final.get("run_id", -1)) == run_id:
                received = int(final.get("received", total_chunks - len(pending)))
                loss = float(final.get("loss", ((total_chunks - received) / max(total_chunks, 1)) * 100))
                crc_fail = int(final.get("crc_fail", crc_fail))
                timeouts = int(final.get("timeouts", timeouts))
            else:
                received = total_chunks - len(pending)
                loss = ((total_chunks - received) / max(total_chunks, 1)) * 100

            result = {
                "success": not pending,
                "run_id": run_id,
                "bytes_total": len(data),
                "chunks_total": total_chunks,
                "chunks_received": received,
                "loss_percent": loss,
                "crc_fail_count": crc_fail,
                "timeouts": timeouts,
                "rounds": rounds,
                "duration_s": elapsed,
                "effective_bps": len(data) / elapsed,
                "aborted": bool(pending),
            }
            if on_event:
                on_event("final", result)
            return result
        finally:
            ser.close()

    def send_text(self, text: str, **kwargs) -> dict:
        return self.send_bytes(text.encode("utf-8"), **kwargs)
