#!/usr/bin/env python3
import math
import os
import pty
import select
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = ROOT.parent / 'bin' / 'frozrctl'
TARGET = '/mnt/SDCARD/video/transform-test.mp4'
PACKET = 250
RAW = 249
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
                rgb = (255, 0, 0)       # TL red
            elif y < h // 2:
                rgb = (0, 255, 0)       # TR green
            elif x < w // 2:
                rgb = (0, 0, 255)       # BL blue
            else:
                rgb = (255, 255, 0)     # BR yellow
            pixels.extend(rgb)
    path.write_bytes(f'P6\n{w} {h}\n255\n'.encode() + pixels)


def unpack_wire(wire, size):
    out = bytearray()
    remaining = size
    for offset in range(0, len(wire), PACKET):
        take = min(RAW, remaining)
        out.extend(wire[offset:offset + take])
        remaining -= take
        if remaining <= 0:
            break
    assert len(out) == size
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
    with tempfile.TemporaryDirectory(prefix='frozr-transform-') as td:
        temp = Path(td)
        source = temp / 'quadrants.ppm'
        animated = temp / 'quadrants-animated.png'
        captured = temp / 'captured.mp4'
        raw_frame = temp / 'frame.rgb'
        make_quadrant_ppm(source)
        subprocess.check_call([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1',
            '-i', str(source), '-t', '1', '-r', '4', '-plays', '0', '-f', 'apng', str(animated),
        ])

        master, slave = pty.openpty()
        slave_path = os.ttyname(slave)
        home = temp / 'home'
        home.mkdir()
        env = os.environ.copy()
        env['HOME'] = str(home)
        proc = subprocess.Popen([
            'gjs', str(CLI), '--device', slave_path,
            'media', str(animated), '--background', '--target', TARGET,
            '--rotation', '90',
            '--mirror-horizontal', 'on',
            '--mirror-vertical', 'on',
        ], cwd=ROOT.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        errors = []
        uploaded = b''
        try:
            packet = read_exact(master, PACKET)
            assert_packet(packet, 0x01, 1)
            assert packet[10:12] == b'\xc5\xd3'
            os.write(master, HELLO)

            assert_packet(read_exact(master, PACKET), 0x79, 1)
            assert_packet(read_exact(master, PACKET), 0x96, 1)
            assert_packet(read_exact(master, PACKET), 0x7b, 1)

            packet = read_exact(master, PACKET)
            target = TARGET.encode('ascii')
            assert_packet(packet, 0x6f, len(target))
            assert packet[10:10 + len(target)] == target
            size = int.from_bytes(packet[10 + len(target):14 + len(target)], 'little')
            assert size > 0
            os.write(master, b'create_success')

            chunks = math.ceil(size / RAW)
            wire = read_exact(master, chunks * PACKET, timeout=30.0)
            uploaded = unpack_wire(wire, size)

            packet = read_exact(master, PACKET)
            assert_packet(packet, 0x6e, len(target))
            os.write(master, str(size).encode())

            packet = read_exact(master, PACKET)
            assert_packet(packet, 0x78, len(target), 1)
            os.write(master, b'play_video_success')

            stdout, stderr = proc.communicate(timeout=10)
            if proc.returncode != 0:
                errors.append(f'CLI exit {proc.returncode}: {stderr}')

            captured.write_bytes(uploaded)
            probe = subprocess.check_output([
                'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                '-show_entries', 'stream=codec_name,width,height,nb_read_frames', '-of', 'csv=p=0', str(captured),
            ], text=True).strip()
            codec, width, height, frame_count = probe.split(',')
            if codec != 'h264' or width != '480' or height != '480' or int(frame_count) < 2:
                errors.append(f'unexpected stream: {probe}')

            subprocess.check_call([
                'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(captured),
                '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(raw_frame),
            ])
            frame = raw_frame.read_bytes()
            if len(frame) != 480 * 480 * 3:
                errors.append(f'unexpected frame bytes: {len(frame)}')
            else:
                def sample(x, y):
                    i = (y * 480 + x) * 3
                    return tuple(frame[i:i + 3])
                # Rotation 90 CW, then horizontal mirror, then vertical mirror.
                expected = {
                    'TL': ('green', sample(80, 80)),
                    'TR': ('yellow', sample(400, 80)),
                    'BL': ('red', sample(80, 400)),
                    'BR': ('blue', sample(400, 400)),
                }
                for name, (want, rgb) in expected.items():
                    got = dominant(rgb)
                    if got != want:
                        errors.append(f'{name}: expected {want}, got {got} {rgb}')

            print('stream:', probe)
            print('uploaded bytes:', len(uploaded))
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
