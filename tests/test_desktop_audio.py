"""Independent audio import, editing, persistence and cancellation in real Tk."""

import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import wave
import zipfile

from osu_paint_audio import audio_duration_ms, render_audio
from osu_paint_desktop import PaintApp
from osu_paint_video import ImportCancelled
from test_desktop_video import video_result


class DesktopAudioTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "测试音轨.wav"
        with wave.open(str(self.source), "wb") as audio:
            audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 48000 * 3)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PaintApp(self.root)
        self.addCleanup(self.close)

    def close(self):
        self.app.import_cancel.set()
        self.root.update_idletasks()
        for job in self.root.tk.call("after", "info"):
            self.root.after_cancel(job)
        self.root.destroy()

    def wait_for(self, condition):
        deadline = time.monotonic() + 8
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(condition())

    def open_import(self):
        with patch("osu_paint_desktop.filedialog.askopenfilename", return_value=str(self.source)):
            self.app.import_audio()

    def test_real_import_edit_round_trip_preview_and_export_share_audio(self):
        frames = copy.deepcopy(self.app.frames)
        self.open_import()
        for key, value in dict(speed="2", start_ms="6000", trim_start_ms="500").items():
            self.app.audio_fields[key].set(value)
        self.app.audio_apply_button.invoke()
        self.wait_for(lambda: not self.app.importing)
        self.assertEqual(self.app.frames, frames)
        self.assertIsNone(self.app.video)
        self.assertAlmostEqual(audio_duration_ms(self.app.audio_data), 7250, delta=40)
        self.assertAlmostEqual(audio_duration_ms(self.app.audio_source), 3000, delta=20)
        self.assertGreaterEqual(self.app.seek_max, 7250 - 40)
        self.assertEqual(self.app.seek_min, 0)
        saved = json.loads(json.dumps(self.app._project_data()))
        self.assertEqual(saved["version"], 3)
        self.assertNotIn(str(self.source.parent), json.dumps(saved))
        self.app.load_text("#", keep_video=False)
        self.app.load_project(saved)
        self.app._refresh_preview()
        self.assertEqual(self.app._project_data(), saved)
        with patch.object(self.app.audio_player, "play") as play:
            self.app.toggle_play()
            play.assert_called_once_with(self.app.audio_data, 2000)
        self.app._stop()
        self.app.output_dir.set(str(Path(self.directory.name) / "output"))
        self.app.export()
        self.wait_for(lambda: not self.app.exporting)
        with zipfile.ZipFile(self.app.last_output / "pattern.osz") as archive:
            self.assertEqual(archive.read("audio.ogg"), self.app.audio_data)
        original = self.app.audio_source
        self.app.edit_audio()
        self.app.audio_fields["speed"].set("1")
        self.app.audio_apply_button.invoke()
        self.wait_for(lambda: not self.app.importing)
        self.assertEqual(self.app.audio_source, original)
        self.assertAlmostEqual(audio_duration_ms(self.app.audio_data), 8500, delta=40)

    def test_cancel_and_failure_keep_project_and_inputs_for_retry(self):
        before = copy.deepcopy(self.app._project_data())
        self.open_import()
        self.app.audio_fields["speed"].set("1.5")
        self.app.audio_cancel_button.invoke()
        self.assertEqual(self.app._project_data(), before)
        self.open_import()
        with patch("osu_paint_desktop.read_audio", side_effect=ValueError("无音轨")), \
                patch("osu_paint_desktop.messagebox.showerror") as error:
            self.app.audio_apply_button.invoke()
            self.wait_for(lambda: not self.app.importing)
            error.assert_called_once()
        self.assertEqual(self.app._project_data(), before)
        self.assertEqual(str(self.app.audio_apply_button["state"]), "normal")
        entered = threading.Event()

        def slow_read(path, *, cancel):
            entered.set()
            cancel.wait(3)
            raise ImportCancelled("cancelled")

        with patch("osu_paint_desktop.read_audio", side_effect=slow_read):
            self.app.audio_apply_button.invoke()
            self.assertTrue(entered.wait(2))
            self.app.audio_cancel_button.invoke()
            self.wait_for(lambda: not self.app.importing)
        self.assertEqual(self.app._project_data(), before)
        self.assertIsNone(self.app.import_dialog)

    def test_invalid_project_audio_is_atomic_and_removal_clears_source(self):
        self.open_import()
        self.app.audio_apply_button.invoke()
        self.wait_for(lambda: not self.app.importing)
        before = copy.deepcopy(self.app._project_data())
        for key, value in (("speed", 0), ("leading_ms", -1), ("source", "invalid"), ("duration_ms", float("nan"))):
            invalid = copy.deepcopy(before)
            invalid["audio_track"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.app.load_project(invalid)
            self.assertEqual(self.app._project_data(), before)
        self.app.edit_audio()
        self.app.audio_remove_button.invoke()
        self.assertIsNone(self.app.audio_data)
        self.assertIsNone(self.app.audio_source)
        self.assertNotIn("audio_track", self.app._project_data())
        self.assertTrue(self.source.exists())

    def test_video_audio_edit_removes_old_leading_offset_once(self):
        from osu_paint_audio import read_audio
        original = render_audio(read_audio(self.source), start_ms=2000)
        self.app._apply_video(video_result(original))
        frames, windows, video = copy.deepcopy((self.app.frames, self.app.frame_times, self.app.video))
        self.app.edit_audio()
        self.app.audio_fields["start_ms"].set("1000")
        self.app.audio_fields["speed"].set("2")
        self.app.audio_fields["trim_start_ms"].set("500")
        self.app.audio_apply_button.invoke()
        self.wait_for(lambda: not self.app.importing)
        self.assertAlmostEqual(audio_duration_ms(self.app.audio_data), 2250, delta=40)
        self.assertEqual((self.app.frames, self.app.frame_times, self.app.video), (frames, windows, video))
        saved = self.app._project_data()
        self.app.load_project(saved)
        self.assertEqual(self.app._project_data(), saved)

    def test_audio_controls_fit_and_dialog_does_not_change_project(self):
        self.root.deiconify()
        before = copy.deepcopy(self.app._project_data())
        self.open_import()
        self.root.update()
        dialog = self.app.import_dialog
        for widget in (*self.app.audio_inputs, self.app.audio_apply_button,
                       self.app.audio_cancel_button, self.app.audio_remove_button):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), dialog.winfo_rootx() + dialog.winfo_width())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), dialog.winfo_rooty() + dialog.winfo_height())
        self.assertEqual(self.app._project_data(), before)
        self.app.audio_cancel_button.invoke()
