"""Video UI, persistence and immutable export snapshots using real Tk widgets."""

import base64
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import zipfile

from osu_paint import compile_frames, write_output
from osu_paint_desktop import PaintApp
from osu_paint_video import ImportCancelled


def video_result(audio=b"OggS test audio"):
    frames = [["..", ".."], ["#.", ".."], ["..", ".#"]]
    windows = [(2000, 2249.425), (2250, 2499.425), (2500, 2750)]
    plan = compile_frames(frames, frame_times=windows, fast_clear=True,
                          allow_empty_frames=True, anchor_reference=True)
    video = {"filename": "local-video.mp4", "fps": 4, "width": 2, "height": 2,
             "start_ms": 2000, "duration_ms": 750}
    plan["video"] = video.copy()
    return {"plan": plan, "audio": audio, "video": video}


class DesktopVideoTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PaintApp(self.root)
        self.addCleanup(self.destroy_window)

    def destroy_window(self):
        self.app.import_cancel.set()
        self.root.update_idletasks()
        for job in self.root.tk.call("after", "info"):
            self.root.after_cancel(job)
        self.root.destroy()

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(condition(), "Background task did not finish")

    def open_video_dialog(self):
        with patch("osu_paint_desktop.filedialog.askopenfilename", return_value="local-video.mp4"), \
                patch("osu_paint_desktop.messagebox.askyesno", return_value=True):
            self.app.import_video()
        self.root.update_idletasks()

    def test_dialog_passes_custom_options_and_applies_audio_and_frames(self):
        result = video_result()
        self.open_video_dialog()
        self.assertIsNotNone(self.app.import_dialog)
        for key, value in dict(fps="2.5", width="2", height="2", start_ms="2500").items():
            self.app.video_fields[key].set(value)
        with patch("osu_paint_desktop.read_video", return_value=result) as importer:
            self.app.video_start_button.invoke()
            self.wait_for(lambda: not self.app.importing)
        self.assertEqual({key: importer.call_args.kwargs[key] for key in ("fps", "width", "height", "start_ms")},
                         dict(fps=2.5, width=2, height=2, start_ms=2500))
        self.assertEqual(self.app.frames[0], ["..", ".."])
        self.assertEqual(self.app.audio_data, result["audio"])
        self.assertEqual(self.app.timing_mode.get(), "自由模式")
        self.assertTrue(self.app.fast_clear.get())
        self.assertTrue(self.app.dirty)
        self.assertIsNone(self.app.import_dialog)
        self.assertEqual(self.app.plan, result["plan"])

    def test_bad_options_and_import_failure_preserve_existing_project(self):
        before = copy.deepcopy(self.app._project_data())
        self.open_video_dialog()
        self.app.video_fields["width"].set("11")
        with patch("osu_paint_desktop.messagebox.showerror"), patch("osu_paint_desktop.read_video") as importer:
            self.app.video_start_button.invoke()
            importer.assert_not_called()
        self.app.video_fields["width"].set("10")
        with patch("osu_paint_desktop.messagebox.showerror") as report, \
                patch("osu_paint_desktop.read_video", side_effect=ValueError("invalid video")):
            self.app.video_start_button.invoke()
            self.wait_for(lambda: not self.app.importing)
        report.assert_called_once()
        self.assertEqual(self.app._project_data(), before)
        self.assertEqual(str(self.app.video_start_button["state"]), "normal")
        self.app.video_cancel_button.invoke()
        self.assertIsNone(self.app.import_dialog)

    def test_cancel_reaps_worker_and_preserves_original_and_close_guard(self):
        before = copy.deepcopy(self.app._project_data())
        started = threading.Event()

        def read(*args, cancel, **kwargs):
            started.set()
            cancel.wait(4)
            raise ImportCancelled("已取消视频导入，原项目未改变。")

        self.open_video_dialog()
        with patch("osu_paint_desktop.read_video", side_effect=read):
            self.app.video_start_button.invoke()
            self.assertTrue(started.wait(2))
            with patch.object(self.root, "destroy") as destroy, patch("osu_paint_desktop.messagebox.showinfo"):
                self.app.close()
                destroy.assert_not_called()
            self.app.video_cancel_button.invoke()
            self.wait_for(lambda: not self.app.importing)
        self.assertEqual(self.app._project_data(), before)
        self.assertIsNone(self.app.import_dialog)

    def test_cancel_wins_race_with_already_completed_worker(self):
        before = copy.deepcopy(self.app._project_data())
        self.open_video_dialog()
        with patch("osu_paint_desktop.read_video", return_value=video_result()):
            self.app.video_start_button.invoke()
            # Wait for the worker without dispatching the Tk completion handler.
            deadline = time.monotonic() + 2
            while self.app.import_results.empty() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.app.video_cancel_button.invoke()
            self.wait_for(lambda: not self.app.importing)
        self.assertEqual(self.app._project_data(), before)

    def test_json_project_embeds_music_and_reopens_without_source_video(self):
        result = video_result()
        self.app._apply_video(result)
        expected = copy.deepcopy(self.app._project_data())
        self.assertEqual(expected["version"], 2)
        self.assertEqual(base64.b64decode(expected["audio"]), result["audio"])
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "视频项目.json"
            with patch("osu_paint_desktop.filedialog.asksaveasfilename", return_value=str(project)):
                self.app.save_pattern()
            self.assertFalse(self.app.dirty)
            self.app.load_text("#", keep_video=False)
            self.app.load_project(json.loads(project.read_text(encoding="utf-8")))
            self.app._refresh_preview()
            self.assertEqual(self.app._project_data(), expected)
            self.assertIsNotNone(self.app.plan)
            self.app.output_dir.set(str(Path(directory) / "output"))
            self.app.export()
            self.wait_for(lambda: not self.app.exporting)
            with zipfile.ZipFile(self.app.last_output / "pattern.osz") as archive:
                self.assertEqual(archive.read("audio.ogg"), result["audio"])
                self.assertNotIn("silence.wav", archive.namelist())

    def test_invalid_video_project_is_atomic_and_old_projects_clear_media(self):
        old = copy.deepcopy(self.app._project_data())
        self.app._apply_video(video_result())
        valid = copy.deepcopy(self.app._project_data())
        for key, value in (("audio", "invalid base64"), ("audio", base64.b64encode(b"not ogg").decode()),
                           ("video", {}), ("video", dict(valid["video"], width=3))):
            invalid = copy.deepcopy(valid)
            invalid[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.app.load_project(invalid)
            self.assertEqual(self.app._project_data(), valid)
        self.app.load_project(old)
        self.assertIsNone(self.app.video)
        self.assertIsNone(self.app.audio_data)
        self.assertEqual(self.app._project_data(), old)

    def test_new_and_open_text_clear_old_audio_but_edit_text_keeps_it(self):
        self.app._apply_video(video_result())
        self.app.load_text("..\n..\n---\n.#\n..")
        self.assertIsNotNone(self.app.audio_data)
        with patch("osu_paint_desktop.messagebox.askyesno", return_value=True), \
                patch("osu_paint_desktop.simpledialog.askinteger", side_effect=[2, 2]):
            self.app.new_pattern()
        self.assertIsNone(self.app.audio_data)
        self.assertIsNone(self.app.video)
        self.app._apply_video(video_result())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pattern.txt"
            source.write_text("#", encoding="utf-8")
            with patch("osu_paint_desktop.messagebox.askyesno", return_value=True), \
                    patch("osu_paint_desktop.filedialog.askopenfilename", return_value=str(source)):
                self.app.open_pattern()
        self.assertIsNone(self.app.audio_data)
        self.assertIsNone(self.app.video)

    def test_resized_video_text_round_trips_with_audio(self):
        result = video_result()
        self.app._apply_video(result)
        self.app.load_text("#..\n...\n..#")
        saved = copy.deepcopy(self.app._project_data())
        self.app.load_text("#", keep_video=False)
        self.app.load_project(saved)
        self.app._refresh_preview()
        self.assertEqual(self.app.frames, [["#..", "...", "..#"]])
        self.assertEqual(self.app.audio_data, result["audio"])
        self.assertIsNotNone(self.app.plan)
        self.assertEqual(self.app._project_data(), saved)

    def test_export_snapshot_keeps_original_audio_when_editor_changes(self):
        result = video_result()
        self.app._apply_video(result)
        release = threading.Event()

        def write(plan, output, *, audio_data=None):
            release.wait(4)
            write_output(plan, output, audio_data=audio_data)

        with tempfile.TemporaryDirectory() as directory, patch("osu_paint_desktop.write_output", side_effect=write):
            self.app.output_dir.set(directory)
            self.app.export()
            self.app._apply_video(video_result(b"OggS replacement"))
            release.set()
            self.wait_for(lambda: not self.app.exporting)
            with zipfile.ZipFile(Path(directory) / "pattern.osz") as archive:
                self.assertEqual(archive.read("audio.ogg"), result["audio"])

    def test_existing_video_audio_requires_overwrite_confirmation(self):
        self.app._apply_video(video_result())
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.ogg"
            audio.write_bytes(b"keep")
            self.app.output_dir.set(directory)
            with patch("osu_paint_desktop.messagebox.askyesno", return_value=False) as confirm:
                self.app.export()
            confirm.assert_called_once()
            self.assertFalse(self.app.exporting)
            self.assertEqual(audio.read_bytes(), b"keep")

    def test_text_save_does_not_mark_video_project_as_fully_saved(self):
        self.app._apply_video(video_result())
        self.app.timing_mode.set("均分模式")
        with tempfile.TemporaryDirectory() as directory, \
                patch("osu_paint_desktop.filedialog.asksaveasfilename", return_value=str(Path(directory) / "frames.txt")):
            self.app.save_pattern()
        self.assertTrue(self.app.dirty)
        self.assertIsNotNone(self.app.audio_data)

    def test_preview_culls_notes_instead_of_scanning_entire_video(self):
        class IndexedOnly(list):
            def __iter__(self):
                raise AssertionError("Preview must not scan all video notes")

        self.app._apply_video(video_result())
        self.app.plan["notes"] = IndexedOnly(self.app.plan["notes"])
        self.app._draw_preview()


if __name__ == "__main__":
    unittest.main()
