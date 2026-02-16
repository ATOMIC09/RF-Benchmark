import serial
import time
import struct
import sys
import json
import os

# --- Configuration ---
PORT = 'COM5'  # Change to your RX port
BAUDRATE = 9600
PACKETS_PER_TEST = 100
OUTPUT_FILE = 'rf433_results.json'

def save_results(data_by_mtu):
    """Saves test results to JSON file."""
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(data_by_mtu, f, indent=2)
    print(f"   [Saved to {OUTPUT_FILE}]")

def main():
    try:
        # Initialize data storage
        data_by_mtu = {}  # Dictionary: {mtu_size: [list of test results]}

        with serial.Serial(PORT, BAUDRATE, timeout=5.0) as ser:  # 5s timeout for 3s cooldown
            print(f"Listening on {PORT} at {BAUDRATE} bps... (Waiting for SYNC)\n")

            # Clear buffer once at startup
            ser.reset_input_buffer()

            while True:
                # Wait for SYNC - use read_until for reliable detection
                try:
                    ser.read_until(b'SYNC', size=1000)  # Add size limit
                except:
                    print("   [WARNING] SYNC timeout - waiting for next transmission...")
                    time.sleep(0.5)
                    continue

                sync_data = ser.read(6)
                if len(sync_data) < 6:
                    continue
                    
                current_mtu, current_gap = struct.unpack('<H f', sync_data)
                gap_ms = int(current_gap * 1000)
                
                packets_received = 0
                bytes_received = 0
                start_time = time.time()
                last_packet_time = time.time()

                # 2. Process incoming packets with shorter timeout
                ser.timeout = 0.1  # Short timeout for packet reading
                packet_buffer = b''
                max_buffer_size = current_mtu * 150  # Limit buffer to 150 packets worth

                while True:
                    # Check for batch timeout
                    if time.time() - last_packet_time > 1.5 and packets_received > 0:
                        break # Batch ended via timeout

                    # Read available data
                    if ser.in_waiting > 0:
                        chunk = ser.read(ser.in_waiting)
                        packet_buffer += chunk

                        # Prevent infinite buffer growth
                        if len(packet_buffer) > max_buffer_size:
                            # Keep only the last max_buffer_size bytes
                            packet_buffer = packet_buffer[-max_buffer_size:]

                    # Process complete packets from buffer
                    while len(packet_buffer) >= current_mtu:
                        # Look for start byte
                        if packet_buffer[0] == 0xAA:
                            # Extract packet
                            packet = packet_buffer[:current_mtu]
                            packet_buffer = packet_buffer[current_mtu:]

                            packets_received += 1
                            bytes_received += current_mtu
                            last_packet_time = time.time()

                            sys.stdout.write(f"\r-> Receiving [{current_mtu}B@{gap_ms}ms]: {packets_received}/{PACKETS_PER_TEST}")
                            sys.stdout.flush()

                            if packets_received == PACKETS_PER_TEST:
                                break
                        else:
                            # Misaligned - skip one byte and try again
                            packet_buffer = packet_buffer[1:]

                    if packets_received == PACKETS_PER_TEST:
                        break

                    time.sleep(0.001)  # Small delay to prevent busy-waiting

                # Restore timeout for SYNC detection
                ser.timeout = 5.0
                
                # 3. Batch complete: Calculate metrics
                elapsed = last_packet_time - start_time
                rf_throughput = bytes_received / elapsed if elapsed > 0 else 0
                loss_percent = ((PACKETS_PER_TEST - packets_received) / PACKETS_PER_TEST) * 100

                # Calculate expected throughput based on air gap
                expected_time = packets_received * current_gap
                expected_throughput = bytes_received / expected_time if expected_time > 0 else 0

                # Clear any remaining packet data before next test
                ser.reset_input_buffer()

                print(f"\n   [RESULT] Loss: {loss_percent:.1f}% | RF Speed: {rf_throughput:.2f} B/s | Expected: {expected_throughput:.2f} B/s")

                # 4. Save results to dictionary and file
                mtu_key = str(current_mtu)  # JSON keys must be strings
                if mtu_key not in data_by_mtu:
                    data_by_mtu[mtu_key] = []

                data_by_mtu[mtu_key].append({
                    'gap_ms': gap_ms,
                    'rf_throughput': rf_throughput,
                    'expected_throughput': expected_throughput,
                    'loss': loss_percent,
                    'packets_received': packets_received,
                    'packets_expected': PACKETS_PER_TEST
                })

                # Save to JSON file after each test
                save_results(data_by_mtu)
                print()

    except KeyboardInterrupt:
        print("\nTest stopped by user.")
        if data_by_mtu:
            save_results(data_by_mtu)
            print(f"\nFinal results saved to {OUTPUT_FILE}")
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == '__main__':
    main()