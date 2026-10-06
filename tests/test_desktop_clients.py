"""Client selection must survive project and background-operation boundaries."""

import copy
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from osu_paint_desktop import PaintApp


class DesktopClientTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PaintApp(self.root)
        self.addCleanup(self.destroy_window)

    def destroy_window(self):
        self.root.update_idletasks()
        for job in self.root.tk.call("after", "info"):
            self.root.after_cancel(job)
        self.root.destroy()

    def test_both_projects_round_trip_and_unmarked_project_defaults_to_lazer(self):
        for client in ("stable", "lazer"):
            self.app.target_client.set(client)
            self.app._refresh_preview()
            saved = copy.deepcopy(self.app._project_data())
            self.assertEqual(saved["target_client"], client)
            self.app.target_client.set("lazer" if client == "stable" else "stable")
            self.app.load_project(saved)
            self.app._refresh_preview()
            self.assertEqual(self.app.plan["target_client"], client)
        saved.pop("target_client")
        self.app.target_client.set("stable")
        self.app.load_project(saved)
        self.app._refresh_preview()
        self.assertEqual(self.app.plan["target_client"], "lazer")

    def test_switching_client_preserves_video_and_audio_but_invalidates_alignment(self):
        self.app.video = dict(filename="synthetic.mp4", fps=10, width=7, height=6,
                              start_ms=2000, duration_ms=2000, refresh_hz=60,
                              requested_fps=10, requested_height=6)
        self.app.audio_data = b"OggS synthetic"
        frames, windows = copy.deepcopy((self.app.frames, self.app.frame_times))
        self.app.target_client.set("stable")
        self.app._refresh_preview()
        self.assertEqual((self.app.frames, self.app.frame_times), (frames, windows))
        self.assertEqual(self.app.audio_data, b"OggS synthetic")
        self.assertNotIn("refresh_hz", self.app.video)
        self.assertEqual(self.app.plan["target_client"], "stable")

    def test_unknown_project_client_fails_without_replacing_project(self):
        before = self.app._project_data()
        invalid = dict(before, target_client="unknown")
        with self.assertRaises(ValueError):
            self.app.load_project(invalid)
        self.assertEqual(self.app._project_data(), before)

    def test_export_keeps_clicked_client_while_editor_switches(self):
        entered, release = threading.Event(), threading.Event()
        captured = []
        def export(plan, output, **kwargs):
            captured.append(plan)
            entered.set()
            release.wait(3)
        with tempfile.TemporaryDirectory() as directory, patch("osu_paint_desktop.write_output", side_effect=export):
            self.app.target_client.set("stable")
            self.app.output_dir.set(directory)
            self.app.export()
            self.assertTrue(entered.wait(2))
            self.app.target_client.set("lazer")
            self.app._refresh_preview()
            release.set()
            deadline = time.monotonic() + 4
            while self.app.exporting and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            self.assertFalse(self.app.exporting)
        self.assertEqual(captured[0]["target_client"], "stable")
        self.assertEqual(self.app.plan["target_client"], "lazer")
