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

# Tar preserves executable permissions; only tracked documentation and examples are included.
git -C "$root" ls-files -z -- README.md CHANGELOG.md LICENSE THIRD_PARTY_NOTICES.md \
    docs/usage.md docs/skin.md docs/desktop.png examples licenses > "$root/build/linux-package-files"
tar -czf "$root/dist/osu-paint-linux-x64.tar.gz" -C "$root/dist" osu-paint \
    -C "$root" --null -T "$root/build/linux-package-files"
printf 'Built: %s\n' "$root/dist/osu-paint-linux-x64.tar.gz"
