#!/usr/bin/env bash
set -euo pipefail

systemctl --user disable --now frozr-restore.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/frozr-restore.service"
rm -f "$HOME/.local/share/applications/io.github.xeift.FrozrO2Linux.desktop"
rm -f "$HOME/.local/bin/frozrctl" "$HOME/.local/bin/frozr-gui"
rm -rf "$HOME/.local/lib/frozro2-linux"
systemctl --user daemon-reload || true

echo "Removed the per-user Frozr-O II Linux installation."
echo "Settings under ~/.config/frozr-linux are preserved."
echo "If you installed the udev rule, remove it separately with:"
echo "  sudo rm -f /etc/udev/rules.d/60-frozr-lcd.rules"
