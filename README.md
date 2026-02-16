# RF433 Throughput Testing Suite

A comprehensive testing framework for measuring RF433 wireless module performance across different packet sizes (MTU) and transmission intervals (air gaps).

## System Architecture

### Components

1. **Transmitter.py** - Sends test packets over RF433 transmitter module
2. **Receiver.py** - Receives packets and measures performance metrics
3. **Plotter.py** - Visualizes individual MTU test results (separate window per MTU)
4. **Overview.py** - Visualizes overall performance across all MTU sizes

### Communication Protocol

```
[SYNC Packet]
┌─────┬─────────┬──────────┐
│SYNC │ MTU(2B) │ GAP(4B)  │
└─────┴─────────┴──────────┘
  4B      u16      float32

[Data Packet]
┌──────┬────────┬─────────────────────┐
│ 0xAA │ SEQ(4B)│ PAYLOAD (0xBB...)   │
└──────┴────────┴─────────────────────┘
  1B      u32      (MTU-5) bytes of 0xBB
```

**Payload Details**:
- Start byte: `0xAA` (packet marker)
- Sequence number: 4-byte unsigned integer (0-99)
- Payload: Filled with `0xBB` bytes for padding
- Total packet size equals configured MTU

**Payload Generation** (Transmitter.py:28):
```python
payload_size = mtu - 5
packet = struct.pack('<B I', 0xAA, seq) + (b'\xBB' * payload_size)
```

Example for MTU=16:
```
[0xAA][0x00 0x00 0x00 0x00][0xBB 0xBB 0xBB 0xBB 0xBB 0xBB 0xBB 0xBB 0xBB 0xBB 0xBB]
 1B          4B (seq=0)                      11 bytes of 0xBB padding

Total: 1 + 4 + 11 = 16 bytes
```

### Test Parameters

- **MTU Sizes**: 16, 32, 48, 64, 96, 128, 160, 192, 224, 256 bytes
- **Air Gaps**: 5ms, 10ms, 20ms, 30ms
- **Packets per test**: 100
- **UART Baudrate**: 9600 bps

## Problems Found & Solutions

### Problem 1: Missing SYNC Packets Between Tests

**Symptom**: Receiver would catch the first test but miss subsequent tests.

**Root Cause**: Timing mismatch between transmitter's 3-second cooldown and receiver's 2-second timeout. Buffer was cleared before next SYNC arrived.

**Solution** (Receiver.py:25, 77):
```python
# Increased timeout to accommodate cooldown
ser.timeout = 5.0  # 5s timeout for 3s cooldown

# Clear buffer AFTER processing, not before waiting for SYNC
ser.reset_input_buffer()  # After batch completes
```

### Problem 2: Receiver Freezing on Large MTU Packets (160+ bytes)

**Symptom**: System would hang indefinitely when testing MTU ≥160 bytes.

**Root Cause**: `ser.read(current_mtu - 1)` would block for up to 5 seconds when reading large packets. If the data stream got misaligned, it never recovered.

**Solution** (Receiver.py:52-96):
- Implemented buffered reading with dynamic timeout switching
- 0.1s timeout during packet reception (non-blocking)
- 5.0s timeout for SYNC detection (allows cooldown wait)
- Packet boundary detection with automatic misalignment recovery

```python
# Read all available data into buffer
chunk = ser.read(ser.in_waiting)
packet_buffer += chunk

# Process complete packets
if packet_buffer[0] == 0xAA:
    # Extract packet
else:
    # Skip 1 byte and re-sync
    packet_buffer = packet_buffer[1:]
```

### Problem 3: Infinite Buffer Growth Leading to Hang

**Symptom**: Receiver would hang after running tests for extended periods.

**Root Cause**: `packet_buffer` grew indefinitely when misaligned data kept arriving without being processed.

**Solution** (Receiver.py:55, 67-70):
```python
max_buffer_size = current_mtu * 150  # Limit to 150 packets

if len(packet_buffer) > max_buffer_size:
    packet_buffer = packet_buffer[-max_buffer_size:]
```

### Problem 4: Throughput Doesn't Change with Air Gap

**Symptom**: Measured throughput remained constant (~855 B/s for 128B) regardless of air gap setting.

**Root Cause**: RF433 modules have internal UART buffers that decouple transmission timing from reception timing. The modules receive data at 9600 baud, buffer it, transmit over RF, and output at maximum speed on the receiver side.

**Key Finding**: The air gap delays happen **before** the RF module, so they don't affect RF transmission bottleneck speed.

**Solution** (Receiver.py:101-108):
Added dual metrics to reveal the true bottleneck:

```python
# Actual measured throughput (RF module speed)
rf_throughput = bytes_received / elapsed

# Theoretical throughput accounting for air gaps
expected_time = packets_received * current_gap
expected_throughput = bytes_received / expected_time
```

