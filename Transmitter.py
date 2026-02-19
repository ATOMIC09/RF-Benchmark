import json
import math
import time
import zlib
from typing import Literal
from serial import Serial

# ── Protocol helpers ──────────────────────────────────────────────────────────

num_packet_before_check = 1

def encodeTx(byteInput: bytes, packetNo: int, totalPacket: int,
             packetType: Literal["image", "text", "json"]) -> bytes:
    typeLookup = {"image": 0, "text": 1, "json": 2}
    if isinstance(byteInput, str):
        byteInput = byteInput.encode()
        packetType = "text"
    if isinstance(byteInput, dict):
        byteInput = json.dumps(byteInput).encode()
        packetType = "json"
    packet_num   = packetNo.to_bytes(3, byteorder='big')
    packet_total = totalPacket.to_bytes(3, byteorder='big')
    packet_type  = typeLookup[packetType].to_bytes(1, byteorder='big')
    packet_len   = len(byteInput).to_bytes(2, byteorder='big')
    output = packet_num + packet_type + packet_total + packet_len + byteInput
    output += zlib.crc32(output).to_bytes(4, "big")
    return output

def decodeTx(byteInput: bytes) -> dict:
    packetTypeLookup = {0: "image", 1: "text", 2: "json"}
    packet_num         = int.from_bytes(byteInput[0:3], byteorder='big')
    packet_type        = int.from_bytes(byteInput[3:4], byteorder='big')
    total_packet_count = int.from_bytes(byteInput[4:7], byteorder='big')
    packet_size        = int.from_bytes(byteInput[7:9], byteorder='big')
    packet_content     = byteInput[9:-4]
    checkFCS           = zlib.crc32(byteInput[:-4]).to_bytes(4, "big")
    fcs                = byteInput[-4:]
    return {
        "packet_num":         packet_num,
        "packet_type":        packetTypeLookup.get(packet_type, "unknown"),
        "total_packet_count": total_packet_count,
        "packet_size":        packet_size,
        "packet_content":     packet_content,
        "pass":               fcs == checkFCS,
    }

def decodeMetaData(byteInput: bytes) -> dict:
    packetTypeLookup = {0: "image", 1: "text", 2: "json"}
    packet_num         = int.from_bytes(byteInput[0:3], byteorder='big')
    packet_type        = int.from_bytes(byteInput[3:4], byteorder='big')
    total_packet_count = int.from_bytes(byteInput[4:7], byteorder='big')
    packet_size        = int.from_bytes(byteInput[7:9], byteorder='big')
    return {
        "packet_num":         packet_num,
        "packet_type":        packetTypeLookup.get(packet_type, "err"),
        "total_packet_count": total_packet_count,
        "packet_size":        packet_size,
    }

# ── Configuration ─────────────────────────────────────────────────────────────

PORT       = "COM4"
BAUDRATE   = 9600
FRAME_SIZE = 1500
IMAGE_FILE = "image.jpg"

# ── Main ──────────────────────────────────────────────────────────────────────

time.sleep(2)
ser = Serial(PORT, baudrate=BAUDRATE, timeout=5)

with open(IMAGE_FILE, 'rb') as f:
    content = f.read()

total_size = len(content)
noOfSend   = math.ceil(total_size / FRAME_SIZE)
print(f"File size: {total_size} bytes  |  Packets: {noOfSend}")

i         = 0
lastTime  = 0
startTime = time.time()

while i < noOfSend:
    timeDiff = time.time() - lastTime
    lastTime = time.time()

    index_start = FRAME_SIZE * i
    index_end   = index_start + FRAME_SIZE
    transmit = encodeTx(content[index_start:index_end], i, noOfSend, 'image')
    ser.write(transmit)
    print(f"Sent packet {i}/{noOfSend - 1}  "
          f"({index_end / total_size * 100:.1f}%)  "
          f"timeDiff={timeDiff:.4f}s  bytes={len(transmit)}")

    if i % num_packet_before_check == 0 or i == noOfSend - 1:
        print("Waiting for ACK/ASK...")
        total_read: bytes = b''
        metaData = None
        ser.flush()

        while True:
            read = ser.read(1)
            if read:
                total_read += read
                if len(total_read) == 9:
                    metaData = decodeMetaData(total_read)
                if metaData and len(total_read) >= 9 + metaData["packet_size"] + 4:
                    decoded = decodeTx(total_read)
                    print(f"  Reply: {decoded['packet_content']}")
                    if decoded["pass"]:
                        content_str = decoded["packet_content"].decode(errors='replace')
                        if "ASK" in content_str:
                            ack_package = content_str.split("ASK")[1]
                            print(f"  ASK received - reverting to packet {int(ack_package)}")
                            i = int(ack_package) - 1
                        elif "ACK" in content_str:
                            ack_package = content_str.split("ACK")[1]
                            if int(ack_package) == i:
                                print("  ACK OK")
                            else:
                                print(f"  ACK mismatch - reverting to packet {int(ack_package)}")
                                i = int(ack_package) - 1
                    else:
                        total_read = b''
                        metaData = None
                        continue
                    break
            else:
                print("  No reply - retrying last packet")
                i = max(-1, i - 1)
                break

    i += 1

print(f"\nDone. Total time: {time.time() - startTime:.2f}s")
ser.close()
