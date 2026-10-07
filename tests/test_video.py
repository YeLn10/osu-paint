"""Synthetic, local FFmpeg regressions; no user media or network access."""

from array import array
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

from osu_paint import encode_osu, write_output
from osu_paint_video import (ImportCancelled, _run_ffmpeg, import_video, preview_video_frame,
                             resolve_video_options, validate_video_options)


class VideoValidationTests(unittest.TestCase):


    def test_rejects_invalid_fps_dimensions_and_offset(self):
        defaults = dict(fps=10, width=10, height=24, start_ms=2000, scroll_speed=27)
        for field, value in (("fps", 0), ("fps", -1), ("fps", math.nan), ("fps", math.inf),
                             ("fps", 61), ("width", 0), ("width", 19), ("width", 2.5),
                             ("height", 0), ("height", 129), ("height", 1.5),
                             ("start_ms", 0), ("start_ms", math.inf), ("scroll_speed", 0),
                             ("threshold", -1), ("threshold", 256), ("brightness", math.nan),
                             ("brightness", 256), ("contrast", 0), ("contrast", math.inf),
                             ("invert", "true"), ("fit", "invalid")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_video_options(**dict(defaults, **{field: value}))
        with self.assertRaises(ValueError):
            validate_video_options(**dict(defaults, fps=60, scroll_speed=1))

    def test_all_supported_column_counts_use_ordinary_video_options(self):
        for width in range(1, 19):
            client = "lazer"
            with self.subTest(width=width, client=client):
                validate_video_options(fps=4, width=width, height=4, start_ms=2000,
                                       scroll_speed=27)

    def test_missing_dependency_has_actionable_error(self):
        with patch.dict(sys.modules, {"imageio_ffmpeg": None}), self.assertRaisesRegex(ValueError, "requirements.txt"):
            _run_ffmpeg([], None)


@unittest.skipUnless(imageio_ffmpeg, "Install requirements.txt for real FFmpeg tests")
class VideoImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.exe = imageio_ffmpeg.get_ffmpeg_exe()
        cls.source = cls.directory / "带 音乐的视频.mkv"
        cls.silent = cls.directory / "silent.mkv"
        cls.black = cls.directory / "black.mkv"
        cls.variable = cls.directory / "variable.mkv"
        # 4 frames at 4 FPS: black, top-left, bottom-right, white.
        raw = bytearray()
        for frame in range(4):
            for y in range(16):
                for x in range(16):
                    light = frame == 3 or (frame == 1 and x < 8 and y < 8) or (frame == 2 and x >= 8 and y >= 8)
                    raw.extend(bytes([255 if light else 0]) * 3)
        cls.ffmpeg(["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "16x16", "-r", "4", "-i", "pipe:0",
                    "-itsoffset", "0.25", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.75",
                    "-c:v", "ffv1", "-c:a", "pcm_s16le", str(cls.source)], input=bytes(raw))
        cls.ffmpeg(["-i", str(cls.source), "-an", "-c:v", "copy", str(cls.silent)])
        cls.ffmpeg(["-f", "lavfi", "-i", "color=black:size=16x16:rate=4:duration=1",
                    "-c:v", "ffv1", str(cls.black)])

        cls.ffmpeg(["-i", str(cls.silent), "-vf", "setpts=if(eq(N\\,0)\\,0\\,if(eq(N\\,1)\\,0.1/TB\\,if(eq(N\\,2)\\,0.6/TB\\,1.1/TB)))",
                    "-fps_mode", "vfr", "-enc_time_base", "1:1000", "-c:v", "ffv1", str(cls.variable)])

    @classmethod
    def ffmpeg(cls, args, **kwargs):
        return subprocess.run([cls.exe, "-hide_banner", "-loglevel", "error", "-y", *args],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kwargs).stdout

    def load(self, path=None, **kwargs):
        options = dict(fps=4, width=2, height=2, start_ms=2000, scroll_speed=27)
        options.update(kwargs)
        return import_video(path or self.source, **options)

    def test_video_frames_fps_resolution_and_black_frame(self):
        result = self.load()
        plan = result["plan"]
        self.assertEqual([f["pattern"] for f in plan["frames"]],
                         [["..", ".."], ["#.", ".."], ["..", ".#"], ["##", "##"]])
        self.assertEqual([f["start_ms"] for f in plan["frames"]], [2000, 2250, 2500, 2750])
        self.assertEqual(plan["end_ms"], 3000)
        self.assertEqual(result["video"]["fps"], 4)
        self.assertNotIn(str(self.directory), str(result["video"]))
        smaller = self.load(fps=2, width=3, height=5)
        self.assertEqual(len(smaller["plan"]["frames"]), 2)
        self.assertTrue(all(len(f["pattern"]) == 5 and len(f["pattern"][0]) == 3
                            for f in smaller["plan"]["frames"]))

    def test_high_column_import_and_selected_frame_preview_preserve_audio(self):
        for width in (11, 12, 14, 16, 17, 18):
            options = dict(fps=4, width=width, height=4)
            with self.subTest(width=width):
                result = self.load(**options)
                plan = result["plan"]
                self.assertEqual(plan["keys"], width)
                self.assertEqual(len(plan["frames"]), 4)
                self.assertEqual([f["start_ms"] for f in plan["frames"]], [2000, 2250, 2500, 2750])
                self.assertTrue(result["audio"].startswith(b"OggS"))
                self.assertNotIn("reference_animation", result["video"])
                self.assertTrue(all("end_ms" not in n for n in plan["notes"]))
                preview = preview_video_frame(self.source, frame_index=2, **options)
                self.assertEqual(preview["frame"], plan["frames"][2]["pattern"])
                self.assertEqual(preview["frame"][:2], ["." * width] * 2)
                self.assertTrue(all(row.startswith("." * (width // 2)) and row.endswith("#" * (width // 2))
                                    for row in preview["frame"][2:]))

    def test_high_column_cli_exports_only_short_notes_and_audio(self):
        output = self.directory / "high-column-cli"
        script = Path(__file__).resolve().parents[1] / "osu_paint.py"
        process = subprocess.run([sys.executable, str(script), str(self.source), "--video",
                                  "--fps", "4", "--width", "16", "--height", "4",
                                  "--start-ms", "2000", "--output", str(output)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors="replace"))
        with zipfile.ZipFile(output / "pattern.osz") as archive:
            self.assertEqual(set(archive.namelist()), {"pattern.osu", "audio.ogg"})
            exported = archive.read("pattern.osu").decode("utf-8")
            self.assertIn("CircleSize: 16", exported)
            notes = exported.split("[HitObjects]", 1)[1].strip().splitlines()
            self.assertTrue(notes)
            self.assertTrue(all(line.split(",")[3] == "1" for line in notes))
            self.assertTrue(archive.read("audio.ogg").startswith(b"OggS"))
        with zipfile.ZipFile(output / "pixel-film.osk") as skin:
            self.assertIsNone(skin.testzip())
            self.assertIn("Keys: 16", skin.read("skin.ini").decode())


    def test_automatic_fractional_refresh_and_holds_share_real_preview_and_preserve_audio(self):
        client = "lazer"
        with self.subTest(client=client):
            options = dict(fps=20, width=2, height=4, refresh_hz=60000 / 1001,
                           merge_holds=True)
            base = self.load(**options)
            repeated = self.load(**options)
            # Ogg stream serials/CRCs vary across encodes; compare the decoded signal.
            pcm_args = ["-i", "pipe:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"]
            self.assertEqual(self.ffmpeg(pcm_args, input=repeated["audio"]),
                             self.ffmpeg(pcm_args, input=base["audio"]))
            self.assertEqual(repeated["video"]["start_ms"], 2000)
            self.assertEqual(base["plan"], repeated["plan"])
            preview = preview_video_frame(self.source, **options, frame_index=10)
            self.assertEqual(preview["frame"], repeated["plan"]["frames"][10]["pattern"])
            self.assertTrue(any("end_time_ms" in n for n in repeated["plan"]["notes"]))
            self.assertTrue(repeated["audio"].startswith(b"OggS"))


    def test_both_client_phase_schedules_leave_the_decoded_audio_unchanged(self):
        pcm_args = ["-i", "pipe:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"]
        original = self.load(start_ms=2000.6)
        expected = self.ffmpeg(pcm_args, input=original["audio"])
        for client in ("lazer", "stable"):
            with self.subTest(client=client):
                result = self.load(start_ms=2000.6, target_client=client, refresh_hz=60, merge_holds=True)
                self.assertEqual(result["video"]["start_ms"], 2000.6)
                self.assertEqual(self.ffmpeg(pcm_args, input=result["audio"]), expected)

    def test_audio_includes_import_offset_and_original_stream_delay(self):
        result = self.load()
        output = self.directory / "export"
        write_output(result["plan"], output, audio_data=result["audio"])
        with zipfile.ZipFile(output / "pattern.osz") as archive:
            self.assertEqual(set(archive.namelist()), {"pattern.osu", "audio.ogg"})
            self.assertTrue(archive.read("audio.ogg").startswith(b"OggS"))
            self.assertIn(b"AudioFilename: audio.ogg", archive.read("pattern.osu"))
        pcm = self.ffmpeg(["-i", str(output / "audio.ogg"), "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"])
        samples = array("f", pcm)
        self.assertAlmostEqual(len(samples) / 48000, 3, delta=0.04)
        self.assertLess(max(abs(x) for x in samples[:int(2.20 * 48000)]), 0.001)
        self.assertGreater(max(abs(x) for x in samples[int(2.30 * 48000):int(2.90 * 48000)]), 0.02)

    def test_silent_video_still_imports_and_all_black_video_is_rejected(self):
        result = self.load(self.silent)
        self.assertIsNone(result["audio"])
        self.assertEqual(len(result["plan"]["frames"]), 4)
        with self.assertRaisesRegex(ValueError, "至少|全黑|亮"):
            self.load(self.black)

    def test_fractional_fps_is_not_rounded_to_an_integer(self):
        result = self.load(fps=2.5)
        self.assertEqual(result["video"]["fps"], 2.5)
        self.assertEqual([f["start_ms"] for f in result["plan"]["frames"]], [2000, 2400, 2800])

    def test_variable_rate_source_uses_timestamps_not_frame_indices(self):
        result = self.load(self.variable)
        frames = result["plan"]["frames"]
        # This FFV1 fixture has no per-frame durations. Its final hold is inferred by
        # FFmpeg; verify the unambiguous timestamp changes rather than inventing an EOF.
        self.assertEqual([f["pattern"] for f in frames[:6]],
                         [["..", ".."], ["#.", ".."], ["#.", ".."],
                          ["..", ".#"], ["..", ".#"], ["##", "##"]])
        self.assertTrue(all(f["pattern"] == ["##", "##"] for f in frames[6:]))
        self.assertEqual([f["start_ms"] for f in frames],
                         [2000 + i * 250 for i in range(len(frames))])

    def test_active_cancellation_terminates_ffmpeg_process(self):
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        real_popen = subprocess.Popen
        processes = []

        def spawn(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            processes.append(process)
            return process

        timer.start()
        try:
            with patch("osu_paint_video.subprocess.Popen", side_effect=spawn), self.assertRaises(ImportCancelled):
                _run_ffmpeg(["-re", "-stream_loop", "-1", "-i", str(self.silent), "-f", "null", "-"], cancel)
        finally:
            timer.cancel()
            timer.join()
        self.assertTrue(processes)
        self.assertTrue(all(process.poll() is not None for process in processes))

    def test_cli_imports_video_with_custom_options_and_audio(self):
        output = self.directory / "CLI 输出"
        script = Path(__file__).resolve().parents[1] / "osu_paint.py"
        process = subprocess.run([sys.executable, str(script), str(self.source), "--video", "--fps", "2.5",
                                  "--width", "3", "--height", "5", "--start-ms", "2000", "--output", str(output)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors="replace"))
        import json
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["video"]["fps"], 2.5)
        self.assertEqual(report["keys"], 3)
        with zipfile.ZipFile(output / "pattern.osz") as archive:
            self.assertIn("audio.ogg", archive.namelist())

    def test_cancel_invalid_file_and_frame_budget(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(ImportCancelled):
            self.load(cancel=cancelled)
        invalid = self.directory / "invalid.mp4"
        invalid.write_text("not a video", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.load(invalid)
        with self.assertRaises((ValueError, OSError)):
            self.load(self.directory / "missing.mp4")
        with patch("osu_paint_video.MAX_VIDEO_FRAMES", 2), self.assertRaisesRegex(ValueError, "帧|上限"):
            self.load()

    def test_preview_matches_import_for_selected_vfr_frames_and_filters(self):
        for fit in ("stretch", "contain", "cover"):
            options = dict(fps=4, width=3, height=5, threshold=100, brightness=15,
                           contrast=1.5, invert=True, fit=fit)
            imported = self.load(self.variable, **options)
            for index in (0, 2, 4):
                preview = preview_video_frame(self.variable, frame_index=index, **options)
                self.assertEqual(preview["frame"], imported["plan"]["frames"][index]["pattern"])
                self.assertTrue(preview["source_ppm"].startswith(b"P6"))
                self.assertEqual(preview["time_ms"], index * 250)

    def test_adjustments_recover_dim_shapes_and_invert_background(self):
        source = self.directory / "dim.mkv"
        pixels = bytes([80] * 8 + [120] * 8) * 16
        self.ffmpeg(["-f", "rawvideo", "-pix_fmt", "gray", "-s", "16x16", "-r", "1", "-i", "pipe:0",
                     "-c:v", "ffv1", str(source)], input=pixels)
        default = preview_video_frame(source, fps=1, width=2, height=2)
        self.assertEqual(default["frame"], ["..", ".."])
        for changes in (dict(threshold=100), dict(brightness=30), dict(brightness=50, contrast=2)):
            adjusted = preview_video_frame(source, fps=1, width=2, height=2, **changes)
            self.assertEqual(adjusted["frame"], [".#", ".#"])
            self.assertEqual(self.load(source, fps=1, **changes)["plan"]["pattern"], adjusted["frame"])
        inverse = preview_video_frame(source, fps=1, width=2, height=2, threshold=100, invert=True)
        self.assertEqual(inverse["frame"], ["#.", "#."])

    def test_preview_range_validation_and_cancellation(self):
        for index in (-1, 100, 20000):
            with self.assertRaises(ValueError):
                preview_video_frame(self.source, frame_index=index, fps=4)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ImportCancelled):
            preview_video_frame(self.source, cancel=cancel)


if __name__ == "__main__":
    unittest.main()
