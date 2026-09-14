#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${VERSION:-0.1.2}"
ARCH="all"
PKG="frozro2-linux"
BUILD="$ROOT/.build/${PKG}_${VERSION}_${ARCH}"
DIST="$ROOT/dist"

command -v dpkg-deb >/dev/null 2>&1 || {
  echo "dpkg-deb is required (Ubuntu/Debian: sudo apt install dpkg-dev)" >&2
  exit 1
}

rm -rf "$BUILD"
mkdir -p \
  "$BUILD/DEBIAN" \
  "$BUILD/usr/bin" \
  "$BUILD/usr/share/applications" \
  "$BUILD/usr/lib/systemd/system" \
  "$BUILD/usr/lib/udev/rules.d" \
  "$BUILD/usr/share/doc/$PKG" \
  "$DIST"

install -m755 "$ROOT/bin/frozrctl" "$BUILD/usr/bin/frozrctl"
install -m755 "$ROOT/bin/frozr-gui" "$BUILD/usr/bin/frozr-gui"
install -m644 "$ROOT/packaging/60-frozr-lcd.rules" "$BUILD/usr/lib/udev/rules.d/60-frozr-lcd.rules"
install -m644 "$ROOT/LICENSE" "$BUILD/usr/share/doc/$PKG/copyright"
install -m644 "$ROOT/README.md" "$BUILD/usr/share/doc/$PKG/README.md"

sed 's|@GUI@|/usr/bin/frozr-gui|g' \
  "$ROOT/share/applications/io.github.xeift.FrozrO2Linux.desktop.in" \
  > "$BUILD/usr/share/applications/io.github.xeift.FrozrO2Linux.desktop"

sed 's|@CLI@|/usr/bin/frozrctl|g' \
  "$ROOT/share/systemd/system/frozr-restore@.service.in" \
  > "$BUILD/usr/lib/systemd/system/frozr-restore@.service"
chmod 644 "$BUILD/usr/lib/systemd/system/frozr-restore@.service"

cat > "$BUILD/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: gjs, ffmpeg, gir1.2-gtk-4.0, gir1.2-adw-1, udev
Maintainer: Xeift
Description: Linux controller for the XIGMATEK Frozr-O II LCD
 Clean-room Linux CLI and GTK4 frontend for image display, media upload,
 on-device playback, live system dashboard, storage management, brightness,
 serial permissions and boot state restore.
EOF

cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules || true
  udevadm trigger --subsystem-match=tty || true
fi

TARGET_USER="${SUDO_USER:-}"
if [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != root ] && command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  systemctl enable --now "frozr-restore@${TARGET_USER}.service" >/dev/null
fi
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/postinst"

cat > "$BUILD/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
case "$1" in
  remove|deconfigure)
    if command -v systemctl >/dev/null 2>&1; then
      for link in /etc/systemd/system/multi-user.target.wants/frozr-restore@*.service; do
        [ -L "$link" ] || continue
        systemctl disable --now "$(basename "$link")" >/dev/null 2>&1 || true
      done
    fi
    ;;
esac
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/prerm"

cat > "$BUILD/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v udevadm >/dev/null 2>&1; then
  udevadm control --reload-rules || true
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
fi
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/postrm"

dpkg-deb --build --root-owner-group "$BUILD" "$DIST/${PKG}_${VERSION}_${ARCH}.deb"
echo "$DIST/${PKG}_${VERSION}_${ARCH}.deb"
