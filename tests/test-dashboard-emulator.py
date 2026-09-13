#!/usr/bin/env python3
import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = ROOT.parent / 'bin' / 'frozrctl'
HELLO = b'chs_2inch.dev1_rom1.89'
PACKET = 250
RAW = 249
FRAME_BYTES = 480 * 480 * 4


def read_exact(fd, size, timeout=12.0):
    data = bytearray()
    deadline = time.monotonic() + timeout
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f'wanted {size}, got {len(data)} bytes')
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        chunk = os.read(fd, min(65536, size - len(data)))
        if not chunk:
            raise EOFError(f'wanted {size}, got EOF at {len(data)} bytes')
        data.extend(chunk)
    return bytes(data)


def assert_packet(packet, command, declared=None, flag=0, payload=None):
    assert len(packet) == PACKET
    assert packet[0] == command, (hex(packet[0]), hex(command))
    assert packet[1:3] == b'\xef\x69'
    length = int.from_bytes(packet[3:7], 'big')
    if declared is not None:
        assert length == declared, (length, declared)
    assert packet[7] == flag, (packet[7], flag)
    if payload is not None:
        assert packet[10:10 + len(payload)] == payload
    return length


def raw_wire_size(size):
    return ((size + RAW - 1) // RAW) * PACKET


def unpack_raw(wire, size):
    out = bytearray()
    remaining = size
    for offset in range(0, len(wire), PACKET):
        take = min(RAW, remaining)
        out.extend(wire[offset:offset + take])
        remaining -= take
        if remaining <= 0:
            break
    assert len(out) == size, (len(out), size)
    return bytes(out)


def validate_delta(payload):
    assert payload.endswith(b'\xef\x69'), payload[-8:]
    data = payload[:-2]
    pos = 0
    runs = 0
    pixels = 0
    last_end = 0
    while pos < len(data):
        assert pos + 3 <= len(data)
        first = data[pos]
        single = bool(first & 0x80)
        index = ((first & 0x7f) << 16) | (data[pos + 1] << 8) | data[pos + 2]
        pos += 3
        assert 0 <= index < 480 * 480
        assert index >= last_end
        if single:
            assert pos + 4 <= len(data)
            pos += 4
            run = 1
        else:
            assert pos + 2 <= len(data)
            run = int.from_bytes(data[pos:pos + 2], 'big')
            pos += 2
            assert 1 < run <= 65000
            assert index + run <= 480 * 480
            assert pos + run * 4 <= len(data)
            pos += run * 4
        last_end = index + run
        pixels += run
        runs += 1
    assert pos == len(data)
    assert runs > 0
    assert pixels > 0
    return runs, pixels


def main():
    master, slave = pty.openpty()
    slave_path = os.ttyname(slave)
    home = ROOT / 'home-dashboard-emulator'
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['HOME'] = str(home)

    proc = subprocess.Popen(
        [
            'gjs', str(CLI), '--device', slave_path,
            'dashboard', '--frames', '2', '--interval', '250', '--quiet',
            '--rotation', '270', '--mirror-horizontal', 'on', '--mirror-vertical', 'on',
        ],
        cwd=ROOT.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    errors = []
    delta_summary = None
    try:
        packet = read_exact(master, PACKET)
        assert_packet(packet, 0x01, 1, 0, b'\xc5\xd3')
        os.write(master, HELLO)

        assert_packet(read_exact(master, PACKET), 0x79, 1)
        assert_packet(read_exact(master, PACKET), 0x96, 1)

        assert_packet(read_exact(master, PACKET), 0xcf, 1)
        os.write(master, b'ok|renderCnt:0')

        start = read_exact(master, PACKET)
        assert start == bytes([0x2c]) * PACKET

        brightness = read_exact(master, PACKET)
        assert_packet(brightness, 0x7b, 1)
        assert 0 <= brightness[10] <= 255

        full_command = read_exact(master, PACKET)
        assert_packet(full_command, 0xc8, FRAME_BYTES)
        full_wire = read_exact(master, raw_wire_size(FRAME_BYTES), timeout=20.0)
        full = unpack_raw(full_wire, FRAME_BYTES)
        assert len(full) == FRAME_BYTES
        os.write(master, b'full_frame_ok')

        delta_command = read_exact(master, PACKET, timeout=12.0)
        delta_len = assert_packet(delta_command, 0xcc)
        assert delta_len > 2
        metadata = delta_command[10:18]
        assert int.from_bytes(metadata[:4], 'big') == 1
        assert metadata[4:] == b'\x00\x00\x00\x00'
        delta_wire = read_exact(master, raw_wire_size(delta_len), timeout=12.0)
        delta_payload = unpack_raw(delta_wire, delta_len)
        runs, pixels = validate_delta(delta_payload)
        delta_summary = (delta_len, len(delta_wire), runs, pixels)
    except Exception as exc:
        errors.append(str(exc))
    finally:
        try:
            stdout, stderr = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            errors.append('CLI did not terminate after --frames 2')
        os.close(master)
        os.close(slave)

    print('exit:', proc.returncode)
    print('stdout:\n' + stdout)
    print('stderr:\n' + stderr)
    if delta_summary:
        print('delta:', {
            'payload_bytes': delta_summary[0],
            'wire_bytes': delta_summary[1],
            'runs': delta_summary[2],
            'changed_pixels': delta_summary[3],
        })
    print('errors:', errors)

    if proc.returncode != 0 or errors:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
