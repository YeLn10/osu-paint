"""Bundle the verified Linux executable and tracked user documentation."""

import subprocess

from package_release import ROOT, write_tar


if __name__ == "__main__":
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    names = subprocess.check_output(
        ["git", "ls-files", "--", "README.md", "CHANGELOG.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
         "docs/usage.md", "docs/skin.md", "docs/desktop.png", "examples", "licenses"],
        cwd=ROOT, text=True, encoding="utf-8").splitlines()
    files = [(ROOT / "dist/osu-paint", "osu-paint")]
    files.extend((ROOT / name, name) for name in names)
    output = ROOT / "dist/osu-paint-linux-x64.tar.gz"
    write_tar(output, files, commit)
    print(f"Built: {output}")