**Example Results**:
```
MTU: 128 bytes, Air Gap: 100ms
- Expected Throughput: 1280 B/s  (128B / 0.1s)
- RF Speed (actual):   855 B/s   ← RF module bottleneck!
```

This reveals that the **RF433 module maximum throughput is ~860-880 B/s**, not the air gap timing.

## Results Interpretation

### JSON Data Structure

```json
{
  "16": [
    {
      "gap_ms": 4,
      "rf_throughput": 495.27,        // Actual measured speed
      "expected_throughput": 3200.00, // Theoretical with air gaps
      "loss": 0.0,
      "packets_received": 100,
      "packets_expected": 100
    }
  ]
}
```

### Chart Visualization

Each MTU size gets a separate window showing:

- **Blue solid line**: RF Speed (actual measured throughput)
- **Cyan dashed line**: Expected throughput (theoretical with air gaps)
- **Red line**: Packet Loss percentage
- **Data labels**: Exact values at each test point

### Key Findings

1. **RF Module Bottleneck**: ~860-880 B/s maximum throughput
2. **Optimal MTU**: 128 bytes achieves best speed (855 B/s)
3. **Larger MTU Impact**:
   - 160B+: 1% packet loss
   - 192B+: 2% packet loss
   - Speed plateaus at ~880 B/s
4. **Air Gap Effect**: Minimal impact on RF speed due to internal buffering

## Usage

### 1. Run Receiver (Start First)
```bash
python Receiver.py
# Wait for "Listening on COM5..." message
```

### 2. Run Transmitter
```bash
python Transmitter.py
# Executes automated test sweep
```

### 3. Visualize Results

**Individual MTU Charts** (separate window per MTU):
```bash
python Plotter.py
```

**Overview Charts** (all MTUs in one view):
```bash
python Overview.py
# Creates 2 windows:
# - Line charts: Throughput & Loss vs MTU Size
# - Heatmaps: Performance matrix across all parameters
```

## Configuration

### Transmitter.py
```python
PORT = 'COM4'          # TX module port
BAUDRATE = 9600
MTU_SIZES = [16, 32, 48, 64, 96, 128, 160, 192, 224, 256]
AIR_GAPS = [0.005, 0.01, 0.02, 0.03]  # seconds
```

### Receiver.py
```python
PORT = 'COM5'          # RX module port
BAUDRATE = 9600
OUTPUT_FILE = 'rf433_results.json'
```

### Plotter.py
```python
INPUT_FILE = 'rf433_results.json'
plt.rcParams['font.family'] = 'Niramit'
```

### Overview.py
```python
INPUT_FILE = 'rf433_results.json'
plt.rcParams['font.family'] = 'Niramit'
```

**Overview Charts Include**:
1. **Line Charts**: Shows how throughput and packet loss change with MTU size for each air gap
2. **Heatmaps**: Color-coded matrix showing performance across all MTU/air gap combinations
   - Green heatmap: Throughput (darker = higher)
   - Red heatmap: Packet loss (darker = more loss)

## Technical Details

### Buffer Management
- **Max buffer size**: 150 packets worth of data
- **Timeout switching**: 5s for SYNC, 0.1s for packets
- **Misalignment recovery**: Automatic byte-by-byte re-sync

### Timing Methodology
- **Start time**: First packet received
- **End time**: Last packet received
- **Throughput**: Total bytes / elapsed time
- **Expected throughput**: Total bytes / (packets × air_gap)

### Packet Loss Detection
- **Timeout**: 1.5 seconds after last packet
- **Loss calculation**: (Expected - Received) / Expected × 100%

## Dependencies

```bash
pip install pyserial matplotlib
```

Requires **Niramit font** installed for chart rendering.

## Hardware Setup

```
[PC] ←→ [UART] ←→ [RF433 TX] ~~~RF~~~ [RF433 RX] ←→ [UART] ←→ [PC]
         COM4                                                  COM5
```

- TX RF433 module on COM4 (9600 baud)
- RX RF433 module on COM5 (9600 baud)
- Ensure proper antenna and power supply for RF modules

## Conclusion

This testing suite successfully characterizes RF433 module performance, revealing:

**Key Findings**:
1. RF module internal buffering decouples air gap timing from throughput
2. Maximum achievable throughput is ~860-880 B/s
3. Optimal MTU is 128 bytes (0% loss, 855 B/s)
4. Larger packets improve throughput slightly but increase packet loss

**Problems Solved**:
1. SYNC packet timing mismatches between transmitter and receiver
2. Receiver freezing on large packets due to blocking reads and misalignment
3. Infinite buffer growth causing memory exhaustion
4. Misleading throughput measurements not accounting for RF buffering

The dual-metric approach (RF Speed vs Expected) clearly shows the difference between theoretical and actual performance, identifying the RF module as the primary bottleneck rather than transmission timing.

**Payload Structure**:
- Each packet contains: `0xAA` start byte + 4-byte sequence number + `0xBB` padding
- Simple pattern allows easy validation and debugging
- No actual data transmitted - pure throughput testing
