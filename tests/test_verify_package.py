"""Package verification must cover extracted modules as well as root entries."""

import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from tools import verify_package


class PackageVerificationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.sources = {
            "osu_paint": "osu_paint.py",
            "osu_paint_desktop": "osu_paint_desktop.py",
            "osu_paint_audio": "osu_paint_audio.py",
            "osu_paint_video": "osu_paint_video.py",
            "osu_paint_skin": "osu_paint_skin.py",
            "osu_paint_app": "osu_paint_app/__init__.py",
            "osu_paint_app.desktop": "osu_paint_app/desktop.py",
            "osu_paint_app.project": "osu_paint_app/project.py",
        }
        self.bundled = {}
        for name, filename in self.sources.items():
            source = self.root / filename
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("VALUE = 1\n", encoding="utf-8")
            self.bundled[name] = compile(source.read_bytes(), filename, "exec")
        self.executable = self.root / "osu-paint.exe"
        self.executable.write_bytes(b"synthetic executable")
        self.pyz = Mock(toc={**self.bundled, "mutagen.oggvorbis": None})
        self.pyz.extract.side_effect = self.bundled.__getitem__
        archive = Mock(toc={"imageio_ffmpeg/ffmpeg.exe": None, "pygame/mixer.pyd": None})
        archive.open_embedded_archive.return_value = self.pyz
        self.archive = archive

    def verify(self):
        readers = ModuleType("PyInstaller.archive.readers")
        readers.CArchiveReader = Mock(return_value=self.archive)
        with patch.object(verify_package, "ROOT", self.root), \
                patch.dict(sys.modules, {"PyInstaller.archive.readers": readers}):
            return verify_package.verify_package(self.executable)

    def test_verifies_every_root_and_package_module(self):
        result = self.verify()
        self.assertEqual(set(result["modules_match_source"]), set(self.sources))
        self.assertTrue(result["media_components_included"])
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_stale_extracted_module_is_rejected(self):
        (self.root / self.sources["osu_paint_app.project"]).write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "osu_paint_app.project differs"):
            self.verify()

    def test_missing_extracted_module_is_rejected(self):
        del self.pyz.toc["osu_paint_app.project"]
        with self.assertRaisesRegex(ValueError, "osu_paint_app.project.*missing"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
