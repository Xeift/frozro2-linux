#!/usr/bin/env python3
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLI = ROOT.parent / 'bin' / 'frozrctl'

COLORS = {
    'r': bytes((255, 0, 0)),
    'g': bytes((0, 255, 0)),
    'b': bytes((0, 0, 255)),
    'y': bytes((255, 255, 0)),
}


def make_ppm(path):
    w = h = 8
    pixels = bytearray()
    for y in range(h):
        for x in range(w):
            if y < 4 and x < 4:
                pixels += COLORS['r']
            elif y < 4:
                pixels += COLORS['g']
            elif x < 4:
                pixels += COLORS['b']
            else:
                pixels += COLORS['y']
    path.write_bytes(f'P6\n{w} {h}\n255\n'.encode() + pixels)


def decode_rgb(path):
    return subprocess.check_output([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(path),
        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-frames:v', '1', '-'
    ])


def sample(raw, x, y):
    i = (y * 480 + x) * 3
    return raw[i:i + 3]


def close(actual, expected, tolerance=12):
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected))


def verify(path, tolerance=12):
    raw = decode_rgb(path)
    expected = {
        (40, 40): COLORS['r'],
        (440, 40): COLORS['b'],
        (40, 440): COLORS['g'],
        (440, 440): COLORS['y'],
    }
    for point, color in expected.items():
        got = sample(raw, *point)
        assert close(got, color, tolerance), (point, tuple(got), tuple(color))


def main():
    with tempfile.TemporaryDirectory(prefix='frozr-preview-test-') as td:
        td = Path(td)
        source = td / 'quadrants.ppm'
        make_ppm(source)

        static_out = td / 'static.png'
        subprocess.check_call([
            'gjs', str(CLI), 'preview', str(source), str(static_out),
            '--rotation', '90', '--mirror-horizontal', 'on', '--mirror-vertical', 'off',
        ], cwd=ROOT.parent)
        verify(static_out, tolerance=0)

        video = td / 'quadrants.mp4'
        subprocess.check_call([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1',
            '-i', str(source), '-t', '1', '-r', '2', '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p', str(video),
        ])
        video_out = td / 'video.png'
        subprocess.check_call([
            'gjs', str(CLI), 'preview', str(video), str(video_out),
            '--rotation', '90', '--mirror-horizontal', 'on', '--mirror-vertical', 'off',
        ], cwd=ROOT.parent)
        verify(video_out, tolerance=20)

        static_info = json.loads(subprocess.check_output([
            'gjs', str(CLI), 'content-info', str(source),
        ], cwd=ROOT.parent, text=True))
        assert static_info['kind'] == 'static', static_info

        apng = td / 'animated.png'
        subprocess.check_call([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=4:duration=1',
            '-plays', '0', '-f', 'apng', str(apng),
        ])
        apng_info = json.loads(subprocess.check_output([
            'gjs', str(CLI), 'content-info', str(apng),
        ], cwd=ROOT.parent, text=True))
        assert apng_info['kind'] == 'animated', apng_info
        assert apng_info['codec'] == 'apng', apng_info
        assert apng_info['framesSeen'] >= 2, apng_info

        apng_preview = td / 'animated-preview.mp4'
        subprocess.check_call([
            'gjs', str(CLI), 'preview', str(apng), str(apng_preview),
            '--rotation', '270', '--mirror-horizontal', 'on', '--mirror-vertical', 'on',
        ], cwd=ROOT.parent)
        preview_probe = subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
            '-show_entries', 'stream=codec_name,width,height,nb_read_frames',
            '-of', 'json', str(apng_preview),
        ], text=True)
        preview_stream = json.loads(preview_probe)['streams'][0]
        assert preview_stream['codec_name'] == 'h264', preview_stream
        assert preview_stream['width'] == 480 and preview_stream['height'] == 480, preview_stream
        assert int(preview_stream['nb_read_frames']) >= 2, preview_stream

    print('preview static/video/APNG checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
