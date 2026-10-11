import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import package_release as release


class ReleaseTests(unittest.TestCase):
    def test_archives_keep_user_files_and_resolve_moved_document_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contents = {
                "README.md": "[使用](docs/usage.md) [架构](docs/architecture.md#modules)\n",
                "CHANGELOG.md": "# Changes\n",
                "LICENSE": "license\n",
                "THIRD_PARTY_NOTICES.md": "[license](licenses/example.txt)\n",
                "docs/usage.md": "[首页](../README.md) [皮肤](skin.md#layout)\n",
                "docs/skin.md": "[使用](usage.md) [许可证](../LICENSE) "
                                "[研究](research/evidence.md#sampling) "
                                "[外部](https://example.com/skin?q=1#part) [本节](#layout)\n",
                "docs/desktop.png": "synthetic image",
                "docs/architecture.md": "# modules\n",
                "docs/research/evidence.md": "# sampling\n",
                "docs/releases/v0.1.0.md": "release notes\n",
                "docs/releases/v0.0.1.md": "old release\n",
                "examples/heart.txt": "#\n",
                "licenses/example.txt": "upstream license\n",
            }
            for name, content in contents.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            for index in range(10):
                (root / f"pixel-film-{index}.osk").write_bytes(b"synthetic skin")
            (root / "dist").mkdir()
            (root / "dist/osu-paint.exe").write_bytes(b"synthetic executable")
            (root / "output").mkdir()
            (root / "output/private-project.json").write_text("private sentinel")
            commit = "a" * 40

            def git_output(arguments, **kwargs):
                if arguments[1] == "rev-parse":
                    return commit + "\n"
                self.assertEqual(arguments[:2], ["git", "ls-files"])
                return "\n".join(name for name in contents
                                 if any(name.startswith(prefix + "/") for prefix in arguments[2:]))

            def git_run(arguments, **kwargs):
                if arguments[1] == "archive":
                    output = arguments[arguments.index("--output") + 1]
                    with zipfile.ZipFile(output, "w") as archive:
                        for name, content in contents.items():
                            archive.writestr("osu-paint-v0.1.0/" + name, content)

            with patch.object(release, "ROOT", root), \
                    patch.object(release, "verify_package", return_value={}), \
                    patch.object(release, "package_version", return_value="test"), \
                    patch("builtins.print"), \
                    patch.object(release.subprocess, "check_output", side_effect=git_output), \
                    patch.object(release.subprocess, "run", side_effect=git_run):
                output = release.package_release("v0.1.0")

            repository = f"https://github.com/YeLn10/osu-paint/blob/{commit}/"
            with zipfile.ZipFile(output / "osu-paint-v0.1.0-windows-x64.zip") as archive:
                names = set(archive.namelist())
                self.assertIn("docs/usage.md", names)
                self.assertIn("docs/skin.md", names)
                self.assertIn("licenses/example.txt", names)
                self.assertIn("examples/heart.txt", names)
                self.assertNotIn("docs/architecture.md", names)
                self.assertFalse(any(name.startswith(("docs/research/", "docs/releases/", "output/"))
                                     for name in names))
                readme = archive.read("README.md").decode("utf-8")
                self.assertIn("[使用](docs/usage.md)", readme)
                self.assertIn(f"[架构]({repository}docs/architecture.md#modules)", readme)
                self.assertEqual(archive.read("RELEASE_NOTES.md").decode("utf-8"), "release notes\n")
            with zipfile.ZipFile(output / "pixel-film-v0.1.0-skins.zip") as archive:
                self.assertEqual(sum(name.endswith(".osk") for name in archive.namelist()), 10)
                readme = archive.read("README.md").decode("utf-8")
                self.assertIn("[许可证](LICENSE)", readme)
                self.assertIn(f"[使用]({repository}docs/usage.md)", readme)
                self.assertIn(f"[研究]({repository}docs/research/evidence.md#sampling)", readme)
                self.assertIn("[外部](https://example.com/skin?q=1#part) [本节](#layout)", readme)
            with zipfile.ZipFile(output / "osu-paint-v0.1.0-source.zip") as archive:
                self.assertIn("osu-paint-v0.1.0/docs/research/evidence.md", archive.namelist())
            for line in (output / "SHA256SUMS.txt").read_text().splitlines():
                checksum, name = line.split("  ")
                self.assertEqual(checksum, hashlib.sha256((output / name).read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
