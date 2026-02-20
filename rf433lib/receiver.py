from dataclasses import dataclass

from serial import Serial

from .protocol import decode_frame, read_exact, recv_msg, send_msg


@dataclass
class ReceiverConfig:
    port: str = "COM5"
    baudrate: int = 9600
    serial_timeout: float = 0.2
    sync_timeout: float = 120.0
    frame_timeout: float = 2.5


class RF433Receiver:
    def __init__(self, config: ReceiverConfig | None = None):
        self.config = config or ReceiverConfig()

    def receive_once(self, on_event=None) -> dict | None:
        ser = Serial(
            self.config.port,
            baudrate=self.config.baudrate,
            timeout=self.config.serial_timeout,
        )

        try:
            sync = recv_msg(ser, timeout_s=self.config.sync_timeout)
            if not sync or sync.get("type") != "SYNC":
                return None

            run_id = int(sync["run_id"])
            mtu = int(sync["mtu"])
            total_chunks = int(sync["count"])
            total_size = int(sync.get("total_size", 0))
            metadata = sync.get("meta", {})

            chunks: list[bytes | None] = [None] * total_chunks
            crc_fail = 0
            timeouts = 0

            send_msg(ser, {"type": "SYNC_ACK", "run_id": run_id})
            if on_event:
                on_event("sync", {"run_id": run_id, "mtu": mtu, "chunks": total_chunks})

            while True:
                msg = recv_msg(ser, timeout_s=self.config.sync_timeout)
                if not msg:
                    continue

                msg_type = msg.get("type")

                if msg_type == "BURST":
                    msg_run = int(msg.get("run_id", -1))
                    seqs = [int(x) for x in msg.get("seqs", [])]
                    if msg_run != run_id:
                        continue

                    missing = set(seqs)
                    for _ in seqs:
                        raw = read_exact(ser, mtu, timeout_s=self.config.frame_timeout)
                        if raw is None:
                            timeouts += 1
                            break

                        decoded = decode_frame(raw, mtu)
                        if not decoded.get("ok"):
                            crc_fail += 1
                            continue

                        if int(decoded["run_id"]) != run_id:
                            continue

                        seq = int(decoded["seq"])
                        if 0 <= seq < total_chunks:
                            chunks[seq] = decoded["payload"]
                            missing.discard(seq)

                    report = {
                        "type": "REPORT",
                        "run_id": run_id,
                        "missing": sorted(missing),
                        "received_total": sum(chunk is not None for chunk in chunks),
                        "crc_fail": crc_fail,
                        "timeouts": timeouts,
                    }
                    send_msg(ser, report)
                    if on_event:
                        on_event("report", report)
                    continue

                if msg_type == "END":
                    if int(msg.get("run_id", -1)) != run_id:
                        continue

                    received = sum(chunk is not None for chunk in chunks)
                    loss = ((total_chunks - received) / max(total_chunks, 1)) * 100
                    final = {
                        "type": "FINAL",
                        "run_id": run_id,
                        "received": received,
                        "expected": total_chunks,
                        "loss": loss,
                        "crc_fail": crc_fail,
                        "timeouts": timeouts,
                    }
                    send_msg(ser, final)

                    payload = b"".join(chunk or b"" for chunk in chunks)
                    if total_size > 0:
                        payload = payload[:total_size]

                    result = {
                        "success": received == total_chunks,
                        "run_id": run_id,
                        "data": payload,
                        "metadata": metadata,
                        "chunks_received": received,
                        "chunks_expected": total_chunks,
                        "loss_percent": loss,
                        "crc_fail_count": crc_fail,
                        "timeouts": timeouts,
                    }
                    if on_event:
                        on_event("final", result)
                    return result
        finally:
            ser.close()

    def receive_text_once(self, on_event=None) -> str | None:
        result = self.receive_once(on_event=on_event)
        if not result or not result.get("success"):
            return None
        return result["data"].decode("utf-8", errors="ignore")
