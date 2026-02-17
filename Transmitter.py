import serial
import time
import struct
import random
import zlib

# --- Configuration ---
PORT = 'COM4'  # Change to your TX port
BAUDRATE = 9600
PACKETS_PER_TEST = 100

# Expanded sweep variables - 5ms to 200ms air gaps
MTU_SIZES = [16, 32, 64, 128, 256, 512, 1024, 1492, 1500]
AIR_GAPS = [0.005,0.01, 0.02, 0.03] # Seconds

def send_test_batch(ser, mtu, gap):
    print(f"\n--- Testing MTU: {mtu} bytes | Air Gap: {gap*1000:.1f} ms ---")

    # Generate random seed for this batch
    random_seed = random.randint(0, 2**32 - 1)

    # Send SYNC header
    # Format: 'SYNC' + MTU (unsigned short) + GAP (float) + SEED (unsigned int)
    sync_packet = b'SYNC' + struct.pack('<H f I', mtu, gap, random_seed)
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
        ser.flush()  # Wait until all bytes are actually transmitted over serial

        # Real-time console update on transmitter
        print(f"\rSending packet {seq+1}/{PACKETS_PER_TEST}...", end='', flush=True)
        time.sleep(gap)

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
            print("Starting automated throughput sweep...\n")
            
            for mtu in MTU_SIZES:
                for gap in AIR_GAPS:
                    send_test_batch(ser, mtu, gap)
                    time.sleep(3) # Cool down the RF module's internal buffer
                    
            print("\nSweep complete.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()