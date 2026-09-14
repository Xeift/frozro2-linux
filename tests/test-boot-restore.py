#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
service = (ROOT / 'share/systemd/system/frozr-restore@.service.in').read_text()
installer = (ROOT / 'install.sh').read_text()
packager = (ROOT / 'packaging/build-deb.sh').read_text()
gui = (ROOT / 'bin/frozr-gui').read_text()

assert not (ROOT / 'share/systemd/user/frozr-restore.service.in').exists()
assert 'After=graphical-session.target' not in service
assert 'Environment=SUDO_USER=%i' in service
assert 'ExecStart=@CLI@ restore' in service
assert 'Restart=on-failure' in service
assert 'RestartSec=2' in service
assert 'StartLimitIntervalSec=0' in service
assert 'WantedBy=multi-user.target' in service

assert 'loginctl enable-linger' not in installer
assert 'systemctl --user' not in installer
assert 'sudo systemctl enable --now "frozr-restore@${USER}.service"' in installer

assert 'usr/lib/systemd/system' in packager
assert 'usr/lib/systemd/user' not in packager
assert 'systemctl enable --now "frozr-restore@${TARGET_USER}.service"' in packager
assert 'remove|deconfigure)' in packager
assert 'loginctl enable-linger' not in packager

assert "label: 'After Linux starts'" in gui
assert 'restored automatically on the next boot.' in gui

print('system boot restore service checks passed')
