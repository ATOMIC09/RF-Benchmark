import serial
import time
import struct
import random
import zlib

# --- Configuration ---
PORT = 'COM4'  # Change to your TX port
BAUDRATE = 9600
PACKETS_PER_TEST = 100

# Fine-grained buffer limit sweep: 8-byte steps from 16 to 256
# Goal: find maximum MTU the RF module buffer can hold before overflow
MTU_SIZES = [16, 32, 64, 128, 256, 512, 1024, 1492, 1500]

def send_test_batch(ser, mtu):
    print(f"\n--- Testing MTU: {mtu} bytes ---")

    # Generate random seed for this batch
    random_seed = random.randint(0, 2**32 - 1)

    # Send SYNC header
    # Format: 'SYNC' + MTU (unsigned short) + SEED (unsigned int)
    sync_packet = b'SYNC' + struct.pack('<H I', mtu, random_seed)
    ser.write(sync_packet)
    ser.flush()
    time.sleep(1.5) # Give receiver time to parse SYNC and get ready

    for seq in range(PACKETS_PER_TEST):
        # Packet: Start Byte (1) + Seq Num (4) + Random Payload + CRC32 (4)
        # So payload_size = mtu - 1 - 4 - 4 = mtu - 9
        payload_size = mtu - 9

        # Generate deterministic random payload based on seed and sequence
        rng = random.Random(random_seed + seq)
        random_payload = bytes([rng.randint(0, 255) for _ in range(payload_size)])

        # Calculate CRC32 of the payload
        crc32 = zlib.crc32(random_payload) & 0xFFFFFFFF

        # Pack packet: start byte + seq + payload + crc32
        packet = struct.pack('<B I', 0xAA, seq) + random_payload + struct.pack('<I', crc32)
        ser.write(packet)
        ser.flush()  # Block until bytes are physically out of UART - no sleep needed

        print(f"\rSending packet {seq+1}/{PACKETS_PER_TEST}...", end='', flush=True)

    print(" Done.")

    # Wait for ACK from receiver
    print("Waiting for ACK from receiver...", end='', flush=True)
    ser.timeout = 5.0
    ack = ser.read(3)
    if ack == b'ACK':
        print(" Received ACK!")
    else:
        print(f" No ACK received (got: {ack})")

def main():
    try:
        with serial.Serial(PORT, BAUDRATE, timeout=1) as ser:
            time.sleep(2)
            print("Starting buffer limit sweep...\n")

            for mtu in MTU_SIZES:
                send_test_batch(ser, mtu)
                time.sleep(3) # Cool down RF module between tests

            print("\nSweep complete.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()