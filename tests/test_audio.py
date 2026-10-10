"""Exercise real Ogg decoding/seeking with SDL's silent test output device."""

import os
import subprocess
import time
import unittest
from unittest.mock import patch
from io import BytesIO
from pathlib import Path
import tempfile
import threading

from osu_paint_audio import AudioPreview


class AudioPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from imageio_ffmpeg import get_ffmpeg_exe
        cls.audio = subprocess.run(
            [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:sample_rate=48000:duration=1", "-c:a", "libvorbis", "-f", "ogg", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout

    def setUp(self):
        environment = patch.dict(os.environ, SDL_AUDIODRIVER="dummy")
        environment.start()
        self.addCleanup(environment.stop)
        self.player = AudioPreview()
        self.addCleanup(self.player.close)

    def test_real_ogg_seek_stop_resume_and_end(self):
        self.player.play(self.audio, 250)
        time.sleep(0.06)
        position = self.player.position_ms()
        self.assertGreaterEqual(position, 250)
        self.assertLess(position, 500)
        self.player.stop()
        self.assertIsNone(self.player.position_ms())
        self.player.play(self.audio, 800)
        self.assertGreaterEqual(self.player.position_ms(), 800)
        time.sleep(0.4)
        self.assertIsNone(self.player.position_ms())
        self.player.play(self.audio, 0)
        self.assertIsNotNone(self.player.position_ms())
        self.player.close()
        self.assertIsNone(self.player.position_ms())
        self.assertIsNone(self.player.stream)

    def test_seek_past_audio_end_and_silent_project(self):
        self.player.play(self.audio, 1500)
        self.assertIsNone(self.player.position_ms())
        self.player.play(self.audio, 0)
        self.player.play(None, 0)
        self.assertIsNone(self.player.position_ms())
        self.assertIsNone(self.player.stream)

    def test_bad_audio_can_be_replaced_by_valid_audio(self):
        with self.assertRaisesRegex(RuntimeError, "音乐播放失败"):
            self.player.play(b"OggS broken", 0)
        self.assertIsNone(self.player.position_ms())
        self.player.play(self.audio, 100)
        self.assertIsNotNone(self.player.position_ms())

    def test_unavailable_device_reports_error_and_can_retry(self):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
        with patch.object(pygame.mixer, "init", side_effect=pygame.error("no device")):
            with self.assertRaisesRegex(RuntimeError, "音频输出设备"):
                self.player.play(self.audio, 0)
        self.player.play(self.audio, 0)
        self.assertIsNotNone(self.player.position_ms())

    def test_import_and_render_speed_trim_and_timeline_offset(self):
        from mutagen.oggvorbis import OggVorbis
        from osu_paint_audio import read_audio, render_audio
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.ogg"
            source.write_bytes(self.audio)
            original = read_audio(source)
            rendered = render_audio(original, speed=2, start_ms=300, trim_start_ms=200)
        self.assertAlmostEqual(OggVorbis(BytesIO(original)).info.length, 1, delta=.02)
        self.assertAlmostEqual(OggVorbis(BytesIO(rendered)).info.length, .7, delta=.04)
        from imageio_ffmpeg import get_ffmpeg_exe
        pcm = subprocess.run([get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                              "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1"],
                             input=rendered, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        import array
        samples = array.array("h", pcm)
        self.assertLess(max(abs(v) for v in samples[:12000]), 10)
        self.assertGreater(max(abs(v) for v in samples[16000:20000]), 500)

    def test_audio_settings_reject_invalid_values_and_allow_cancel(self):
        from osu_paint_audio import render_audio
        from osu_paint_video import ImportCancelled
        for options in ({"speed": 0}, {"speed": float("nan")}, {"start_ms": -1},
                        {"trim_start_ms": 1000}, {"trim_start_ms": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                render_audio(self.audio, **options)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ImportCancelled):
            render_audio(self.audio, cancel=cancel)


if __name__ == "__main__":
    unittest.main()
