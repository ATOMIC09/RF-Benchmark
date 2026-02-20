import math
import time
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
    packet_size = int.from_bytes(byteInput[7:9], byteorder="big")
    return {"packet_size": packet_size}


def main() -> None:
    time.sleep(2)
    ser = Serial("COM4", baudrate=9600, timeout=5)

    with open("image.jpg", "rb") as imageFile:
        time.sleep(1)
        content = imageFile.read()
        total_size = len(content)
        print(total_size)

        frame_size = 1500
        noOfSend = math.ceil(total_size / frame_size)
        i = 0
        lastTime = 0.0
        startTime = time.time()

        while i < noOfSend:
            timeDiff = time.time() - lastTime
            lastTime = time.time()

            index_start = frame_size * i
            index_end = (frame_size * i) + frame_size
            transmit = encodeTx(content[index_start:index_end], i, noOfSend, "image")
            ser.write(transmit)
            ser.flush()

            print(
                f"Send Packet {i} from {noOfSend - 1} = {index_end / total_size * 100:.3f}% "
                f"time diff : {timeDiff:.4f}s total of {len(transmit)} bytes"
            )

            if (i >= 0 and i % num_packet_before_check == 0) or i == noOfSend - 1:
                print("waiting for checking reply")
                total_read: bytes = b""
                metaData: dict | None = None
                ser.flush()

                while True:
                    read = ser.read()
                    if read:
                        total_read += read

                        if len(total_read) == 9:
                            metaData = decodeMetaData(total_read)
                        if (
                            len(total_read) > 9
                            and metaData is not None
                            and len(total_read) >= metaData["packet_size"] + 13
                        ):
                            decoded = decodeTx(total_read)
                            print(f"return message {decoded['packet_content']}")
                            ask_state = "ACK"

                            if decoded["pass"]:
                                text = decoded["packet_content"].decode(errors="ignore")
                                if "ASK" in text:
                                    ack_package = text.split("ASK")[1]
                                    ask_state = "ASK"
                                elif "ACK" in text:
                                    ack_package = text.split("ACK")[1]
                                    ask_state = "ACK"
                                else:
                                    ack_package = ""

                                if ask_state == "ACK" and ack_package.isdigit():
                                    if int(ack_package) == i:
                                        print("Check OK ✅")
                                        break
                                    else:
                                        print("Reverting...")
                                        i = int(ack_package) - 1
                                        break
                                elif ask_state == "ASK" and ack_package.isdigit():
                                    print("Ask Reverting...")
                                    i = int(ack_package) - 1
                                    break
                            else:
                                total_read = b""
                    else:
                        print("No ACK received, retrying...")
                        i = max(-1, i - 1)
                        break

            i += 1

        print(f"Total Time {time.time() - startTime:.2f}s")

    ser.close()


if __name__ == "__main__":
    main()
