"""Shared application modules must stay usable without desktop/media dependencies."""

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ApplicationImportTests(unittest.TestCase):
    def test_project_and_compiler_work_with_only_the_standard_library(self):
        script = '''
import json
import sys
from pathlib import Path
from osu_paint import compile_frames, parse_frames
from osu_paint_app.project import Project
from osu_paint_app.ffmpeg import ImportCancelled, check_cancel

project = Project.from_data(json.loads(Path("examples/free.json").read_text(encoding="utf-8")))
assert project.to_data()["version"] == 1
plan = compile_frames(parse_frames("#"), 2000, 4000)
assert plan["notes"]
assert not {"tkinter", "pygame", "imageio_ffmpeg", "mutagen"}.intersection(sys.modules)
'''
        result = subprocess.run([sys.executable, "-S", "-c", script], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_audio_module_does_not_depend_on_video_or_compiler(self):
        script = '''
import sys
import osu_paint_audio
from osu_paint_app.ffmpeg import check_cancel
osu_paint_audio.validate_audio_settings(speed=1, start_ms=0, trim_start_ms=0)
assert not {"osu_paint_video", "osu_paint", "tkinter"}.intersection(sys.modules)
'''
        result = subprocess.run([sys.executable, "-S", "-c", script], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
