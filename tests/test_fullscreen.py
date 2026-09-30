"""Full-screen row geometry checked against the actual exported timing points."""

from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile

from osu_paint import compile_frames, encode_osu, make_preview, write_output
from osu_paint_skin import SKIN_PROFILES
from test_osu_paint import decode, position
from test_skin import mania_sections


class FullScreenTests(unittest.TestCase):
    def test_native_bottom_anchors_fill_rows_and_stay_unjudged_during_display(self):
        for height in (1, 3, 24, 128):
            plan = compile_frames([["#"] * height] * 3, 2000, 3000, fast_clear=True)
            points, _ = decode(encode_osu(plan))
            first, last = plan["frames"][0], plan["frames"][-1]
            ordered = sorted(plan["notes"], key=lambda n: n["row"])
            self.assertEqual(len(ordered), height)
            for note in ordered:
                bottom = (1 - position(points, note["time_ms"], plan["time_range_ms"])
                          + position(points, first["start_ms"], plan["time_range_ms"]))
                # lazer anchors its legacy texture at the bottom, not its centre.
                self.assertAlmostEqual(bottom - 1 / height, note["row"] / height, delta=2 / 768)
                self.assertGreater(note["time_ms"], last["end_ms"])

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable; HTML geometry check skipped")
    def test_html_pixels_tile_the_full_height_and_available_width(self):
        for keys in (1, 8, 18):
            for height in (3, 24):
                for merged in (False, True):
                    with self.subTest(keys=keys, height=height, holds=merged):
                        plan = compile_frames([["#" * keys] * height], 2000, 2400, fast_clear=True, merge_holds=merged)
                        script = make_preview(plan).split("<script>")[1].split("</script>")[0]
                        harness = r"""
const vm=require('node:vm'),assert=require('node:assert/strict'),rects=[];
const ctx={clearRect(){rects.length=0;},fillRect(x,y,w,h){if(this.fillStyle==='black')rects.push([x,y,w,h]);}};
const elements={view:{height:600,getContext:()=>ctx},seek:{},time:{},info:{},pattern:{},play:{}};
const sandbox=vm.createContext({document:{getElementById:id=>elements[id]},requestAnimationFrame(){},performance:{now:()=>0}});
vm.runInContext(SCRIPT,sandbox);
const width=960,lane=width/KEYS;
for(let col=0;col<KEYS;col++){
    const cells=rects.filter(r=>Math.abs(r[0]-col*lane)<1e-5).sort((a,b)=>a[1]-b[1]);
    assert.ok(cells.length);let edge=0;
    for(const [x,y,w,h] of cells){assert.ok(Math.abs(y-edge)<1e-5);assert.ok(Math.abs(w-lane)<1e-5);edge=y+h;}
    assert.ok(600-edge>=600/768-1e-5 && 600-edge<2*600/768);
}
""".replace("SCRIPT", json.dumps(script)).replace("KEYS", str(keys))
                        result = subprocess.run([shutil.which("node"), "-"], input=harness, text=True,
                                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rows_cover_the_entire_height_in_the_serialized_beatmap(self):
        client = "lazer"
        for height in (1, 3, 13, 24, 128):
            with self.subTest(client=client, height=height):
                plan = compile_frames([["#"] * height], 2000, 2400,
                                      fast_clear=True)
                points, _ = decode(encode_osu(plan))
                for note in plan["notes"]:
                    expected = (note["row"] + 1) / height - plan["drift_playfield_fraction"] - 1 / 768
                    actual = (1 - position(points, note["time_ms"], plan["time_range_ms"])
                              + position(points, 2000, plan["time_range_ms"]))
                    self.assertAlmostEqual(actual, expected, delta=1e-6)

    def test_exported_skins_match_the_actual_row_count(self):
        for height in (1, 3, 13, 24, 128):
            with self.subTest(height=height), tempfile.TemporaryDirectory() as directory:
                plan = compile_frames([["#"] * height], 2000, 2400,
                                      fast_clear=True)
                write_output(plan, Path(directory))
                for filename in SKIN_PROFILES:
                    with zipfile.ZipFile(Path(directory) / filename) as skin:
                        sections, _ = mania_sections(skin.read("skin.ini").decode())
                    for section in sections.values():
                        self.assertEqual(section["HitPosition"], "480")
                        self.assertAlmostEqual(float(section["WidthForNoteHeightScale"]) * height,
                                               480, delta=1e-7)


if __name__ == "__main__":
    unittest.main()
