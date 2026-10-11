"""Portable project format checks, independent of Tk and media decoders."""

import base64
import copy
import json
from pathlib import Path
import unittest

from osu_paint_app.project import Project


def project_data(version=1, *, video=False):
    data = dict(format="osu-paint", version=version, target_client="stable",
                frames=[["#.", ".#"], ["..", ".."]],
                frame_times=[["2000", "2300"], ["2500", "2800"]], timing_mode="自由模式",
                settings=dict(start_ms="2000", end_ms="2800", transition_ms="12", scroll_speed="27"),
                fast_clear=True, merge_holds=True)
    if version >= 2:
        data.update(video=dict(filename="synthetic.mkv", fps=2, width=2, height=2,
                               start_ms=2000, duration_ms=1000) if video else None,
                    audio=base64.b64encode(b"OggS synthetic output").decode("ascii"))
    if version == 3:
        data["audio_track"] = dict(filename="synthetic.ogg", speed=1.5, start_ms=2000,
                                   trim_start_ms=100, leading_ms=0, duration_ms=3000,
                                   source=base64.b64encode(b"OggS synthetic source").decode("ascii"))
    return data


class ProjectTests(unittest.TestCase):
    def test_all_project_versions_round_trip_without_media_files(self):
        for version, video in ((1, False), (2, True), (3, False), (3, True)):
            with self.subTest(version=version, video=video):
                data = project_data(version, video=video)
                before = copy.deepcopy(data)
                project = Project.from_data(data)
                self.assertEqual(json.loads(json.dumps(project.to_data())), before)
                self.assertEqual(data, before)
                if version >= 2:
                    self.assertEqual(project.audio_data, b"OggS synthetic output")
                if version == 3:
                    self.assertEqual(project.audio_source, b"OggS synthetic source")

    def test_legacy_example_keeps_single_notes_and_default_client(self):
        path = Path(__file__).resolve().parents[1] / "examples/free.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        project = Project.from_data(data)
        self.assertFalse(project.merge_holds)
        self.assertEqual(project.target_client, "lazer")
        self.assertEqual(project.to_data(), dict(data, merge_holds=False, target_client="lazer"))

    def test_blank_drafts_and_unfinished_timing_fields_remain_editable(self):
        data = project_data()
        data["frames"] = [["..", ".."], ["..", ".."]]
        data["frame_times"][0] = ["", "unfinished"]
        data["settings"]["transition_ms"] = ""
        self.assertEqual(Project.from_data(data).to_data(), data)

    def test_silent_video_does_not_acquire_an_audio_track(self):
        data = project_data(2, video=True)
        data["audio"] = None
        project = Project.from_data(data)
        self.assertIsNone(project.audio_data)
        self.assertEqual(project.to_data(), data)

    def test_obsolete_video_controls_are_ignored_without_mutating_input(self):
        data = project_data(2, video=True)
        data["video"].update(game_fps=60, frame_fps=60, refresh_phase_ms=3)
        before = copy.deepcopy(data)
        project = Project.from_data(data)
        self.assertEqual(project.video, project_data(2, video=True)["video"])
        self.assertEqual(data, before)

    def test_invalid_projects_are_rejected_without_mutating_input(self):
        for key, value in (("format", "report"), ("version", 4), ("target_client", "other"),
                           ("merge_holds", "true"), ("frames", [["#"]]),
                           ("frame_times", []), ("timing_mode", "other"),
                           ("fast_clear", "true"), ("audio", "invalid base64"),
                           ("audio_track", {})):
            data = project_data(3, video=True)
            data[key] = value
            before = copy.deepcopy(data)
            with self.subTest(key=key), self.assertRaises(ValueError):
                Project.from_data(data)
            self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
