"""Import local video as timestamped note frames and a portable Ogg audio track."""

from fractions import Fraction
import math
from pathlib import Path
import re
import subprocess
import tempfile

from osu_paint import SUPPORTED_KEY_COUNTS, compile_frames, minimum_transition_ms, number


MAX_VIDEO_FRAMES = 20000
MAX_VIDEO_PIXELS = 2000000


class ImportCancelled(Exception):
    pass


def resolve_video_options(*, fps, width, height, start_ms, scroll_speed, target_client="lazer",
                          threshold=128, brightness=0, contrast=1, invert=False, fit="stretch", game_fps=None,
                          refresh_hz=None, refresh_phase_ms=0, merge_holds=False):
    if not math.isfinite(fps) or not 0 < fps <= 60:
        raise ValueError("视频 FPS 须大于 0 且不超过 60，可以填写小数。")
    if not isinstance(height, int) or not 1 <= height <= 128:
        raise ValueError("视频高度须为 1–128 行。")
    if not isinstance(merge_holds, bool):
        raise ValueError("连续单键转长条必须是开关值。")
    if refresh_hz is not None:
        if game_fps is not None:
            raise ValueError("刷新率排帧与旧版游戏 FPS 排帧不能同时启用。")
        if isinstance(refresh_hz, bool) or not math.isfinite(refresh_hz) or not 20 <= refresh_hz <= 1000:
            raise ValueError("实际刷新率须为 20–1000 Hz，可填写小数。")
    if not math.isfinite(refresh_phase_ms):
        raise ValueError("画面相位偏移必须是有限数值。")
    if refresh_phase_ms and (refresh_hz is None or abs(refresh_phase_ms) > 1000 / refresh_hz):
        raise ValueError("画面相位偏移须在正负一个刷新周期内，并启用刷新率排帧。")
    if game_fps is not None:
        if target_client != "stable":
            raise ValueError("游戏 FPS 优化只支持 stable。")
        if not isinstance(game_fps, int) or not 60 <= game_fps <= 999:
            raise ValueError("游戏 FPS 须为 60–999 的整数。")
    clock_hz = refresh_hz if refresh_hz is not None else game_fps
    if clock_hz is not None:
        if target_client == "stable":
            maximum_height = math.floor(1000 / clock_hz) - 3
            if maximum_height < 1:
                raise ValueError("刷新率太高，stable 无法留出整数毫秒切帧；请使用 250 Hz / FPS 或以下。")
            height = min(height, maximum_height)
        divisor = max(math.ceil(clock_hz / 60), 1, round(clock_hz / fps))
        fps = clock_hz / divisor
        if minimum_transition_ms(scroll_speed, target_client, height) >= 1000 / clock_hz:
            raise ValueError("切帧无法放入一个刷新周期；请提高滚速或降低目标刷新率。")
    options = dict(fps=fps, width=width, height=height, start_ms=start_ms, scroll_speed=scroll_speed,
                   target_client=target_client, threshold=threshold, brightness=brightness,
                   contrast=contrast, invert=invert, fit=fit)
    _validate_video_options(**options)
    if start_ms + refresh_phase_ms - minimum_transition_ms(scroll_speed, target_client, height) < 100:
        raise ValueError("画面相位调整后，进场前仍须保留至少 100 ms。")
    options.update(game_fps=game_fps, refresh_hz=refresh_hz, refresh_phase_ms=refresh_phase_ms,
                   merge_holds=merge_holds)
    return options


def validate_video_options(**options):
    resolved = resolve_video_options(**options)
    return minimum_transition_ms(resolved["scroll_speed"], resolved["target_client"], resolved["height"])


