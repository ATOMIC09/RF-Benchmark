import time
import os
import json
import zlib
from typing import Literal
from serial import Serial


num_packet_before_check = 1


def encodeTx(byteInput, packetNo: int, totalPacket: int,
             packetType: Literal["image", "text", "json"]) -> bytes:
    typeLookup = {
        "image": 0,
        "text": 1,
        "json": 2,
    }
    if isinstance(byteInput, str):
        byteInput = byteInput.encode()
        packetType = "text"
    if isinstance(byteInput, dict):
        byteInput = json.dumps(byteInput).encode()
        packetType = "json"

    packet_num = packetNo.to_bytes(3, byteorder="big")
    packet_total = totalPacket.to_bytes(3, byteorder="big")
    packet_type = typeLookup[packetType].to_bytes(1, byteorder="big")
    packet_length = len(byteInput).to_bytes(2, byteorder="big")

    output = packet_num + packet_type + packet_total + packet_length + byteInput
    output += zlib.crc32(output).to_bytes(4, "big")
    return output


def decodeTx(byteInput: bytes) -> dict:
    packetTypeLookup = {
        0: "image",
        1: "text",
        2: "json",
    }
    packet_num = int.from_bytes(byteInput[0:3], byteorder="big")
    packet_type = int.from_bytes(byteInput[3:4], byteorder="big")
    total_packet_count = int.from_bytes(byteInput[4:7], byteorder="big")
    packet_size = int.from_bytes(byteInput[7:9], byteorder="big")
    packet_content = byteInput[9:-4]
    checkFCS = zlib.crc32(byteInput[:-4]).to_bytes(4, "big")
    fcs = byteInput[-4:]

    return {
        "packet_num": packet_num,
        "packet_type": packetTypeLookup.get(packet_type, "err"),
        "total_packet_count": total_packet_count,
        "packet_size": packet_size,
        "packet_content": packet_content,
        "pass": fcs == checkFCS,
    }


def decodeMetaData(byteInput: bytes) -> dict:
    packetTypeLookup = {
        0: "image",
        1: "text",
        2: "json",
    }

    packet_num = int.from_bytes(byteInput[0:3], byteorder="big")
    packet_type = int.from_bytes(byteInput[3:4], byteorder="big")
    total_packet_count = int.from_bytes(byteInput[4:7], byteorder="big")
    packet_size = int.from_bytes(byteInput[7:9], byteorder="big")

    if packet_type in packetTypeLookup:
        return {
            "packet_num": packet_num,
            "packet_type": packetTypeLookup[packet_type],
            "total_packet_count": total_packet_count,
            "packet_size": packet_size,
        }

    return {
        "packet_num": packet_num,
        "packet_type": "err",
        "total_packet_count": total_packet_count,
        "packet_size": packet_size,
    }


def main() -> None:
    ser = Serial("COM5", timeout=5, baudrate=9600)
    output_file = "output.jpg"

    try:
        ser.close()
    except Exception:
        pass

    try:
        os.remove(output_file)
    except Exception:
        pass

    time.sleep(1)
    ser.open()

    total_read: bytes = b""
    last_frame_receive = 0
    done = False
    frame_size = 1500

    with open(output_file, "wb"):
        pass

    while True:
        read = ser.read(frame_size + 13)
        if read:
            done = False
            try:
                decoded = decodeTx(read)
                if not decoded["pass"]:
                    print("error, replying")
                    reply_message = encodeTx(f"ASK{last_frame_receive}", 0, 1, "text")
                    ser.write(reply_message)
                    ser.flush()
                    total_read = b""
                else:
                    last_frame_receive = decoded["packet_num"]
                    print(
                        f"received {(decoded['packet_num']) / (decoded['total_packet_count'] - 1) * 100:.2f}% "
                        f"packet no {last_frame_receive} from {decoded['total_packet_count'] - 1}"
                    )
                    if decoded["packet_type"] == "image":
                        with open(output_file, "rb+") as file:
                            file.seek(decoded["packet_num"] * frame_size, 0)
                            print(
                                f"File wrote at {decoded['packet_num'] * frame_size} "
                                f"for {len(decoded['packet_content'])} bytes"
                            )
                            file.write(decoded["packet_content"])

                        reply_message = encodeTx(f"ACK{last_frame_receive}", 0, 1, "text")
                        ser.write(reply_message)
                        ser.flush()

                    total_read = b""
                    if (decoded["packet_num"] + 1) == decoded["total_packet_count"]:
                        done = True
                        reply_message = encodeTx(f"ACK{last_frame_receive}", 0, 1, "text")
                        ser.write(reply_message)
                        ser.flush()
            except Exception as e:
                print(e)
        else:
            if not done:
                ask_for = max(last_frame_receive - 1, 0)
                print(f"trying to ask for {ask_for} packet")
                reply_message = encodeTx(f"ASK{ask_for}", 0, 1, "text")
                ser.write(reply_message)
                ser.flush()
            total_read = b""


if __name__ == "__main__":
    main()
