"""Import local video as timestamped note frames and a portable Ogg audio track."""

import math
from pathlib import Path
import re
import subprocess
import tempfile

from osu_paint import compile_frames, minimum_transition_ms, number


MAX_VIDEO_FRAMES = 20000
MAX_VIDEO_PIXELS = 2000000


class ImportCancelled(Exception):
    pass


def validate_video_options(*, fps, width, height, start_ms, scroll_speed):
    if not math.isfinite(fps) or not 0 < fps <= 60:
        raise ValueError("视频 FPS 须大于 0 且不超过 60，可以填写小数。")
    if not isinstance(width, int) or not 1 <= width <= 10:
        raise ValueError("视频宽度须为 1–10 列；每列对应一个 mania 按键列。")
    if not isinstance(height, int) or not 1 <= height <= 128:
        raise ValueError("视频高度须为 1–128 行。")
    transition = minimum_transition_ms(scroll_speed)
    if not math.isfinite(start_ms) or start_ms - transition < 100:
        raise ValueError("视频开始时间须为有限数值，并在进场前保留至少 100 ms。")
    if 1000 / fps <= transition * 3:
        raise ValueError("当前滚速不足以容纳此 FPS 的展示和切帧；请降低 FPS 或提高 lazer 滚速。")
    return transition


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ImportCancelled("已取消视频导入，原项目未改变。")


def _run_ffmpeg(arguments, cancel):
    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        executable = get_ffmpeg_exe()
    except (ImportError, RuntimeError) as error:
        raise ValueError("缺少视频处理组件。源码运行请先执行 python -m pip install -r requirements.txt；"
                         "独立 EXE 请使用包含视频功能的新版。") from error
    command = [executable, "-nostdin", "-hide_banner", "-nostats", "-y", "-xerror", *arguments]
    _check_cancel(cancel)
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
        try:
            while True:
                _check_cancel(cancel)
                try:
                    _, stderr = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            process.kill()
            process.communicate()
            raise
        _check_cancel(cancel)
        log = stderr.decode("utf-8", errors="replace")
        if process.returncode:
            raise ValueError("视频或音轨处理失败（文件可能损坏或格式不支持）：\n" + log[-1600:])
        return log


def import_video(path, *, fps=10, width=10, height=24, start_ms=2000, scroll_speed=27,
                 progress=None, cancel=None):
    transition = validate_video_options(fps=fps, width=width, height=height,
                                        start_ms=start_ms, scroll_speed=scroll_speed)
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("请选择存在的本地视频文件。")
    _check_cancel(cancel)

    def report(message):
        _check_cancel(cancel)
        if progress is not None:
            progress(message)

    frame_size = width * height
    limit = min(MAX_VIDEO_FRAMES, MAX_VIDEO_PIXELS // frame_size)
    with tempfile.TemporaryDirectory(prefix="osu-paint-video-") as directory:
        directory = Path(directory)
        raw = directory / "frames.raw"
        report("正在按指定 FPS 缩放和抽帧…（可取消）")
        # Timestamp-based resampling handles variable-rate video without cumulative drift.
        # A tiny grayscale raw file bounds memory and lets cancellation reap FFmpeg reliably.
        filters = f"fps=fps={number(fps)}:start_time=0:round=up,scale={width}:{height}:flags=area,format=gray"
        log = _run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:v:0",
                           "-vf", filters, "-frames:v", str(limit + 1), "-an", "-f", "rawvideo", str(raw)], cancel)
        pixels = raw.read_bytes()
        count, remainder = divmod(len(pixels), frame_size)
        if remainder or not count:
            raise ValueError("视频未能解码出完整画面。")
        if count > limit:
            raise ValueError(f"视频超过当前分辨率的 {limit} 帧上限；请降低 FPS、分辨率或使用较短视频。")
        frames = []
        for index in range(count):
            if index % 250 == 0:
                report(f"正在生成音符画面：{index + 1} / {count} 帧…")
            block = pixels[index * frame_size:(index + 1) * frame_size]
            frames.append(["".join("#" if value >= 128 else "." for value in block[row:row + width])
                           for row in range(0, frame_size, width)])
        period = 1000 / fps
        windows = [(start_ms + i * period,
                    start_ms + (i + 1) * period - (transition if i < count - 1 else 0))
                   for i in range(count)]
        report("正在编译谱面与视频时间轴…")
        plan = compile_frames(frames, scroll_speed=scroll_speed, frame_times=windows,
                              fast_clear=True, allow_empty_frames=True, anchor_reference=True)
        audio_data = None
        if re.search(r"^\s*Stream #0:\d+.*Audio:", log, re.MULTILINE):
            report("正在提取音乐并对齐视频开始时间…（可取消）")
            audio = directory / "audio.ogg"
            # Keep the input's relative stream timestamps, including delayed audio starts.
            # Strip original metadata; the exported project never needs the private source path.
            delay_samples = round(start_ms * 48)
            _run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:a:0", "-vn",
                         "-af", f"aresample=48000:async=1:first_pts=0,adelay={delay_samples}S:all=1",
                         "-ac", "2", "-c:a", "libvorbis", "-q:a", "5",
                         "-map_metadata", "-1", "-map_chapters", "-1", str(audio)], cancel)
            audio_data = audio.read_bytes()
        _check_cancel(cancel)
    video = {"filename": path.name, "fps": fps, "width": width, "height": height,
             "start_ms": start_ms, "duration_ms": count * period}
    plan["video"] = video.copy()
    return {"plan": plan, "audio": audio_data, "video": video}
