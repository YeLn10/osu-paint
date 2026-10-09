"""Stable sprite clipping, checked against native MovementY fixtures."""

from bisect import bisect_right
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from osu_paint import compile_frames, encode_osu
from osu_paint_skin import SKIN_PROFILES, build_skin
from test_skin import mania_sections, png_pixels
from test_stable_geometry import decode


def f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def movements(points, time, height, offset=0, duration=0, scroll_speed=27):
    # Independent transcription of the target's clipped sprite transforms.
    # These are not the compiler's unclipped Timeline positions.
    index = bisect_right([p[0] for p in points], time) - 1
    result = []
    end, y = time, 480
    for start, beat in reversed(points[:index + 1]):
        speed = 21 * (scroll_speed * 100 / 120) / beat
        y0 = y - speed * (end - start)
        if start == end:
            continue
        if y0 < 0:
            start, y0 = end - y / speed, 0
        result.append(dict(start=int(start), end=int(end), y0=f32(y0 + offset), y1=f32(y + offset), tag=1))
        if y0 == 0:
            break
        end, y = start, y0
    start, y, until, limit, tag = time, 480, time + duration, float("inf"), 2
    for (_, beat), (next_time, _) in zip(points[index:], points[index + 1:]):
        speed = 21 * (scroll_speed * 100 / 120) / beat
        while True:
            end = min(next_time, until)
            y1 = y + speed * (end - start)
            if start != end:
                if y1 > limit:
                    end, y1 = start + (limit - y) / speed, limit
                result.append(dict(start=int(start), end=int(end), y0=f32(f32(y) + offset),
                                   y1=f32(f32(y1) + offset), tag=tag))
                if y1 == limit:
                    return sorted(result, key=lambda t: (t["start"], t["end"]))
                start, y = end, y1
            if end != until:
                break
            limit, until, tag = y1 + height, float("inf"), 3
    return sorted(result, key=lambda t: (t["start"], t["end"]))


def sprites(points, objects, note_height=40, scroll_speed=27):
    result = []
    for head, tail in objects:
        parts = [(head, note_height, 0, 0)]
        if tail != head:
            parts.extend([(tail, note_height, 0, 0), (head, note_height / 2, -note_height / 2, tail - head)])
        for time, height, offset, duration in parts:
            path = movements(points, time, height, offset, duration, scroll_speed)
            size = note_height
            if duration:
                body = [p for p in path if p["tag"] == 2]
                size = body[-1]["y1"] - body[0]["y0"]
            result.append((path, size))
    return result


def sprite_spans(paths, now, clip=480):
    spans = []
    for path, size in paths:
        for p in path:
            if p["start"] <= now < p["end"]:
                y = p["y0"] + (p["y1"] - p["y0"]) * (now - p["start"]) / (p["end"] - p["start"])
                if min(clip, y) > max(0, y - size):
                    spans.append((max(0, y - size), min(clip, y)))
                break
    return sorted(spans)


class StableRenderingTests(unittest.TestCase):
    def test_sprite_model_matches_installed_stable_transforms(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/stable-movement.json").read_text())
        for sprite in fixture["sprites"]:
            kind, head, tail = sprite["kind"], sprite["head"], sprite["tail"]
            actual = movements(fixture["points"], tail if kind == "tail" else head,
                               20 if kind == "body" else 40, -20 if kind == "body" else 0,
                               tail - head if kind == "body" else 0)
            self.assertEqual(len(actual), len(sprite["transforms"]))
            for a, b in zip(actual, sprite["transforms"]):
                self.assertEqual((a["start"], a["end"], a["tag"]), (b["start"], b["end"], b["tag"]))
                for key in ("y0", "y1"):
                    self.assertAlmostEqual(a[key], b[key], delta=1e-5)

    def test_common_black_column_has_no_internal_white_seam_through_the_cut(self):
        for rows in (1, 3, 12, 24, 128):
            for speed in (1, 27, 40):
                for merged in (False, True):
                    with self.subTest(rows=rows, speed=speed, merged=merged):
                        gap = rows + 1
                        plan = compile_frames([["##"] * rows, ["#."] * rows],
                                              frame_times=[(2000, 2040), (2040 + gap, 2200)],
                                              scroll_speed=speed, fast_clear=True,
                                              merge_holds=merged, target_client="stable")
                        text = encode_osu(plan)
                        decoded, _ = decode(text)
                        points = [(t, beat / sv) for t, beat, sv in decoded] + [(10000, 500)]
                        objects = [[], []]
                        for line in text.split("[HitObjects]\n")[1].splitlines():
                            f = line.split(",")
                            head = int(f[2])
                            objects[int(f[0]) // 256].append((head, int(f[5].split(":")[0]) if f[3] == "128" else head))
                        common, outgoing = [sprites(points, notes, 480 / rows, speed) for notes in objects]
                        start, end = plan["frames"][0]["sweep_start_ms"], plan["frames"][1]["start_ms"]
                        for tick in range(start * 8, end * 8 + 1):
                            spans = sprite_spans(common, tick / 8, clip=479)
                            self.assertTrue(spans, tick / 8)
                            edge = 0
                            for top, bottom in spans:
                                self.assertLessEqual(top - edge, 1e-4, (tick / 8, spans))
                                edge = max(edge, bottom)
                            # Integer clipping can remove the outgoing hold head
                            # before its body reaches the bottom. This separate
                            # transient edge is not an internal moving seam.
                            self.assertGreaterEqual(edge, 479 - 240 / rows)
                        self.assertAlmostEqual(max(b for _, b in sprite_spans(common, end, 479)), 479, delta=1e-4)
                        for now in (end, end + .5, plan["end_ms"]):
                            self.assertFalse(sprite_spans(outgoing, now, clip=479), now)

    def test_integer_hold_clipping_still_has_a_transient_bottom_edge(self):
        plan = compile_frames([["##"] * 12, ["#."] * 12],
                              frame_times=[(2000, 2040), (2053, 2200)],
                              fast_clear=True, merge_holds=True, target_client="stable")
        decoded, _ = decode(encode_osu(plan))
        points = [(t, beat / sv) for t, beat, sv in decoded] + [(10000, 500)]
        objects = [(n["time_ms"], n["end_time_ms"]) for n in plan["notes"] if n["column"] == 0]
        paths = sprites(points, objects)
        at_head = sprite_spans(paths, objects[0][0], clip=479)
        self.assertLess(max(b for _, b in at_head), 479)
        self.assertEqual(max(b for _, b in sprite_spans(paths, objects[0][0] + .125, clip=479)), 479)

    def test_stable_bottom_mask_covers_the_stage_and_is_opaque_white(self):
        with tempfile.TemporaryDirectory() as directory:
            for ratio, label in SKIN_PROFILES.values():
                path = build_skin(Path(directory) / "stable.osk", rows=12, aspect_ratio=ratio,
                                  label=label, target_client="stable")
                with zipfile.ZipFile(path) as skin:
                    sections, _ = mania_sections(skin.read("skin.ini").decode())
                    for keys, section in sections.items():
                        width, height, pixels = png_pixels(skin.read(section["StageBottom"] + ".png"))
                        stage_width = sum(map(float, section["ColumnWidth"].split(",")))
                        self.assertGreaterEqual(width, stage_width - 1e-7)
                        self.assertLess(width - stage_width, 1 + 1e-7)
                        self.assertEqual(height, 1)
                        self.assertEqual(pixels, b"\xff" * width * height * 4)


if __name__ == "__main__":
    unittest.main()
