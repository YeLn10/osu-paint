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


def validate_video_options(*, fps, width, height, start_ms, scroll_speed, target_client="lazer",
                           threshold=128, brightness=0, contrast=1, invert=False, fit="stretch",
                           reference_animation=False):
    if not math.isfinite(fps) or not 0 < fps <= 60:
        raise ValueError("视频 FPS 须大于 0 且不超过 60，可以填写小数。")
    if not isinstance(width, int) or not (1 <= width <= 10 or
                                         reference_animation and width in (12, 14, 16, 18)):
        raise ValueError("视频宽度须为 1–10 列；参考动画也支持 12、14、16、18 列。")
    if not isinstance(height, int) or not 1 <= height <= 128:
        raise ValueError("视频高度须为 1–128 行。")
    if not math.isfinite(threshold) or not 0 <= threshold <= 255:
        raise ValueError("黑白阈值须在 0–255 之间。")
    if not math.isfinite(brightness) or not -255 <= brightness <= 255:
        raise ValueError("亮度须在 -255–255 之间。")
    if not math.isfinite(contrast) or not 0 < contrast <= 5:
        raise ValueError("对比度须大于 0 且不超过 5。")
    if not isinstance(invert, bool) or fit not in ("stretch", "contain", "cover"):
        raise ValueError("反转或缩放方式无效。")
    if not isinstance(reference_animation, bool):
        raise ValueError("参考动画选项必须为布尔值。")
    if reference_animation:
        if target_client != "stable" or fps != 30 or height > 31:
            raise ValueError("参考动画需要 stable、30 FPS，最多 31 行；推荐 16×12。")
        if not math.isfinite(scroll_speed) or not 1 <= scroll_speed <= 40:
            raise ValueError("游戏滚速须在 1–40 之间。")
    transition = height if reference_animation else minimum_transition_ms(scroll_speed, target_client, height)
    if not math.isfinite(start_ms) or start_ms - transition < 100:
        raise ValueError("视频开始时间须为有限数值，并在进场前保留至少 100 ms。")
    if not reference_animation and target_client == "stable" and math.floor(1000 / fps) < 2 * transition + 2:
        maximum_fps = math.floor(1000000 / (2 * transition + 2)) / 1000
        raise ValueError(f"stable 的 {height} 行画面至少需要 {2 * transition + 2:g} ms / 帧；"
                         f"FPS 须不超过 {maximum_fps:.3f}，或降低行数。")
    if target_client == "lazer" and 1000 / fps <= transition * 3:
        raise ValueError("当前滚速不足以容纳此 FPS 的展示和切帧；请降低 FPS 或提高 lazer 滚速。")
    return transition


def _scale_filter(width, height, fit):
    scale = f"scale={width}:{height}:flags=area"
    if fit == "contain":
        scale += f":force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    elif fit == "cover":
        scale += f":force_original_aspect_ratio=increase,crop={width}:{height}"
    return scale + ",format=gray"


def _pixel_frame(block, width, *, threshold=128, brightness=0, contrast=1, invert=False):
    pixels = ["#" if (((value - 128) * contrast + 128 + brightness >= threshold) != invert)
              else "." for value in block]
    return ["".join(pixels[row:row + width]) for row in range(0, len(pixels), width)]


def preview_video_frame(path, *, frame_index=0, fps=10, width=10, height=24, start_ms=2000,
                        scroll_speed=27, target_client="lazer", threshold=128, brightness=0,
                        contrast=1, invert=False, fit="stretch", cancel=None, reference_animation=False):
    validate_video_options(fps=fps, width=width, height=height, start_ms=start_ms,
                           scroll_speed=scroll_speed, target_client=target_client, threshold=threshold,
                           brightness=brightness, contrast=contrast, invert=invert, fit=fit,
                           reference_animation=reference_animation)
    if not isinstance(frame_index, int) or not 0 <= frame_index < MAX_VIDEO_FRAMES:
        raise ValueError(f"预览帧序号须在 1–{MAX_VIDEO_FRAMES} 之间。")
    with tempfile.TemporaryDirectory(prefix="osu-paint-preview-") as directory:
        raw, source = Path(directory) / "frame.raw", Path(directory) / "source.ppm"
        # Select AFTER the same FPS resampling used by full import, including VFR inputs.
        filters = (f"fps=fps={number(fps)}:start_time=0:round=up,select=eq(n\\,{frame_index}),split=2[src][pixels];"
                   "[src]scale=320:180:force_original_aspect_ratio=decrease,"
                   "pad=320:180:(ow-iw)/2:(oh-ih)/2,format=rgb24[source];"
                   f"[pixels]{_scale_filter(width, height, fit)}[result]")
        _run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(Path(path).resolve()),
                     "-filter_complex", filters, "-map", "[source]", "-frames:v", "1", str(source),
                     "-map", "[result]", "-frames:v", "1", "-f", "rawvideo", str(raw)], cancel)
        if not raw.exists() or raw.stat().st_size != width * height or not source.exists():
            raise ValueError("所选帧超出视频范围，请选择更小的帧序号。")
        return {"frame": _pixel_frame(raw.read_bytes(), width, threshold=threshold, brightness=brightness,
                                     contrast=contrast, invert=invert),
                "source_ppm": source.read_bytes(), "frame_index": frame_index,
                "time_ms": frame_index * 1000 / fps}


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
                 progress=None, cancel=None, target_client="lazer", threshold=128, brightness=0,
                 contrast=1, invert=False, fit="stretch", reference_animation=False):
    transition = validate_video_options(fps=fps, width=width, height=height,
                                        start_ms=start_ms, scroll_speed=scroll_speed, target_client=target_client,
                                        threshold=threshold, brightness=brightness, contrast=contrast, invert=invert, fit=fit,
                                        reference_animation=reference_animation)
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
        filters = f"fps=fps={number(fps)}:start_time=0:round=up," + _scale_filter(width, height, fit)
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
            frames.append(_pixel_frame(block, width, threshold=threshold, brightness=brightness,
                                       contrast=contrast, invert=invert))
        period = 1000 / fps
        starts = [math.floor(start_ms + i * period + 1e-7) if reference_animation else start_ms + i * period
                  for i in range(count + 1)]
        windows = [(starts[i], starts[i + 1] - (transition if i < count - 1 else 0))
                   for i in range(count)]
        report("正在编译谱面与视频时间轴…")
        plan = compile_frames(frames, scroll_speed=scroll_speed, frame_times=windows,
                              fast_clear=True, allow_empty_frames=True, anchor_reference=True,
                              target_client=target_client, reference_animation=reference_animation)
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
             "start_ms": start_ms, "duration_ms": count * period,
             "threshold": threshold, "brightness": brightness, "contrast": contrast, "invert": invert, "fit": fit}
    if reference_animation:
        video["reference_animation"] = True
    plan["video"] = video.copy()
    return {"plan": plan, "audio": audio_data, "video": video}
