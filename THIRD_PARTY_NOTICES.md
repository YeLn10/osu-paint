# Third-party components

osu-paint's own source code and generated Pixel Film skin assets are provided under the [MIT License](LICENSE). This does not replace the licenses of dependencies included in a desktop build.

## Runtime components and source

| Component | Release baseline | License / source |
| --- | --- | --- |
| CPython | 3.11.9 | [PSF License and bundled notices](licenses/Python.txt); [source](https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz). |
| Tcl/Tk | Python installer's 8.6 runtime | [Tcl license](licenses/Tcl.txt), [Tk license](licenses/Tk.txt); [Tcl/Tk sources](https://www.tcl.tk/software/tcltk/download.html). |
| imageio-ffmpeg | 0.6.0 | [BSD-2-Clause](licenses/imageio-ffmpeg.txt); [source](https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0). Its FFmpeg executable has its own license. |
| pygame | 2.6.1 | [LGPL-2.1](licenses/pygame-LGPL.txt); [source and dependency build scripts](https://github.com/pygame/pygame/tree/2.6.1). pygame bundles SDL and supporting audio libraries; retain the notices shipped with its distribution. |
| Mutagen | 1.47.0 | [GPL-2.0-or-later](licenses/mutagen-GPL.txt); [source](https://github.com/quodlibet/mutagen/tree/release-1.47.0). |
| FFmpeg | 7.1, Gyan essentials Windows build | [GPL-3.0-or-later](licenses/FFmpeg-GPLv3.txt); [build distribution](https://github.com/GyanD/codexffmpeg/releases/tag/7.1), [corresponding FFmpeg source](https://github.com/FFmpeg/FFmpeg/tree/b08d7969c5), [build and library information](https://www.gyan.dev/ffmpeg/builds/). |
| FFmpeg (Linux x64) | 7.0.2-static, John Van Sickle build supplied by imageio-ffmpeg 0.6.0 | [GPL-3.0-or-later](licenses/FFmpeg-GPLv3.txt); [build distribution and source information](https://johnvansickle.com/ffmpeg/), [FFmpeg source](https://github.com/FFmpeg/FFmpeg/tree/n7.0.2). |

The Windows FFmpeg supplied by imageio-ffmpeg 0.6.0 reports `--enable-gpl --enable-version3`. Do not describe the complete executable bundle as containing only MIT-licensed code. FFmpeg is invoked as a separate process; its full version, build configuration and enabled libraries are recorded in [licenses/FFmpeg-build.txt](licenses/FFmpeg-build.txt).

The Linux FFmpeg also reports `--enable-gpl --enable-version3`; its license output, version and enabled libraries are recorded in [licenses/FFmpeg-linux-build.txt](licenses/FFmpeg-linux-build.txt). Linux builds use the Tcl/Tk 8.6 runtime available in the build environment and retain the same Tcl/Tk license notices.

The source release includes osu-paint's build and packaging scripts. Upstream source links above identify dependency versions for rebuilding or replacing components. Third-party copyright and license notices remain applicable when redistributing the bundle; the MIT license applies to osu-paint's own work.

## Packaging

PyInstaller 6.22.3 is used to build the Windows and Linux executables. Its bootloader is distributed under the [GPL with the PyInstaller bootloader exception](licenses/PyInstaller.txt); [source and license explanation](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3).

No osu! game files, assemblies, music, personal projects or private media are included. osu-paint is an independent tool and is not an official osu! project.
