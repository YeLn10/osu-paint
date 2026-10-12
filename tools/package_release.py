"""Create explicitly selected release assets without including local media."""

import argparse
import hashlib
from importlib.metadata import version as package_version
import io
import json
from pathlib import Path
import platform
import posixpath
import re
import subprocess
import tarfile
from urllib.parse import quote, unquote, urlsplit
import zipfile

from verify_package import ROOT, verify_package


def document_bytes(source, paths, commit):
    def rewrite_link(match):
        # Keep bundled links local; pin omitted references to the same source revision.
        link = urlsplit(match[2])
        if link.scheme or link.netloc or not link.path:
            return match[0]
        target = (source.parent / unquote(link.path)).resolve()
        if target in paths:
            destination = posixpath.relpath(paths[target], posixpath.dirname(paths[source.resolve()]) or ".")
        else:
            destination = (f"https://github.com/YeLn10/osu-paint/blob/{commit}/"
                           + quote(target.relative_to(ROOT.resolve()).as_posix()))
        destination += ("?" + link.query if link.query else "")
        destination += ("#" + link.fragment if link.fragment else "")
        return match[1] + destination + match[3]

    markdown = re.sub(r"(\[[^\]\n]*\]\()([^\s)]+)(\))", rewrite_link,
                      source.read_text(encoding="utf-8"))
    return markdown.encode("utf-8")


def write_tar(output, files, commit):
    paths = {source.resolve(): name for source, name in files}
    with tarfile.open(output, "w:gz") as archive:
        for source, name in files:
            content = (document_bytes(source, paths, commit) if source.suffix == ".md"
                       else source.read_bytes())
            info = archive.gettarinfo(str(source), arcname=name)
            info.size = len(content)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if name == "osu-paint":
                info.mode = 0o755
            archive.addfile(info, io.BytesIO(content))


def write_zip(output, files, commit):
    paths = {source.resolve(): name for source, name in files}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source, name in files:
            if source.suffix != ".md":
                archive.write(source, name)
                continue

            archive.writestr(name, document_bytes(source, paths, commit))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"Invalid release archive: {output.name}")


def package_release(version):
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise ValueError("Version must use vMAJOR.MINOR.PATCH, for example v0.1.0.")
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        subprocess.run(["git", *arguments], cwd=ROOT, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    notes = ROOT / "docs/releases" / f"{version}.md"
    if not notes.is_file():
        raise ValueError(f"Missing release notes: {notes.relative_to(ROOT)}")
    executable = ROOT / "dist/osu-paint.exe"
    verification = verify_package(executable)
    output = ROOT / "dist/release" / version
    output.mkdir(parents=True, exist_ok=True)
    project_files = ["LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "CHANGELOG.md",
                     "docs/usage.md", "docs/skin.md", "docs/desktop.png"]
    project_files.extend(subprocess.check_output(["git", "ls-files", "examples", "licenses"],
                                                 cwd=ROOT, text=True, encoding="utf-8").splitlines())
    files = [(executable, "osu-paint.exe")]
    files.extend((ROOT / name, name) for name in project_files)
    files.append((ROOT / "docs/releases" / f"{version}.md", "RELEASE_NOTES.md"))
    application = output / f"osu-paint-{version}-windows-x64.zip"
    write_zip(application, files, commit)
    skins = sorted(ROOT.glob("pixel-film*.osk"))
    if len(skins) != 10:
        raise ValueError(f"Expected ten delivery skins, found {len(skins)}.")
    skin_archive = output / f"pixel-film-{version}-skins.zip"
    write_zip(skin_archive, [(path, path.name) for path in skins] +
              [(ROOT / "docs/skin.md", "README.md"), (ROOT / "LICENSE", "LICENSE")], commit)
    source_archive = output / f"osu-paint-{version}-source.zip"
    subprocess.run(["git", "archive", "--format=zip", f"--prefix=osu-paint-{version}/",
                    "--output", str(source_archive), "HEAD"], cwd=ROOT, check=True)
    info = dict(version=version, commit=commit, python=platform.python_version(),
                platform="windows-x64", dependencies={name: package_version(name) for name in
                ("pyinstaller", "imageio-ffmpeg", "pygame", "mutagen")}, **verification)
    manifest = output / "build-info.json"
    manifest.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    assets = [application, skin_archive, source_archive, manifest]
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in assets)
    (output / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8")
    (output / "release-notes.md").write_text(notes.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps(dict(directory=str(output), commit=commit, assets=[path.name for path in assets]), indent=2))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    package_release(parser.parse_args().version)
