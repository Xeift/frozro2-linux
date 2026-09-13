#!/usr/bin/env python3
import math
import os
import pty
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = ROOT.parent / 'bin' / 'frozrctl'
TARGET = '/mnt/SDCARD/video/test.mp4'


def read_exact(fd, size, timeout=8.0):
    data = bytearray()
    deadline = time.monotonic() + timeout
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f'timed out after {len(data)}/{size} bytes')
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        chunk = os.read(fd, size - len(data))
        if not chunk:
            raise EOFError(f'pty closed after {len(data)}/{size} bytes')
        data.extend(chunk)
    return bytes(data)


def assert_packet(packet, command, declared_length=None, flag=None):
    assert len(packet) == 250, len(packet)
    assert packet[0] == command, (packet[0], command)
    assert packet[1:3] == b'\xef\x69', packet[:10].hex()
    if declared_length is not None:
        got = int.from_bytes(packet[3:7], 'big')
        assert got == declared_length, (got, declared_length)
    if flag is not None:
        assert packet[7] == flag, (packet[7], flag)


def main():
    sample = bytes((i * 17 + 3) & 0xFF for i in range(1337))
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        f.write(sample)
        local_path = f.name

    master, slave = pty.openpty()
    slave_path = os.ttyname(slave)
    test_home = ROOT / 'home'
    test_home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['HOME'] = str(test_home)
    proc = subprocess.Popen(
        [
            'gjs', str(CLI), '--device', slave_path,
            'media', local_path, '--direct', '--background', '--target', TARGET,
        ],
        cwd=ROOT.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    errors = []
    try:
        pkt = read_exact(master, 250)
        assert_packet(pkt, 0x01, 1, 0)
        assert pkt[10:12] == b'\xc5\xd3'
        os.write(master, b'chs_2inch.dev1_rom1.89')

        pkt = read_exact(master, 250)
        assert_packet(pkt, 0x79, 1, 0)
        pkt = read_exact(master, 250)
        assert_packet(pkt, 0x96, 1, 0)

        pkt = read_exact(master, 250)
        assert_packet(pkt, 0x7B, 1, 0)

        pkt = read_exact(master, 250)
        target_bytes = TARGET.encode('ascii')
        assert_packet(pkt, 0x6F, len(target_bytes), 0)
        assert pkt[10:10 + len(target_bytes)] == target_bytes
        encoded_size = int.from_bytes(
            pkt[10 + len(target_bytes):14 + len(target_bytes)], 'little'
        )
        assert encoded_size == len(sample), (encoded_size, len(sample))
        os.write(master, b'create_success')

        chunk_count = math.ceil(len(sample) / 249)
        wire = read_exact(master, chunk_count * 250)
        for i in range(chunk_count):
            src = sample[i * 249:(i + 1) * 249]
            packet = wire[i * 250:(i + 1) * 250]
            assert packet[:len(src)] == src
            assert packet[len(src):] == bytes(250 - len(src))

        pkt = read_exact(master, 250)
        assert_packet(pkt, 0x6E, len(target_bytes), 0)
        assert pkt[10:10 + len(target_bytes)] == target_bytes
        os.write(master, str(len(sample)).encode('ascii'))

        pkt = read_exact(master, 250)
        assert_packet(pkt, 0x78, len(target_bytes), 1)
        assert pkt[10:10 + len(target_bytes)] == target_bytes
        os.write(master, b'play_video_success')

        stdout, stderr = proc.communicate(timeout=8)
        if proc.returncode != 0:
            errors.append(f'CLI exit {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}')
        expected = [
            'Verified remote size: 1337 bytes',
            'Playback started.',
        ]
        for text in expected:
            if text not in stdout:
                errors.append(f'missing stdout marker: {text!r}\n{stdout}')

        print(f'slave: {slave_path}')
        print(f'exit: {proc.returncode}')
        print('stdout:')
        print(stdout.rstrip())
        print('stderr:')
        print(stderr.rstrip())
        print(f'wire media bytes: {chunk_count * 250}')
        print(f'errors: {errors}')
        return 1 if errors else 0
    except Exception as exc:
        proc.kill()
        stdout, stderr = proc.communicate()
        print(f'FAILED: {exc!r}', file=sys.stderr)
        print(f'stdout:\n{stdout}', file=sys.stderr)
        print(f'stderr:\n{stderr}', file=sys.stderr)
        return 1
    finally:
        os.close(master)
        os.close(slave)
        try:
            os.unlink(local_path)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
