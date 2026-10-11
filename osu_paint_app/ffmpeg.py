"""Shared cancellable FFmpeg execution for audio and video imports."""

import subprocess


class ImportCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ImportCancelled("已取消视频导入，原项目未改变。")


def run_ffmpeg(arguments, cancel):
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        executable = get_ffmpeg_exe()
    except (ImportError, RuntimeError) as error:
        raise ValueError("缺少视频处理组件。源码运行请先执行 python -m pip install -r requirements.txt；"
                         "独立 EXE 请使用包含视频功能的新版。") from error
    command = [executable, "-nostdin", "-hide_banner", "-nostats", "-y", "-xerror", *arguments]
    check_cancel(cancel)
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        try:
            while True:
                check_cancel(cancel)
                try:
                    _, stderr = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            process.kill()
            process.communicate()
            raise
        check_cancel(cancel)
        log = stderr.decode("utf-8", errors="replace")
        if process.returncode:
            raise ValueError("视频或音轨处理失败（文件可能损坏或格式不支持）：\n" + log[-1600:])
        return log
