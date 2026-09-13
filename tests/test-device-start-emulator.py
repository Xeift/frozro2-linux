#!/usr/bin/env python3
import json
import math
import os
import pty
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = ROOT.parent / 'bin' / 'frozrctl'
HELLO = b'chs_2inch.dev1_rom1.89'
BRIGHTNESS = 40
RAW_BRIGHTNESS = math.floor(BRIGHTNESS * 255 / 100)
FLIP = 1
SLEEP_DELAY = 7


def read_exact(fd, size, timeout=8.0):
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
    return length


def config_for(home):
    cfg = home / '.config' / 'frozr-linux' / 'config.json'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({
        'version': 1,
        'autoRestore': False,
        'brightness': BRIGHTNESS,
        'rotation': 0,
        'mirrorHorizontal': False,
        'mirrorVertical': False,
        'deviceConfig': {
            'startMode': 0,
            'flip': True,
            'sleepDelay': SLEEP_DELAY,
        },
        'powerOffDisplay': {
            'mode': 'default',
            'source': None,
            'target': None,
        },
        'lastAction': None,
    }, indent=2) + '\n')
    return cfg


def start_cli(name, *args):
    master, slave = pty.openpty()
    slave_path = os.ttyname(slave)
    home = ROOT / f'home-device-start-{name}'
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    cfg = config_for(home)
    env = os.environ.copy()
    env['HOME'] = str(home)
    for key in ('SUDO_USER', 'SUDO_UID', 'SUDO_GID'):
        env.pop(key, None)
    proc = subprocess.Popen(
        ['gjs', str(CLI), '--device', slave_path, *args],
        cwd=ROOT.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    return proc, master, slave, home, cfg


def hello(master):
    packet = read_exact(master, 250)
    assert_packet(packet, 0x01, 1, 0, b'\xc5\xd3')
    os.write(master, HELLO)


def expect_stop_and_brightness(master):
    assert_packet(read_exact(master, 250), 0x79, 1)
    assert_packet(read_exact(master, 250), 0x96, 1)
    assert_packet(read_exact(master, 250), 0x7b, 1, 0, bytes([RAW_BRIGHTNESS]))


def receive_upload(master, expected_path):
    path = expected_path.encode('ascii')
    packet = read_exact(master, 250)
    declared = assert_packet(packet, 0x6f, len(path), 0, path)
    assert declared == len(path)
    size = int.from_bytes(packet[10 + len(path):14 + len(path)], 'little')
    assert size > 0
    os.write(master, b'create_success')

    wire_size = math.ceil(size / 249) * 250
    wire = read_exact(master, wire_size, timeout=12.0)
    raw = bytearray()
    remaining = size
    for offset in range(0, len(wire), 250):
        take = min(249, remaining)
        raw.extend(wire[offset:offset + take])
        remaining -= take
    assert len(raw) == size

    packet = read_exact(master, 250)
    assert_packet(packet, 0x6e, len(path), 0, path)
    os.write(master, str(size).encode('ascii'))
    return bytes(raw)


def expect_options(master, start_mode):
    payload = bytes([RAW_BRIGHTNESS, start_mode, 0, FLIP, SLEEP_DELAY])
    assert_packet(read_exact(master, 250), 0x7d, 5, 0, payload)


def finish(proc, master, slave, home, expected_stdout=()):
    try:
        stdout, stderr = proc.communicate(timeout=10)
    finally:
        os.close(master)
        os.close(slave)
    if proc.returncode != 0:
        raise AssertionError(f'CLI exit {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}')
    for marker in expected_stdout:
        if marker not in stdout:
            raise AssertionError(f'missing {marker!r}\nstdout:\n{stdout}')
    return stdout


def test_default():
    proc, master, slave, home, cfg = start_cli('default', 'device-start', 'default')
    hello(master)
    expect_options(master, 0)
    stdout = finish(proc, master, slave, home, ('Device startup display set to firmware default.',))
    saved = json.loads(cfg.read_text())
    assert saved['deviceConfig'] == {'startMode': 0, 'flip': True, 'sleepDelay': SLEEP_DELAY}
    assert 'autoRestore' not in saved
    assert 'powerOffDisplay' not in saved
    assert saved['startupDisplay']['mode'] == 'default'
    shutil.rmtree(home, ignore_errors=True)
    return stdout


def make_ppm(path):
    # Four visible quadrants; startup image conversion must produce a real JPEG.
    pixels = bytes([
        255, 0, 0,   0, 255, 0,
        0, 0, 255,   255, 255, 255,
    ])
    path.write_bytes(b'P6\n2 2\n255\n' + pixels)


def test_image():
    image = ROOT / 'device-start-test.ppm'
    make_ppm(image)
    expected = '/mnt/SDCARD/img/frozr-startup-device-start-test.jpg'
    proc, master, slave, home, cfg = start_cli(
        'image', 'device-start', 'image', str(image), '--rotation', '90', '--mirror-horizontal', 'on')
    try:
        hello(master)
        expect_stop_and_brightness(master)
        raw = receive_upload(master, expected)
        assert raw.startswith(b'\xff\xd8'), 'startup image upload is not JPEG'
        assert raw.endswith(b'\xff\xd9'), 'startup JPEG is truncated'

        path = expected.encode('ascii')
        assert_packet(read_exact(master, 250), 0x8c, len(path), 0, path)
        os.write(master, b'play_img_ok')
        expect_options(master, 1)
        stdout = finish(proc, master, slave, home, ('Startup image selected.', 'Firmware startup mode saved: image.'))
        saved = json.loads(cfg.read_text())
        assert saved['deviceConfig'] == {'startMode': 1, 'flip': True, 'sleepDelay': SLEEP_DELAY}
        assert saved['startupDisplay']['mode'] == 'image'
        assert saved['startupDisplay']['target'] == expected
        assert saved['startupDisplay']['rotation'] == 90
        assert saved['startupDisplay']['mirrorHorizontal'] is True
        assert saved['rotation'] == 0
        assert saved['mirrorHorizontal'] is False
        assert saved['mirrorVertical'] is False

        env = os.environ.copy()
        env['HOME'] = str(home)
        for key in ('SUDO_USER', 'SUDO_UID', 'SUDO_GID'):
            env.pop(key, None)
        dry = subprocess.run(
            ['gjs', str(CLI), '--dry-run', 'device-start', 'image', str(image)],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        dry_cfg = json.loads(dry.stdout)
        assert dry_cfg['rotation'] == 90
        assert dry_cfg['mirrorHorizontal'] is True
        assert dry_cfg['mirrorVertical'] is False
        return stdout
    finally:
        image.unlink(missing_ok=True)
        shutil.rmtree(home, ignore_errors=True)


def test_media():
    media = ROOT / 'device-start-test.mp4'
    media.write_bytes(bytes((i * 17) % 256 for i in range(1337)))
    expected = '/mnt/SDCARD/video/frozr-startup-device-start-test.mp4'
    proc, master, slave, home, cfg = start_cli('media', 'device-start', 'media', str(media), '--direct')
    try:
        hello(master)
        expect_stop_and_brightness(master)
        raw = receive_upload(master, expected)
        assert raw == media.read_bytes()

        path = expected.encode('ascii')
        assert_packet(read_exact(master, 250), 0x78, len(path), 1, path)
        os.write(master, b'play_video_success')
        expect_options(master, 2)
        stdout = finish(proc, master, slave, home, ('Startup animation/video selected.', 'Firmware startup mode saved: media.'))
        saved = json.loads(cfg.read_text())
        assert saved['deviceConfig'] == {'startMode': 2, 'flip': True, 'sleepDelay': SLEEP_DELAY}
        assert saved['startupDisplay']['mode'] == 'media'
        assert saved['startupDisplay']['target'] == expected
        assert saved['rotation'] == 0
        assert saved['mirrorHorizontal'] is False
        assert saved['mirrorVertical'] is False
        return stdout
    finally:
        media.unlink(missing_ok=True)
        shutil.rmtree(home, ignore_errors=True)


def test_replaces_managed_startup_asset():
    media = ROOT / 'device-start-replace.mp4'
    media.write_bytes(bytes((i * 29) % 256 for i in range(911)))
    expected = '/mnt/SDCARD/video/frozr-startup-device-start-replace.mp4'
    previous = '/mnt/SDCARD/video/frozr-startup-old.mp4'
    home = ROOT / 'home-device-start-replace'
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    cfg = config_for(home)
    saved = json.loads(cfg.read_text())
    saved.pop('powerOffDisplay', None)
    saved['startupDisplay'] = {
        'mode': 'media',
        'source': '/tmp/old.mp4',
        'target': previous,
        'rotation': 0,
        'mirrorHorizontal': False,
        'mirrorVertical': False,
    }
    saved['deviceConfig']['startMode'] = 2
    cfg.write_text(json.dumps(saved, indent=2) + '\n')

    master, slave = pty.openpty()
    slave_path = os.ttyname(slave)
    env = os.environ.copy()
    env['HOME'] = str(home)
    for key in ('SUDO_USER', 'SUDO_UID', 'SUDO_GID'):
        env.pop(key, None)
    proc = subprocess.Popen(
        ['gjs', str(CLI), '--device', slave_path, 'device-start', 'media', str(media), '--direct'],
        cwd=ROOT.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        hello(master)
        expect_stop_and_brightness(master)
        raw = receive_upload(master, expected)
        assert raw == media.read_bytes()
        path = expected.encode('ascii')
        assert_packet(read_exact(master, 250), 0x78, len(path), 1, path)
        os.write(master, b'play_video_success')
        expect_options(master, 2)
        previous_bytes = previous.encode('ascii')
        assert_packet(read_exact(master, 250), 0x66, len(previous_bytes), 0, previous_bytes)
        stdout = finish(proc, master, slave, home, ('Removed previous startup asset',))
        current = json.loads(cfg.read_text())
        assert current['startupDisplay']['target'] == expected
        return stdout
    finally:
        media.unlink(missing_ok=True)
        shutil.rmtree(home, ignore_errors=True)


def test_restore_is_automatic():
    home = ROOT / 'home-device-start-restore'
    shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    cfg = config_for(home)
    saved = json.loads(cfg.read_text())
    saved['lastAction'] = {'type': 'stopped'}
    cfg.write_text(json.dumps(saved, indent=2) + '\n')
    env = os.environ.copy()
    env['HOME'] = str(home)
    for key in ('SUDO_USER', 'SUDO_UID', 'SUDO_GID'):
        env.pop(key, None)
    try:
        proc = subprocess.run(
            ['gjs', str(CLI), '--dry-run', 'restore'],
            cwd=ROOT.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(f'CLI exit {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}')
        assert '"command": "restore"' in proc.stdout
        assert 'Auto restore is disabled' not in proc.stdout
        return proc.stdout
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main():
    tests = [test_default, test_image, test_media, test_replaces_managed_startup_asset, test_restore_is_automatic]
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
    print(f'passed {len(tests)} device-start protocol tests')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
