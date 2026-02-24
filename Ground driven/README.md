# Ground-Driven Transfer

This folder contains a minimal, ground-driven workflow that keeps the original sender-driven code intact.
The ground station decides when to request a file, and the satellite only downlinks after a request.

## Files

- `ground_request_receive.py`
  - Ground side.
  - Sends CAPTURE (optional), receives FILE_INFO, then sends REQUEST.
  - Receives the downlinked file on the same UART port.

- `satellite_serve_file.py`
  - Satellite side.
  - Listens for CAPTURE and REQUEST on one UART port.
  - On CAPTURE, replies with FILE_INFO for a prepared file.
  - On REQUEST, sends the file using rf433lib sender-driven transfer.

## Protocol Flow

1) Ground -> Satellite: `CAPTURE`
   - Ground asks the satellite to capture/prepare a file.
  - Satellite replies with `FILE_INFO` containing the filename, size, and sha1.

2) Ground -> Satellite: `REQUEST { filename }`
   - Ground requests the file that was reported in FILE_INFO.
  - Satellite replies with `REQUEST_ACK { ok: true }` if the file exists.

3) Satellite -> Ground: `SYNC` + data frames
   - Satellite downlinks data using the existing rf433lib sender-driven protocol.
   - Ground receives and reconstructs the file.

A small delay is used on the satellite before downlink so the ground can switch from
control messages to receive mode on the same UART port.

## Requirements

- `Python 3.10+` recommended
- `pyserial` installed (comes from `rf433lib` requirements)
- One UART link (same port on each side)

## Usage

### 1) Start the satellite side

From the repo root:

```
python satellite_serve_file.py --port COM5 --dir . --start-delay 1.0
```

Notes:
- `--dir` is the folder to serve files from.
- `--start-delay` gives the ground time to switch to receive mode.
- You can use `--capture-file` to force a specific file for `CAPTURE`.

### 2) Start the ground side

From the repo root:

```
python ground_request_receive.py --port COM4 --capture
```

Notes:
- `--capture` triggers `CAPTURE` then `REQUEST` based on `FILE_INFO`.
- If you already know the filename, skip `--capture` and pass the file name:
  ```
  python ground_request_receive.py myfile.bin --port COM4
  ```

## How It Works (Details)

- `CAPTURE` phase:
  - Ground sends `{ type: "CAPTURE" }`.
  - Satellite selects a file (either `--capture-file` or newest in `--dir`).
  - Satellite replies with:
    `{ type: "FILE_INFO", ok: true, filename, size, sha1, mtu, chunks }`

- `REQUEST` phase:
  - Ground sends `{ type: "REQUEST", filename }`.
  - Satellite replies with:
    `{ type: "REQUEST_ACK", ok: true }` or `{ ok: false, reason: "not_found" }`.

- Downlink phase:
  - Satellite uses `RF433Transmitter.send_bytes(...)`.
  - Ground uses `RF433Receiver.receive_once(...)`.
  - File is saved to `./received_files` by default.
  - `SHA1` is checked if provided in metadata.

## Troubleshooting

- No transfer received (timeout)
  - Increase `--start-delay` on the satellite (try `2.0` seconds).
  - Make sure the same UART link is wired and the ports are correct.

- Request rejected: `not_found`
  - The requested filename does not exist in `--dir` on the satellite.
  - Use `--capture-file` or check the directory contents.

## Notes

- This is intentionally minimal and uses the existing sender-driven protocol for
  the actual data transfer, with a small ground-driven control layer on top.