def _validate_video_options(*, fps, width, height, start_ms, scroll_speed, target_client,
                            threshold, brightness, contrast, invert, fit):
    if not math.isfinite(fps) or not 0 < fps <= 60:
        raise ValueError("视频 FPS 须大于 0 且不超过 60，可以填写小数。")
    if not isinstance(width, int) or width not in SUPPORTED_KEY_COUNTS:
        raise ValueError("视频宽度须为 1–18 列。")
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
    transition = minimum_transition_ms(scroll_speed, target_client, height)
    if not math.isfinite(start_ms) or start_ms - transition < 100:
        raise ValueError("视频开始时间须为有限数值，并在进场前保留至少 100 ms。")
    if target_client == "stable" and math.floor(1000 / fps) < transition + 1:
        maximum_fps = math.floor(1000000 / (transition + 1)) / 1000
        raise ValueError(f"stable 的 {height} 行画面至少需要 {transition + 1:g} ms / 帧；"
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
                        contrast=1, invert=False, fit="stretch", cancel=None, game_fps=None,
                        refresh_hz=None, refresh_phase_ms=0, merge_holds=False):
    resolved = resolve_video_options(fps=fps, width=width, height=height, start_ms=start_ms,
                                     scroll_speed=scroll_speed, target_client=target_client, threshold=threshold,
                                     brightness=brightness, contrast=contrast, invert=invert, fit=fit, game_fps=game_fps,
                                     refresh_hz=refresh_hz, refresh_phase_ms=refresh_phase_ms, merge_holds=merge_holds)
    fps, height = resolved["fps"], resolved["height"]
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
                 contrast=1, invert=False, fit="stretch", game_fps=None,
                 refresh_hz=None, refresh_phase_ms=0, merge_holds=False):
    requested_fps, requested_height = fps, height
    resolved = resolve_video_options(fps=fps, width=width, height=height,
                                     start_ms=start_ms, scroll_speed=scroll_speed, target_client=target_client,
                                     threshold=threshold, brightness=brightness, contrast=contrast,
                                     invert=invert, fit=fit, game_fps=game_fps,
                                     refresh_hz=refresh_hz, refresh_phase_ms=refresh_phase_ms, merge_holds=merge_holds)
    fps, height = resolved["fps"], resolved["height"]
    transition = minimum_transition_ms(scroll_speed, target_client, height)
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
        clock_hz = refresh_hz if refresh_hz is not None else game_fps
        # Derive EVERY boundary from its index, never by repeatedly adding a
        # rounded period. Retain fractional refresh clocks such as 60000/1001.
        period_exact = (Fraction(1000) / Fraction(str(fps)) if clock_hz is None else
                        Fraction(1000 * round(clock_hz / fps)) / Fraction(str(clock_hz)))
        period = float(period_exact)
        origin = Fraction(str(start_ms)) + Fraction(str(refresh_phase_ms))
        if clock_hz is None:
            starts = [float(origin + i * period_exact) for i in range(count + 1)]
            windows = [(starts[i], starts[i + 1] - (transition if i < count - 1 else 0))
                       for i in range(count)]
        else:
            refresh_period = Fraction(1000) / Fraction(str(clock_hz))
            post_margin = (refresh_period - Fraction(str(transition))) / 2
            if game_fps is not None:
                post_margin = max(1, math.floor(post_margin))  # Preserve old project timing.
            quantize = math.floor if target_client == "stable" else float
            starts = [quantize(origin)] + [quantize(origin + i * period_exact - post_margin)
                                          for i in range(1, count)]
            windows = [(starts[i], starts[i + 1] - transition) for i in range(count - 1)]
            windows.append((starts[-1], quantize(origin + count * period_exact)))
        report("正在编译谱面与视频时间轴…")
        plan = compile_frames(frames, scroll_speed=scroll_speed, frame_times=windows,
                              fast_clear=True, allow_empty_frames=True, anchor_reference=True,
                              target_client=target_client, merge_holds=merge_holds)
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
    if game_fps is not None:
        video["game_fps"] = game_fps
    if refresh_hz is not None:
        video.update(refresh_hz=refresh_hz, refresh_phase_ms=refresh_phase_ms)
    if clock_hz is not None:
        video.update(requested_fps=requested_fps, requested_height=requested_height)
    plan["video"] = video.copy()
    return {"plan": plan, "audio": audio_data, "video": video}
