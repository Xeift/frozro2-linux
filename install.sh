#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
INSTALL_UDEV=0
UDEV_ALREADY_INSTALLED="${FROZR_UDEV_ALREADY_INSTALLED:-0}"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--udev]

Installs Frozr-O II Linux for the current desktop user.
  --udev   Also install the serial access rule (recommended).

You may run this script normally:
  ./install.sh --udev

If you run the whole script with sudo, it will install the udev rule as root,
then automatically continue the per-user installation as the original user.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --udev) INSTALL_UDEV=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

# A common mistake is `sudo ./install.sh --udev`. Support it safely: use the
# root process only for the udev rule, then drop back to the original desktop
# user for ~/.local files and systemd --user registration.
if [[ "$EUID" -eq 0 ]]; then
  if [[ -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
    echo "Do not install Frozr-O II Linux as root directly; run it from your desktop user." >&2
    echo "Example: ./install.sh --udev" >&2
    exit 1
  fi

  TARGET_USER="$SUDO_USER"
  TARGET_UID="$(id -u "$TARGET_USER")"
  TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
  if [[ -z "$TARGET_HOME" ]]; then
    echo "Could not determine home directory for $TARGET_USER" >&2
    exit 1
  fi

  if [[ "$INSTALL_UDEV" -eq 1 ]]; then
    install -m644 "$ROOT/packaging/60-frozr-lcd.rules" /etc/udev/rules.d/60-frozr-lcd.rules
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=tty || true
    UDEV_ALREADY_INSTALLED=1
  fi

  RUNTIME_DIR="/run/user/$TARGET_UID"
  BUS_ADDRESS="unix:path=$RUNTIME_DIR/bus"
  exec sudo -u "$TARGET_USER" env \
    HOME="$TARGET_HOME" \
    USER="$TARGET_USER" \
    LOGNAME="$TARGET_USER" \
    XDG_RUNTIME_DIR="$RUNTIME_DIR" \
    DBUS_SESSION_BUS_ADDRESS="$BUS_ADDRESS" \
    FROZR_UDEV_ALREADY_INSTALLED="$UDEV_ALREADY_INSTALLED" \
    "$ROOT/install.sh" "$@"
fi

PREFIX="${HOME}/.local"
LIBDIR="${PREFIX}/lib/frozro2-linux"
BINDIR="${PREFIX}/bin"
APPDIR="${HOME}/.local/share/applications"
USERUNITDIR="${HOME}/.config/systemd/user"

for cmd in gjs ffmpeg ffprobe systemctl sed; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    if [[ "$cmd" == "ffmpeg" || "$cmd" == "ffprobe" ]]; then
      echo "Ubuntu/Debian: sudo apt install ffmpeg" >&2
    fi
    exit 1
  fi
done

if ! gjs -c "imports.gi.versions.Gtk='4.0'; imports.gi.Gtk; imports.gi.versions.Adw='1'; imports.gi.Adw" >/dev/null 2>&1; then
  echo "GTK4/Libadwaita GObject introspection packages are required." >&2
  echo "Ubuntu/Debian: sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1" >&2
  exit 1
fi


mkdir -p "$LIBDIR" "$BINDIR" "$APPDIR" "$USERUNITDIR"
install -m755 "$ROOT/bin/frozrctl" "$LIBDIR/frozrctl"
install -m755 "$ROOT/bin/frozr-gui" "$LIBDIR/frozr-gui"
ln -sfn "$LIBDIR/frozrctl" "$BINDIR/frozrctl"
ln -sfn "$LIBDIR/frozr-gui" "$BINDIR/frozr-gui"

sed "s|@GUI@|${BINDIR}/frozr-gui|g" \
  "$ROOT/share/applications/io.github.xeift.FrozrO2Linux.desktop.in" \
  > "$APPDIR/io.github.xeift.FrozrO2Linux.desktop"
chmod 644 "$APPDIR/io.github.xeift.FrozrO2Linux.desktop"

sed "s|@CLI@|${BINDIR}/frozrctl|g" \
  "$ROOT/share/systemd/user/frozr-restore.service.in" \
  > "$USERUNITDIR/frozr-restore.service"
chmod 644 "$USERUNITDIR/frozr-restore.service"

if systemctl --user daemon-reload; then
  systemctl --user enable frozr-restore.service >/dev/null
else
  cat >&2 <<'EOF'
warning: could not contact the user systemd session.
The CLI/GUI were installed, but the automatic login-restore service could not be enabled.
From a normal desktop terminal, run:
  systemctl --user daemon-reload
  systemctl --user enable frozr-restore.service
EOF
fi

if [[ "$INSTALL_UDEV" -eq 1 && "$UDEV_ALREADY_INSTALLED" -ne 1 ]]; then
  sudo install -m644 "$ROOT/packaging/60-frozr-lcd.rules" /etc/udev/rules.d/60-frozr-lcd.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=tty || true
fi

cat <<EOF
Installed Frozr-O II Linux.

CLI: $BINDIR/frozrctl
GUI: $BINDIR/frozr-gui
Auto-restore service: frozr-restore.service
EOF

if [[ "$INSTALL_UDEV" -eq 0 ]]; then
  cat <<'EOF'

Serial permissions were not changed. To enable normal non-root access, rerun:
  ./install.sh --udev
EOF
else
  cat <<'EOF'

udev serial-access rule installed. Replug the LCD if the current tty keeps its old permissions.
EOF
fi
