#!/bin/bash
# Build Gist-Mover-x86_64.AppImage. Run from anywhere:  ./packaging/build_appimage.sh
# Needs: python3 with pip, internet access (installs PySide6/requests/pyinstaller into a
# throwaway venv and downloads appimagetool). Build on the OLDEST distro you want to support:
# an AppImage will not run on systems with an older glibc than the one it was built on.
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(dirname "$HERE")"
BUILD="$ROOT/build-appimage"
ARCH="$(uname -m)"
OUT="$ROOT/Gist-Mover-$ARCH.AppImage"

rm -rf "$BUILD"
mkdir -p "$BUILD"
cd "$BUILD"

echo "==> Creating build venv"
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r "$ROOT/requirements.txt" pyinstaller

echo "==> Bundling with PyInstaller"
./venv/bin/pyinstaller --noconfirm --clean --name gist-mover \
    --windowed --contents-directory . \
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick \
    --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia \
    --exclude-module PySide6.QtPdf --exclude-module PySide6.QtCharts \
    --exclude-module tkinter \
    "$ROOT/gist_mover.py" >pyinstaller.log 2>&1 || { tail -30 pyinstaller.log; exit 1; }

echo "==> Assembling AppDir"
APPDIR="$BUILD/AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a dist/gist-mover/. "$APPDIR/usr/bin/"
cp "$HERE/gist-mover.desktop" "$APPDIR/gist-mover.desktop"
cp "$HERE/gist-mover.desktop" "$APPDIR/usr/share/applications/"
./venv/bin/python "$HERE/make_icon.py" "$APPDIR/gist-mover.png" || {
    echo "ERROR: could not generate the icon. Qt needs the system OpenGL libraries; on a bare" >&2
    echo "       Debian/Ubuntu machine install them with: sudo apt install libegl1 libgl1" >&2
    exit 1
}
cp "$APPDIR/gist-mover.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/gist-mover.png"
ln -sf gist-mover.png "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
# Use the host's `gh` login (for `gh auth token`) and keep the bundled libs private to the app.
export PATH="$PATH:$HOME/.local/bin:/usr/local/bin"
export LD_LIBRARY_PATH="$HERE/usr/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
exec "$HERE/usr/bin/gist-mover" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo "==> Bundling libxcb-cursor (required by Qt 6 on X11, missing from many fresh installs)"
CURSOR="$(ldconfig -p 2>/dev/null | awk '/libxcb-cursor\.so\.0 /{print $NF; exit}')"
if [ -z "$CURSOR" ]; then
    mkdir -p "$BUILD/deb" && (cd "$BUILD/deb" && apt-get download libxcb-cursor0 >/dev/null 2>&1 \
        && dpkg-deb -x ./libxcb-cursor0_*.deb x) || true
    CURSOR="$(find "$BUILD/deb" -name 'libxcb-cursor.so.0*' 2>/dev/null | head -1)"
fi
[ -n "$CURSOR" ] || { echo "ERROR: cannot find libxcb-cursor.so.0. Install it (apt install libxcb-cursor0) and re-run."; exit 1; }
cp -L "$CURSOR" "$APPDIR/usr/bin/libxcb-cursor.so.0"

# PyInstaller only bundles the libraries that are installed on THIS machine. If any library the Qt
# X11 plugin needs is missing here, the AppImage would silently fail to start elsewhere, so check.
echo "==> Checking that the bundled Qt X11 plugin has every library it needs"
XCB="$(find "$APPDIR/usr/bin" -name libqxcb.so | head -1)"
[ -n "$XCB" ] || { echo "ERROR: Qt X11 plugin (libqxcb.so) not found in the bundle." >&2; exit 1; }
MISSING="$(LD_LIBRARY_PATH="$APPDIR/usr/bin" ldd "$XCB" | awk '/not found/{print $1}' | sort -u)"
if [ -n "$MISSING" ]; then
    echo "ERROR: the Qt X11 plugin needs libraries that are not installed on this build machine:" >&2
    echo "$MISSING" | sed 's/^/         /' >&2
    echo "       On Debian/Ubuntu/Mint install them, then re-run this script:" >&2
    echo "         sudo apt install libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \\" >&2
    echo "              libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 libxcb-xfixes0 \\" >&2
    echo "              libxcb-xkb1 libxcb-cursor0 libegl1 libgl1" >&2
    exit 1
fi

echo "==> Fetching appimagetool"
TOOL="$BUILD/appimagetool"
curl -fsSL -o "$TOOL" \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
chmod +x "$TOOL"

echo "==> Packing $OUT"
# --appimage-extract-and-run lets appimagetool itself run without FUSE (containers, CI)
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT" 2>&1 | tail -3
chmod +x "$OUT"
echo "Done: $OUT ($(du -h "$OUT" | cut -f1))"
