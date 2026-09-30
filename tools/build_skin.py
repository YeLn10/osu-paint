"""Rebuild the 1–16K Pixel Film skin using only the Python standard library."""

from pathlib import Path
import struct
import zipfile
import zlib


def skin_ini():
    lines = ["[General]", "Name: osu-paint Pixel Film", "Author: osu-paint", "Version: 2.7"]
    for keys in range(1, 17):
        lines.extend([
            "", "[Mania]", f"Keys: {keys}", "SplitStages: 0", "StageSeparation: 0",
            "ColumnStart: 0", "ColumnRight: 0", "HitPosition: 402",
            "ColumnWidth: " + ",".join(["40"] * keys),
            "ColumnSpacing: " + ",".join(["0"] * (keys - 1)),
            "ColumnLineWidth: " + ",".join(["0"] * (keys + 1)),
            "BarlineHeight: 0", "ColourBarline: 255,255,255,0",
            "ColourColumnLine: 255,255,255,0", "JudgementLine: 0",
            "ScorePosition: 1000", "ComboPosition: 1000",
            "WidthForNoteHeightScale: 40", "UpsideDown: 0", "NoteBodyStyle: 0",
            "StageLeft: blank", "StageRight: blank", "StageBottom: blank", "StageHint: blank",
            "LightingN: blank", "LightingL: blank", "StageLight: blank",
        ])
        for column in range(keys):
            lines.extend([
                f"Colour{column + 1}: 255,255,255,255",
                f"KeyImage{column}: blank", f"KeyImage{column}D: blank",
                f"NoteImage{column}: pixel-black", f"NoteImage{column}H: pixel-black",
                f"NoteImage{column}L: pixel-body", f"NoteImage{column}T: pixel-black",
            ])
    return "\n".join(lines) + "\n"


def solid_png(width, height, colour):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    rows = (b"\x00" + bytes(colour) * width) * height
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def build_skin(path):
    files = {
        "skin.ini": skin_ini().encode("utf-8"),
        "blank.png": solid_png(40, 1, (0, 0, 0, 0)),
        "pixel-black.png": solid_png(40, 40, (0, 0, 0, 255)),
        "pixel-body.png": solid_png(40, 1, (0, 0, 0, 255)),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            # Fixed metadata makes the versioned delivery reproducible.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    return path


if __name__ == "__main__":
    print(build_skin(Path(__file__).resolve().parents[1] / "pixel-film.osk"))
