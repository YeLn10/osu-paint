"""Check the cost of editing and selecting a frame in a long local project."""
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from osu_paint_desktop import PaintApp


class CountedRow(str):
    scans = 0

    def count(self, *args):
        type(self).scans += 1
        return super().count(*args)


class DesktopFrameUpdateTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PaintApp(self.root)
        self.addCleanup(self.destroy_window)
        self.app.frames = [[CountedRow('#.........') for _ in range(24)] for _ in range(200)]
        self.app.frame_times = [[str(2000 + i * 100), str(2090 + i * 100)] for i in range(200)]
        self.app.plan = None
        self.app._update_editor()
        CountedRow.scans = 0

    def destroy_window(self):
        self.root.update_idletasks()
        for job in self.root.tk.call('after', 'info'):
            self.root.after_cancel(job)
        self.root.destroy()

    def test_selecting_frame_only_reads_the_selected_picture(self):
        self.app.frame_list.selection_clear(0, 'end')
        self.app.frame_list.selection_set(100)
        self.app.select_frame()
        self.assertEqual(self.app.selected, 100)
        self.assertEqual(self.app.frame_list.curselection(), (100,))
        self.assertLessEqual(CountedRow.scans, 24)
        self.assertFalse(self.app.dirty)

    def test_painting_updates_one_list_row_without_changing_other_frames(self):
        before = self.app.frame_list.get(1, 'end')
        with patch.object(self.app, '_cell_at', return_value=(0, 1)), \
                patch.object(self.app.frame_list, 'delete', wraps=self.app.frame_list.delete) as delete:
            self.app._paint(SimpleNamespace())
        self.assertNotIn((0, 'end'), [call.args for call in delete.call_args_list])
        self.assertLessEqual(CountedRow.scans, 24)
        self.assertEqual(self.app.frame_list.get(1, 'end'), before)
        self.assertIn('25 亮格', self.app.frame_list.get(0))
        self.assertTrue(self.app.dirty)

    def test_free_time_edit_updates_only_current_label(self):
        self.app.free_times_initialized = True
        self.app.timing_mode.set('自由模式')
        CountedRow.scans = 0
        before = self.app.frame_list.get(1, 'end')
        self.app.fields['start_ms'].set('2001')
        self.assertIn('2001', self.app.frame_list.get(0))
        self.assertEqual(self.app.frame_list.get(1, 'end'), before)
        self.assertLessEqual(CountedRow.scans, 24)

    def test_frame_insert_delete_and_mode_change_refresh_the_whole_list(self):
        self.app.add_frame(duplicate=True)
        self.assertEqual(self.app.frame_list.size(), 201)
        self.assertTrue(self.app.frame_list.get(200).startswith('  201 '))
        self.app.delete_frame()
        self.assertEqual(self.app.frame_list.size(), 200)
        self.app.free_times_initialized = True
        self.app.timing_mode.set('自由模式')
        self.assertIn('21900–21990 ms', self.app.frame_list.get(199))
        self.app.timing_mode.set('均分模式')
        self.assertNotIn('ms', self.app.frame_list.get(199))

    def test_painting_preserves_list_scroll_position(self):
        self.root.deiconify()
        self.root.update()
        self.app.frame_list.selection_clear(0, 'end')
        self.app.frame_list.selection_set(100)
        self.app.select_frame()
        self.app.frame_list.yview_moveto(.49)
        self.root.update_idletasks()
        before = self.app.frame_list.yview()
        with patch.object(self.app, '_cell_at', return_value=(0, 1)):
            self.app._paint(SimpleNamespace())
        self.root.update_idletasks()
        self.assertEqual(self.app.frame_list.yview(), before)
        self.assertEqual(self.app.frame_list.curselection(), (100,))
