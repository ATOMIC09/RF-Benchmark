import json
import time
import zlib
import os
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

PORT        = "COM5"
BAUDRATE    = 9600
FRAME_SIZE  = 1500
OUTPUT_FILE = "output.jpg"

# ── Main ──────────────────────────────────────────────────────────────────────

try:
    os.remove(OUTPUT_FILE)
except FileNotFoundError:
    pass

# Pre-create the output file so seek-writes work
open(OUTPUT_FILE, 'w').close()

ser = Serial(PORT, baudrate=BAUDRATE, timeout=5)

last_frame_receive = 0
done = False

print(f"Listening on {PORT} at {BAUDRATE} baud...")

while True:
    read = ser.read(FRAME_SIZE + 13)  # 13 = 9 header + 4 CRC
    if read:
        done = False
        metaData = decodeMetaData(read[0:9])
        try:
            decoded = decodeTx(read)
            if not decoded["pass"]:
                print(f"CRC error on packet {metaData['packet_num']} - requesting retransmit")
                reply = encodeTx(f"ASK{last_frame_receive}", 0, 1, 'text')
                ser.write(reply)
            else:
                last_frame_receive = decoded["packet_num"]
                pct = (decoded["packet_num"] / max(decoded["total_packet_count"] - 1, 1)) * 100
                print(f"\033[32mReceived {pct:.2f}%  "
                      f"packet {last_frame_receive}/{decoded['total_packet_count'] - 1}\033[39m")

                if decoded["packet_type"] == 'image':
                    with open(OUTPUT_FILE, 'rb+') as f:
                        offset = decoded["packet_num"] * FRAME_SIZE
                        f.seek(offset, 0)
                        f.write(decoded["packet_content"])
                        print(f"\033[33m  Wrote {len(decoded['packet_content'])} bytes at offset {offset}\033[39m")

                reply = encodeTx(f"ACK{last_frame_receive}", 0, 1, 'text')
                ser.write(reply)

                if (decoded["packet_num"] + 1) == decoded["total_packet_count"]:
                    done = True
                    print("\nTransfer complete!")

        except Exception as e:
            print(f"Decode error: {e}")

    else:
        if not done:
            ask_packet = max(last_frame_receive - 1, 0)
            print(f"Timeout - requesting packet {ask_packet}")
            reply = encodeTx(f"ASK{ask_packet}", 0, 1, 'text')
            ser.write(reply)
