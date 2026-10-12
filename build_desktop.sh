#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="${1:-python3}"
environment="$root/.build-env"
build_python="$environment/bin/python"

# Keep packaging tools isolated from the user's Python installation.
if [[ ! -f "$build_python" ]]; then
    "$python" -m venv "$environment"
fi
"$build_python" -m pip install --disable-pip-version-check "pyinstaller==6.22.3" -r "$root/requirements.txt"
"$build_python" -m PyInstaller --noconfirm --onefile --windowed --collect-all imageio_ffmpeg --name osu-paint \
    --distpath "$root/dist" --workpath "$root/build" --specpath "$root/build" "$root/osu-paint.pyw"
"$build_python" "$root/tools/verify_package.py" --exe "$root/dist/osu-paint" > "$root/dist/verify-linux-x64.json"

# Preserve executable permissions and resolve links to documentation outside the bundle.
"$build_python" "$root/tools/package_linux.py"
