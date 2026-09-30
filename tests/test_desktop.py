"""Desktop interactions and export checks against the real Tk widgets."""

from pathlib import Path
import json
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from osu_paint import compile_frames, parse_frames
from osu_paint_desktop import HEART, OUTPUT_FILES, PaintApp


class DesktopTests(unittest.TestCase):
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

    def wait_for_export(self):
        deadline = time.monotonic() + 5
        while self.app.exporting and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app.exporting, "Export did not finish")

    def test_initial_preview_reuses_compiler(self):
        self.assertEqual(self.app.plan, compile_frames([HEART], 2000, 4000, fast_clear=True))
        self.assertFalse(self.app.dirty)
        self.assertEqual(str(self.app.export_button["state"]), "normal")

    def test_paint_drag_and_erase(self):
        with patch.object(self.app, "_grid_geometry", return_value=(10, 10, 40)):
            self.app._begin_stroke(SimpleNamespace(x=30, y=30, num=1))
            self.assertEqual(self.app.frames[0][0], "###.##.")
            self.app._paint(SimpleNamespace(x=150, y=30))
            self.assertEqual(self.app.frames[0][0], "######.")
            self.app._begin_stroke(SimpleNamespace(x=30, y=30, num=3))
            self.assertEqual(self.app.frames[0][0], ".#####.")
            self.app._paint(SimpleNamespace(x=-10, y=-10))
            self.assertEqual(self.app.frames[0][0], ".#####.")
        self.assertTrue(self.app.dirty)
        self.app._refresh_preview()
        self.assertEqual(self.app.plan["pattern"], self.app.frames[0])

    def test_free_mode_keeps_each_frame_times_and_uniform_settings(self):
        self.app.add_frame(duplicate=True)
        # Switch before the pending preview runs: initialise from the latest uniform parameters.
        self.app.fields["end_ms"].set("5000")
        self.app.timing_mode.set("自由模式")
        self.app.fields["start_ms"].set("3500")
        self.app.fields["end_ms"].set("6000")
        self.app.frame_list.selection_clear(0, "end")
        self.app.frame_list.selection_set(0)
        self.app.select_frame()
        self.app.fields["start_ms"].set("1000")
        self.app.fields["end_ms"].set("2000")
        self.app._refresh_preview()
        self.assertEqual([(f["start_ms"], f["end_ms"]) for f in self.app.plan["frames"]],
                         [(1000, 2000), (3500, 6000)])
        self.app.timing_mode.set("均分模式")
        self.assertEqual(self.app.fields["end_ms"].get(), "5000")
        self.app.timing_mode.set("自由模式")
        self.assertEqual(self.app.fields["start_ms"].get(), "1000")
        self.app.fields["end_ms"].set("4000")
        self.app._refresh_preview()
        self.assertIsNone(self.app.plan)
        self.assertIn("间隔不足", self.app.status.get())
        self.assertEqual(str(self.app.export_button["state"]), "disabled")

    def test_free_project_save_open_and_export_preserve_timing(self):
        self.app.add_frame(duplicate=True)
        self.app.timing_mode.set("自由模式")
        self.app.fields["start_ms"].set("4500")
        self.app.fields["end_ms"].set("5200")
        expected = self.app._project_data()
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "自由项目.json"
            with patch("osu_paint_desktop.filedialog.asksaveasfilename", return_value=str(filename)):
                self.app.save_pattern()
            self.assertFalse(self.app.dirty)
            self.assertEqual(json.loads(filename.read_text(encoding="utf-8")), expected)
            self.app.load_project(json.loads(filename.read_text(encoding="utf-8")))
            self.assertEqual(self.app._project_data(), expected)
            self.app.output_dir.set(str(Path(directory) / "export"))
            self.app.export()
            self.wait_for_export()
            report = json.loads((self.app.last_output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["timing_mode"], "free")
            self.assertEqual(report["frames"][1]["start_ms"], 4500)
            self.assertEqual(report["frames"][1]["end_ms"], 5200)
            before = self.app._project_data()
            with self.assertRaises(ValueError):
                self.app.load_project({"format": "osu-paint", "version": 1})
            self.assertEqual(self.app._project_data(), before)

    def test_free_frame_delete_and_text_edits_keep_remaining_times(self):
        self.app.timing_mode.set("自由模式")
        self.app.fields["end_ms"].set("2600")
        self.app.add_frame(duplicate=True)
        self.app.fields["start_ms"].set("4000")
        self.app.fields["end_ms"].set("4800")
        self.app.load_text(self.app._text() + "---\n" + "\n".join(HEART))
        self.assertEqual(self.app.frame_times[:2], [["2000", "2600"], ["4000", "4800"]])
        self.app.delete_frame()
        self.assertEqual(self.app.frame_times[0], ["4000", "4800"])
        self.assertEqual(self.app.fields["start_ms"].get(), "4000")

    def test_preview_does_not_hide_notes_at_judgement_time(self):
        self.root.deiconify()
        self.root.update()
        self.app.fast_clear.set(False)
        self.app._timing_options_changed()
        self.app._refresh_preview()
        self.app.seek_time.set(self.app.plan["notes"][-1]["time_ms"] + 0.1)
        self.app._draw_preview()
        self.assertTrue(self.app.preview.find_withtag("note"), "Show below-line travel, don't hide it at judgement")
        self.app.fast_clear.set(True)
        self.app._timing_options_changed()
        self.app._refresh_preview()
        self.app.seek_time.set(self.app.plan["end_ms"] + 1)
        self.app._draw_preview()
        self.assertFalse(self.app.preview.find_withtag("note"))

    def test_stable_repeated_picture_stays_visible_in_the_preview(self):
        self.root.deiconify()
        self.root.update()
        picture = ["."] * 11 + ["#"] + ["."] * 12
        self.app.frames = [picture] * 2
        plan = compile_frames(self.app.frames, frame_times=[(2000, 2052), (2100, 2200)],
                              fast_clear=True, target_client="stable")
        self.app._refresh_preview(compiled_plan=plan)
        for now in (2000, 2051, 2075, 2099, 2100, 2199):
            self.app.seek_time.set(now)
            self.app._draw_preview()
            self.assertEqual(len(self.app.preview.find_withtag("note")), 1)
            self.assertIn("帧", self.app.time_label.get())
            self.assertNotIn("换帧", self.app.time_label.get())

    def test_stable_changing_picture_uses_exact_rows_in_the_preview_at_ten_fps(self):
        self.root.deiconify()
        self.root.update()
        self.app.frames = [["#."] * 24, [".#"] * 24]
        plan = compile_frames(self.app.frames, frame_times=[(2000, 2075), (2100, 2200)],
                              fast_clear=True, target_client="stable")
        self.app._refresh_preview(compiled_plan=plan)
        stage_h = (self.app.preview.winfo_height() - 34 * self.app.scale) * 658 / 768
        for now in (2000, 2075, 2100, 2200):
            self.app.seek_time.set(now)
            self.app._draw_preview()
            items = self.app.preview.find_withtag("note")
            self.assertEqual(len(items), 24)
            heights = sorted((sum(self.app.preview.coords(item)[1::2]) / 2 - 10 * self.app.scale) / stage_h
                             for item in items)
            for row, y in enumerate(heights):
                self.assertAlmostEqual(y, .2 + (row + .5) * .6 / 24,
                                       delta=plan["drift_playfield_fraction"] + 1e-6)

    def test_duplicate_is_independent_and_delete_selects_valid_frame(self):
        self.app.add_frame(duplicate=True)
        self.assertEqual(len(self.app.frames), 2)
        self.assertEqual(self.app.selected, 1)
        self.app.frames[1][0] = "......."
        self.assertEqual(self.app.frames[0][0], HEART[0])
        self.app.delete_frame()
        self.assertEqual(self.app.selected, 0)
        self.assertEqual(self.app.frames, [HEART])
        self.app.delete_frame()
        self.assertEqual(len(self.app.frames), 1)

    def test_empty_frame_is_editable_but_not_exportable(self):
        self.app.add_frame()
        self.assertEqual(self.app.frames[1], ["......."] * 6)
        self.app._refresh_preview()
        self.assertIsNone(self.app.plan)
        self.assertEqual(str(self.app.export_button["state"]), "disabled")
        self.app.frames[1][0] = "#......"
        self.app._changed()
        self.app._refresh_preview()
        self.assertEqual(len(self.app.plan["frames"]), 2)

    def test_text_round_trip_and_invalid_input_preserves_drawing(self):
        text = "#.\n.#\n---\n.#\n#.\n"
        self.app.load_text(text)
        self.assertEqual(self.app._text(), text)
        with self.assertRaises(ValueError):
            self.app.load_text("wrong")
        self.assertEqual(self.app.frames, parse_frames(text))
        self.app._refresh_preview()
        self.assertEqual(self.app.plan["keys"], 2)

    def test_text_dialog_keeps_apply_button_visible_and_applies_edits(self):
        self.root.deiconify()
        self.app.edit_text()
        self.root.update()
        dialog = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
        editor = next(child for child in dialog.winfo_children() if isinstance(child, tk.Text))
        button = next(child for child in dialog.winfo_children() if child.winfo_class() == "TButton")
        self.assertTrue(button.winfo_ismapped(), "Apply button must remain visible below the editor")
        self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
        self.assertLessEqual(button.winfo_y() + button.winfo_height(), dialog.winfo_height())
        editor.delete("1.0", "end")
        editor.insert("1.0", "#.\n.#\n---\n.#\n#.\n")
        button.invoke()
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(self.app.frames, [["#.", ".#"], [".#", "#."]])

    def test_invalid_values_disable_stale_preview_and_export(self):
        for field, value in [("start_ms", ""), ("end_ms", "nan"),
                             ("scroll_speed", "41"), ("transition_ms", "0")]:
            with self.subTest(field=field):
                original = self.app.fields[field].get()
                self.app.fields[field].set(value)
                self.assertIsNone(self.app.plan)
                self.app._refresh_preview()
                self.assertIsNone(self.app.plan)
                self.assertEqual(str(self.app.export_button["state"]), "disabled")
                self.app.fields[field].set(original)
                self.app._refresh_preview()
                self.assertIsNotNone(self.app.plan)

    def test_frame_selection_updates_preview_time(self):
        self.app.add_frame(duplicate=True)
        self.app._refresh_preview()
        self.app.frame_list.selection_clear(0, "end")
        self.app.frame_list.selection_set(0)
        self.app.select_frame()
        self.assertEqual(self.app.selected, 0)
        self.assertEqual(self.app.seek_time.get(), self.app.plan["frames"][0]["start_ms"])
        self.assertIn("第 1 / 2 帧", self.app.time_label.get())

    def test_playback_advances_stops_and_restarts(self):
        self.app.toggle_play()
        start = self.app.seek_time.get()
        self.app.last_tick -= 0.1
        self.root.after_cancel(self.app.tick_job)
        self.app._tick()
        self.assertGreater(self.app.seek_time.get(), start)
        self.assertTrue(self.app.playing)
        self.app.last_tick -= 10
        self.root.after_cancel(self.app.tick_job)
        self.app._tick()
        self.assertEqual(self.app.seek_time.get(), self.app.seek_max)
        self.assertFalse(self.app.playing)
        self.app.toggle_play()
        self.assertEqual(self.app.seek_time.get(), self.app.seek_min)
        self.app._seek_changed("2000")
        self.assertFalse(self.app.playing)

    def test_export_uses_latest_parameters_and_creates_all_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "中文 输出"
            self.app.output_dir.set(str(output))
            self.app.fields["end_ms"].set("4500")
            self.app.export()
            self.wait_for_export()
            self.assertEqual(self.app.plan["end_ms"], 4500)
            self.assertEqual({p.name for p in output.iterdir()}, set(OUTPUT_FILES))
            with zipfile.ZipFile(output / "pattern.osz") as archive:
                self.assertIsNone(archive.testzip())
            self.assertEqual(self.app.last_output, output.resolve())
            self.assertEqual(str(self.app.folder_button["state"]), "normal")

    def test_overwrite_cancel_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "report.json").write_text("keep", encoding="utf-8")
            self.app.output_dir.set(directory)
            with patch("osu_paint_desktop.messagebox.askyesno", return_value=False) as confirm:
                self.app.export()
            confirm.assert_called_once()
            self.assertFalse(self.app.exporting)
            self.assertEqual((output / "report.json").read_text(encoding="utf-8"), "keep")

    def test_export_error_restores_controls_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-a-directory"
            output.write_text("keep", encoding="utf-8")
            self.app.output_dir.set(str(output))
            with patch("osu_paint_desktop.messagebox.showerror") as report:
                self.app.export()
                self.wait_for_export()
            report.assert_called_once()
            self.assertIn("导出失败", self.app.status.get())
            self.assertIsNone(self.app.last_output)
            self.assertEqual(str(self.app.export_button["state"]), "normal")

    def test_empty_output_is_rejected(self):
        self.app.output_dir.set("   ")
        self.app.export()
        self.assertFalse(self.app.exporting)
        self.assertIn("请选择导出目录", self.app.status.get())

    def test_pattern_save_open_and_cancelled_open(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "绘图.txt"
            self.app.dirty = True
            with patch("osu_paint_desktop.filedialog.asksaveasfilename", return_value=str(filename)):
                self.app.save_pattern()
            self.assertFalse(self.app.dirty)
            self.assertEqual(parse_frames(filename.read_text(encoding="utf-8")), [HEART])
            filename.write_text("\ufeff#.\n.#\n", encoding="utf-8")
            with patch("osu_paint_desktop.filedialog.askopenfilename", return_value=str(filename)):
                self.app.open_pattern()
            self.assertEqual(self.app.frames, [["#.", ".#"]])
            self.app.dirty = True
            with patch("osu_paint_desktop.messagebox.askyesno", return_value=False), patch("osu_paint_desktop.filedialog.askopenfilename") as choose:
                self.app.open_pattern()
            choose.assert_not_called()

    def test_close_is_blocked_during_export_or_unsaved_changes(self):
        with patch.object(self.root, "destroy") as destroy:
            self.app.exporting = True
            with patch("osu_paint_desktop.messagebox.showinfo"):
                self.app.close()
            self.app.exporting = False
            self.app.dirty = True
            with patch("osu_paint_desktop.messagebox.askyesno", return_value=False):
                self.app.close()
            destroy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
