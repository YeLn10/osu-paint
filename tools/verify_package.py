"""Verify that the Windows executable contains the current project code."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULES = ("osu_paint", "osu_paint_desktop", "osu_paint_video", "osu_paint_audio", "osu_paint_skin")


def verify_package(executable):
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    for name in MODULES:
        bundled = pyz.extract(name)
        expected = compile((ROOT / f"{name}.py").read_bytes(), bundled.co_filename, "exec")
        if bundled != expected:
            raise ValueError(f"{name} differs from current source; rebuild the executable.")
    if not any("ffmpeg" in name.lower() and name.endswith(".exe") for name in archive.toc):
        raise ValueError("FFmpeg is missing from the executable.")
    if "mutagen.oggvorbis" not in pyz.toc:
        raise ValueError("Mutagen Ogg decoding is missing from the executable.")
    if not any("pygame" in name and "mixer" in name for name in archive.toc):
        raise ValueError("pygame mixer is missing from the executable.")
    return {"modules_match_source": list(MODULES), "media_components_included": True,
            "exe_bytes": executable.stat().st_size,
            "exe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=ROOT / "dist/osu-paint.exe")
    args = parser.parse_args()
    print(json.dumps(verify_package(args.exe), indent=2))
