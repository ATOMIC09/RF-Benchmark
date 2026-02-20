from rf433lib import RF433Receiver, RF433Transmitter
from rf433lib.receiver import ReceiverConfig
from rf433lib.transmitter import TransmitterConfig


# Example 1: receive one payload (run on receiver side)
def run_receiver_once():
    receiver = RF433Receiver(ReceiverConfig(port="COM5", baudrate=9600))
    result = receiver.receive_once(on_event=lambda name, payload: print(f"[RX] {name}: {payload}"))
    if result and result.get("success"):
        print("[RX] got bytes:", len(result["data"]))


# Example 2: send payload bytes (run on transmitter side)
def run_sender_once():
    tx = RF433Transmitter(TransmitterConfig(port="COM4", baudrate=9600))
    payload = b"Hello from RF433 library"
    result = tx.send_bytes(payload, mtu=256, gap_ms=3, metadata={"topic": "demo"})
    print("[TX] result:", result)


if __name__ == "__main__":
    print("Use run_receiver_once() on RX side and run_sender_once() on TX side.")
