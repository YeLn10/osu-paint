"""Build full-height Pixel Film skins for 1–18K and common display ratios."""

from pathlib import Path
import struct
import zipfile
import zlib


DEFAULT_ASPECT_RATIO = 16 / 10
SKIN_PROFILES = {
    "pixel-film.osk": (DEFAULT_ASPECT_RATIO, "16:10"),
    "pixel-film-16x9.osk": (16 / 9, "16:9"),
    "pixel-film-4x3.osk": (4 / 3, "4:3"),
    "pixel-film-2560x1080.osk": (2560 / 1080, "2560x1080"),
    "pixel-film-3440x1440.osk": (3440 / 1440, "3440x1440"),
}


def skin_ini(*, rows=24, aspect_ratio=DEFAULT_ASPECT_RATIO, label="16:10"):
    if not isinstance(rows, int) or rows < 1:
        raise ValueError("皮肤行数须为正整数。")
    note_height = f"{480 / rows:.9f}".rstrip("0").rstrip(".")
    lines = ["[General]", f"Name: osu-paint Pixel Film {label} ({rows} rows)",
             "Author: osu-paint", "Version: 2.7"]
    for keys in range(1, 19):
        width = f"{480 * aspect_ratio / keys:.9f}".rstrip("0").rstrip(".")
        lines.extend([
            "", "[Mania]", f"Keys: {keys}", "HitPosition: 480",
            "ColumnWidth: " + ",".join([width] * keys),
            "ColumnSpacing: " + ",".join(["0"] * (keys - 1)),
            "ColumnLineWidth: " + ",".join(["0"] * (keys + 1)),
            "BarlineHeight: 0", "ColourBarline: 255,255,255,0",
            "ColourColumnLine: 255,255,255,0", "JudgementLine: 0",
            "ScorePosition: 1000", "ComboPosition: 1000",
            f"WidthForNoteHeightScale: {note_height}", "UpsideDown: 0", "NoteBodyStyle: 0",
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


def build_skin(path, *, rows=24, aspect_ratio=DEFAULT_ASPECT_RATIO, label="16:10"):
    files = {
        "skin.ini": skin_ini(rows=rows, aspect_ratio=aspect_ratio, label=label).encode("utf-8"),
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


def build_skins(directory, rows=24):
    return [build_skin(Path(directory) / filename, rows=rows, aspect_ratio=ratio, label=label)
            for filename, (ratio, label) in SKIN_PROFILES.items()]
