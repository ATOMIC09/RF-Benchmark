import serial
import time
import struct

# --- Configuration ---
PORT = 'COM4'  # Change to your TX port
BAUDRATE = 9600
PACKETS_PER_TEST = 100

# Expanded sweep variables - 5ms to 200ms air gaps
MTU_SIZES = [16, 32, 48, 64, 96, 128, 160, 192, 224, 256]
AIR_GAPS = [0.005,0.01, 0.02, 0.03] # Seconds

def send_test_batch(ser, mtu, gap):
    print(f"\n--- Testing MTU: {mtu} bytes | Air Gap: {gap*1000:.1f} ms ---")
    
    # Send SYNC header
    # Format: 'SYNC' + MTU (unsigned short) + GAP (float)
    sync_packet = b'SYNC' + struct.pack('<H f', mtu, gap)
    ser.write(sync_packet)
    time.sleep(1.5) # Give receiver time to parse SYNC and get ready
    
    for seq in range(PACKETS_PER_TEST):
        # Packet: Start Byte (1) + Seq Num (4) + Dummy Payload
        payload_size = mtu - 5
        
        # Pack sequence number and pad with 0xBB
        packet = struct.pack('<B I', 0xAA, seq) + (b'\xBB' * payload_size)
        ser.write(packet)
        
        # Real-time console update on transmitter
        print(f"\rSending packet {seq+1}/{PACKETS_PER_TEST}...", end='', flush=True)
        time.sleep(gap)
        
    print(" Done.")

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