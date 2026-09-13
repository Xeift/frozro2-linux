#!/usr/bin/env python3
import os
import pty
import select
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = ROOT.parent / 'bin' / 'frozrctl'
PACKET = 250
RAW = 249
FRAME_RAW = 480 * 480 * 4
FRAME_WIRE = ((FRAME_RAW + RAW - 1) // RAW) * PACKET
HELLO = b'chs_2inch.dev1_rom1.89'


def read_exact(fd, size, timeout=20.0):
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


def assert_packet(packet, command, declared=None, flag=0):
    assert len(packet) == PACKET
    assert packet[0] == command, (hex(packet[0]), hex(command))
    assert packet[1:3] == b'\xef\x69'
    if declared is not None:
        assert int.from_bytes(packet[3:7], 'big') == declared
    assert packet[7] == flag


def make_quadrant_ppm(path):
    w = h = 64
    pixels = bytearray()
    for y in range(h):
        for x in range(w):
            if y < h // 2 and x < w // 2:
                rgb = (255, 0, 0)
            elif y < h // 2:
                rgb = (0, 255, 0)
            elif x < w // 2:
                rgb = (0, 0, 255)
            else:
                rgb = (255, 255, 0)
            pixels.extend(rgb)
    path.write_bytes(f'P6\n{w} {h}\n255\n'.encode() + pixels)


def unpack_wire(wire):
    out = bytearray()
    remaining = FRAME_RAW
    for offset in range(0, len(wire), PACKET):
        take = min(RAW, remaining)
        out.extend(wire[offset:offset + take])
        remaining -= take
        if remaining <= 0:
            break
    assert len(out) == FRAME_RAW
    return bytes(out)


def dominant(rgb):
    r, g, b = rgb
    if r > 170 and g > 170 and b < 120:
        return 'yellow'
    if r > g + 60 and r > b + 60:
        return 'red'
    if g > r + 60 and g > b + 60:
        return 'green'
    if b > r + 60 and b > g + 60:
        return 'blue'
    return f'other({r},{g},{b})'


def main():
    with tempfile.TemporaryDirectory(prefix='frozr-image-transform-') as td:
        temp = Path(td)
        source = temp / 'quadrants.ppm'
        home = temp / 'home'
        home.mkdir()
        make_quadrant_ppm(source)

        master, slave = pty.openpty()
        slave_path = os.ttyname(slave)
        env = os.environ.copy()
        env['HOME'] = str(home)
        proc = subprocess.Popen([
            'gjs', str(CLI), '--device', slave_path,
            'image', str(source), '--brightness', '35',
            '--rotation', '90',
            '--mirror-horizontal', 'on',
            '--mirror-vertical', 'on',
        ], cwd=ROOT.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        errors = []
        try:
            packet = read_exact(master, PACKET)
            assert_packet(packet, 0x01, 1)
            os.write(master, HELLO)
            assert_packet(read_exact(master, PACKET), 0x79, 1)
            assert_packet(read_exact(master, PACKET), 0x96, 1)
            assert_packet(read_exact(master, PACKET), 0x7b, 1)
            assert_packet(read_exact(master, PACKET), 0x7d, 5)
            assert_packet(read_exact(master, PACKET), 0x86, 1)
            assert read_exact(master, PACKET) == bytes([0x2c]) * PACKET

            display = read_exact(master, PACKET)
            assert display[:8] == bytes.fromhex('c8ef69000e100e10')
            wire = read_exact(master, FRAME_WIRE, timeout=30.0)
            frame = unpack_wire(wire)
            os.write(master, b'image_ok')

            query = read_exact(master, PACKET)
            assert_packet(query, 0xcf, 1)
            os.write(master, b'ok')

            stdout, stderr = proc.communicate(timeout=8)
            if proc.returncode != 0:
                errors.append(f'CLI exit {proc.returncode}: {stderr}')

            def logical_rgb(x, y):
                # Device framebuffer = logical image rotated 90° CCW.
                hw_x = y
                hw_y = 479 - x
                i = (hw_y * 480 + hw_x) * 4
                b, g, r, _a = frame[i:i + 4]
                return (r, g, b)

            expected = {
                'TL': ('green', logical_rgb(80, 80)),
                'TR': ('yellow', logical_rgb(400, 80)),
                'BL': ('red', logical_rgb(80, 400)),
                'BR': ('blue', logical_rgb(400, 400)),
            }
            for name, (want, rgb) in expected.items():
                got = dominant(rgb)
                if got != want:
                    errors.append(f'{name}: expected {want}, got {got} {rgb}')

            print('frame wire bytes:', len(wire))
            print('stdout:\n' + stdout.rstrip())
            print('stderr:\n' + stderr.rstrip())
            print('errors:', errors)
            return 1 if errors else 0
        except Exception as exc:
            proc.kill()
            stdout, stderr = proc.communicate()
            print('FAILED:', repr(exc))
            print('stdout:\n' + stdout)
            print('stderr:\n' + stderr)
            return 1
        finally:
            os.close(master)
            os.close(slave)


if __name__ == '__main__':
    raise SystemExit(main())
