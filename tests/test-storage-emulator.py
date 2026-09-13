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
VIDEO_DIR = '/mnt/SDCARD/video/'
TARGET = VIDEO_DIR + 'old.mp4'


def read_exact(fd, size, timeout=6.0):
    data = bytearray()
    deadline = time.monotonic() + timeout
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f'wanted {size}, got {len(data)} bytes')
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        chunk = os.read(fd, size - len(data))
        if not chunk:
            raise EOFError(f'wanted {size}, got EOF at {len(data)} bytes')
        data.extend(chunk)
    return bytes(data)


def assert_packet(packet, command, declared_length=None, flag=0, payload=None):
    assert len(packet) == 250
    assert packet[0] == command, (packet[0], command)
    assert packet[1:3] == b'\xef\x69'
    length = int.from_bytes(packet[3:7], 'big')
    if declared_length is not None:
        assert length == declared_length, (length, declared_length)
    assert packet[7] == flag, (packet[7], flag)
    if payload is not None:
        assert packet[10:10 + len(payload)] == payload


def start_cli(*args):
    master, slave = pty.openpty()
    slave_path = os.ttyname(slave)
    test_home = ROOT / 'home'
    test_home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['HOME'] = str(test_home)
    proc = subprocess.Popen(
        ['gjs', str(CLI), '--device', slave_path, *args],
        cwd=ROOT.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    return proc, master, slave


def hello(master):
    packet = read_exact(master, 250)
    assert_packet(packet, 0x01, 1, 0, b'\xc5\xd3')
    os.write(master, HELLO)


def finish(proc, master, slave, expected_stdout=()):
    try:
        stdout, stderr = proc.communicate(timeout=7)
    finally:
        os.close(master)
        os.close(slave)
    if proc.returncode != 0:
        raise AssertionError(f'CLI exit {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}')
    for marker in expected_stdout:
        if marker not in stdout:
            raise AssertionError(f'missing {marker!r}\nstdout:\n{stdout}')
    return stdout


def test_list():
    proc, master, slave = start_cli('ls', VIDEO_DIR)
    hello(master)
    payload = VIDEO_DIR.encode('ascii')
    packet = read_exact(master, 250)
    assert_packet(packet, 0x65, len(payload), 0, payload)
    os.write(master, b'file:one.mp4/two.mp4/')
    stdout = finish(proc, master, slave, ('one.mp4', 'two.mp4'))
    return stdout


def test_empty_list():
    proc, master, slave = start_cli('ls', '/mnt/SDCARD/img/')
    hello(master)
    payload = b'/mnt/SDCARD/img/'
    packet = read_exact(master, 250)
    assert_packet(packet, 0x65, len(payload), 0, payload)
    os.write(master, b'nodir-createdone')
    stdout = finish(proc, master, slave)
    if stdout.strip():
        raise AssertionError(f'expected empty listing, got {stdout!r}')
    return stdout


def test_delete():
    proc, master, slave = start_cli('rm', TARGET)
    hello(master)
    target = TARGET.encode('ascii')
    packet = read_exact(master, 250)
    assert_packet(packet, 0x66, len(target), 0, target)
    parent = VIDEO_DIR.encode('ascii')
    packet = read_exact(master, 250)
    assert_packet(packet, 0x65, len(parent), 0, parent)
    os.write(master, b'file:kept.mp4/')
    stdout = finish(proc, master, slave, (f'Deleted {TARGET}',))
    return stdout


def test_storage():
    proc, master, slave = start_cli('storage')
    hello(master)
    packet = read_exact(master, 250)
    assert_packet(packet, 0x64, 1, 0)
    os.write(master, b'100-200-300-400-500-600')
    stdout = finish(proc, master, slave, ('Storage counters: 100 - 200 - 300 - 400 - 500 - 600',))
    return stdout


def main():
    tests = [test_list, test_empty_list, test_delete, test_storage]
    failures = []
    for test in tests:
        try:
            stdout = test()
            print(f'PASS {test.__name__}')
            if stdout.strip():
                print(stdout.strip())
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f'FAIL {test.__name__}: {exc}', file=sys.stderr)
    if failures:
        return 1
    print(f'passed {len(tests)} storage protocol tests')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
