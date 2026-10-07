"""Layout and wording checks against real Tk widgets, without media files."""

import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from osu_paint_desktop import PaintApp


class DesktopLayoutTests(unittest.TestCase):
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

    def assert_fits(self, widget, window):
        self.assertTrue(widget.winfo_ismapped(), str(widget))
        x = widget.winfo_rootx() - window.winfo_rootx()
        y = widget.winfo_rooty() - window.winfo_rooty()
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + widget.winfo_width(), window.winfo_width())
        self.assertLessEqual(y + widget.winfo_height(), window.winfo_height())
        self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
        self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())

    def test_frame_list_counts_pixels_not_merged_notes(self):
        self.app.load_text("#\n#\n#\n")
        self.app._refresh_preview()
        self.assertEqual(len(self.app.plan["notes"]), 1)
        self.assertIn("3 亮格", self.app.frame_list.get(0))
        self.assertNotIn("音符", self.app.frame_list.get(0))

    def test_editor_and_settings_fit_at_minimum_and_default_sizes(self):
        self.root.deiconify()
        for width, height in ((960, 720), (1120, 820)):
            size = f"{round(width * self.app.scale)}x{round(height * self.app.scale)}"
            self.root.geometry(size)
            for client in ("lazer", "stable"):
                with self.subTest(size=size, client=client):
                    self.app.target_client.set(client)
                    self.app._refresh_preview()
                    self.root.update()
                    # Settings belong under the preview, not under the canvas.
                    self.assertGreater(self.app.entries["scroll_speed"].winfo_rootx(),
                                       self.app.canvas.winfo_rootx() + self.app.canvas.winfo_width())
                    for widget in (*self.app.entries.values(), self.app.client_choice,
                                   self.app.export_button, self.app.play_button,
                                   self.app.delete_button, self.app.folder_button):
                        self.assert_fits(widget, self.root)
                    self.assertGreater(self.app.canvas.winfo_height(), 260 * self.app.scale)

    def test_client_caveats_are_contextual_and_help_keeps_full_limits(self):
        self.app._refresh_preview()
        self.assertNotIn("11/13/15/17", self.app.playback_hint.get())
        self.app.load_text("#" * 11 + "\n")
        self.app._refresh_preview()
        self.assertIn("少一列", self.app.playback_hint.get())
        self.app.target_client.set("stable")
        self.app._refresh_preview()
        self.assertNotIn("少一列", self.app.playback_hint.get())
        self.app.load_text("#\n")
        self.app._refresh_preview()
        self.assertIn("100", self.app.playback_hint.get())
        with patch("osu_paint_desktop.messagebox.showinfo") as show:
            self.app.explain_timing()
        self.assertIn("11/13/15/17K", show.call_args.args[1])
        self.assertIn("零", show.call_args.args[1])

    def test_input_text_has_readable_contrast_in_all_states(self):
        style = ttk.Style(self.root)
        def luminance(colour):
            rgb = [value / 65535 for value in self.root.winfo_rgb(colour)]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
            return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            for state in ((), ("readonly",), ("disabled",)):
                with self.subTest(style=name, state=state):
                    levels = sorted(luminance(style.lookup(name, option, state))
                                    for option in ("foreground", "fieldbackground"))
                    self.assertGreaterEqual((levels[1] + .05) / (levels[0] + .05), 4.5)

    def test_video_dialog_keeps_inputs_and_actions_visible(self):
        self.root.deiconify()
        with patch("osu_paint_desktop.filedialog.askopenfilename", return_value="synthetic.mp4"):
            self.app.import_video()
        self.root.update()
        dialog = self.app.import_dialog
        self.assertLessEqual(dialog.winfo_height(), self.root.winfo_screenheight() - 80)
        for widget in (*self.app.video_inputs, self.app.video_start_button,
                       self.app.video_cancel_button, self.app.video_preview_button):
            self.assert_fits(widget, dialog)
        self.app.video_cancel_button.invoke()

    def test_text_dialog_has_scrollbar_cancel_and_a_safe_minimum_size(self):
        before = self.app._project_data()
        self.root.deiconify()
        self.app.edit_text()
        self.root.update()
        dialog = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
        minimum = dialog.minsize()
        self.assertGreaterEqual(minimum[0], round(420 * self.app.scale))
        self.assertGreaterEqual(minimum[1], round(320 * self.app.scale))
        dialog.geometry(f"{minimum[0]}x{minimum[1]}")
        self.root.update()
        children = dialog.winfo_children()
        editor = next(child for child in children if isinstance(child, tk.Text))
        scroll = next(child for child in children if isinstance(child, ttk.Scrollbar))
        editor.insert('end', '\n'.join(['#.'] * 500))
        self.root.update_idletasks()
        self.root.tk.call(scroll['command'], 'moveto', .9)
        self.assertGreater(editor.yview()[0], .8)
        buttons = [child for child in children if isinstance(child, ttk.Button)]
        for button in buttons:
            self.assert_fits(button, dialog)
        next(button for button in buttons if button['text'] == '取消').invoke()
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(self.app._project_data(), before)
