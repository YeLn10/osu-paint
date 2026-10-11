"""Import local video as timestamped note frames and a portable Ogg audio track."""

from fractions import Fraction
import math
from pathlib import Path
import re
import tempfile

from osu_paint import SUPPORTED_KEY_COUNTS, compile_frames, minimum_transition_ms, number
from osu_paint_app.ffmpeg import ImportCancelled, check_cancel, run_ffmpeg


MAX_VIDEO_FRAMES = 20000
MAX_VIDEO_PIXELS = 2000000


def resolve_video_options(*, fps, width, height, start_ms, scroll_speed,
                          threshold=128, brightness=0, contrast=1, invert=False, fit="stretch",
                          refresh_hz=None, merge_holds=False, target_client="lazer"):
    if not math.isfinite(fps) or not 0 < fps <= 60:
        raise ValueError("视频 FPS 须大于 0 且不超过 60，可以填写小数。")
    if not isinstance(height, int) or not 1 <= height <= 128:
        raise ValueError("视频高度须为 1–128 行。")
    if not isinstance(merge_holds, bool):
        raise ValueError("连续单键转长条必须是开关值。")
    if refresh_hz is not None:
        if isinstance(refresh_hz, bool) or not math.isfinite(refresh_hz) or not 20 <= refresh_hz <= 1000:
            raise ValueError("实际刷新率须为 20–1000 Hz，可填写小数。")
        # Never add extra sweeps by rounding FPS up; tolerate a resolved float round-trip.
        divisor = max(math.ceil(refresh_hz / 60), 1, math.ceil(refresh_hz / fps - 1e-12))
        fps = refresh_hz / divisor
        if target_client == "lazer" and minimum_transition_ms(scroll_speed) >= 1000 / refresh_hz:
            raise ValueError("切帧无法放入一个刷新周期；请提高滚速或降低目标刷新率。")
    options = dict(fps=fps, width=width, height=height, start_ms=start_ms, scroll_speed=scroll_speed,
                   threshold=threshold, brightness=brightness,
                   contrast=contrast, invert=invert, fit=fit, target_client=target_client)
    _validate_video_options(**options)
    options.update(refresh_hz=refresh_hz, merge_holds=merge_holds, target_client=target_client)
    return options


def validate_video_options(**options):
    resolved = resolve_video_options(**options)
    return minimum_transition_ms(resolved["scroll_speed"], resolved["height"], target_client=resolved["target_client"])


def _validate_video_options(*, fps, width, height, start_ms, scroll_speed,
                            threshold, brightness, contrast, invert, fit, target_client):
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
    transition = minimum_transition_ms(scroll_speed, height, target_client=target_client)
    if not math.isfinite(start_ms) or start_ms - transition < 100:
        raise ValueError("视频开始时间须为有限数值，并在进场前保留至少 100 ms。")
    if target_client == "stable":
        period = 1000 / fps
        available = min(math.floor(period + 1e-9),
                        math.floor(start_ms + period + 1e-9) - math.ceil(start_ms))
        if available < transition + 1:
            raise ValueError(f"stable 的 {height} 行画面需 {transition} ms 切帧及至少 1 ms 展示；请降低 FPS 或减少行数。")
    elif 1000 / fps <= transition * 3:
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


def preview_video_frame(path, *, frame_index=0, fps=10, width=10, height=None, start_ms=2000,
                        scroll_speed=27, threshold=128, brightness=0,
                        contrast=1, invert=False, fit="stretch", cancel=None,
                        refresh_hz=None, merge_holds=False, target_client="lazer"):
    height = (12 if target_client == "stable" else 24) if height is None else height
    resolved = resolve_video_options(fps=fps, width=width, height=height, start_ms=start_ms,
                                     scroll_speed=scroll_speed, threshold=threshold,
                                     brightness=brightness, contrast=contrast, invert=invert, fit=fit,
                                     refresh_hz=refresh_hz, merge_holds=merge_holds, target_client=target_client)
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
        run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(Path(path).resolve()),
                     "-filter_complex", filters, "-map", "[source]", "-frames:v", "1", str(source),
                     "-map", "[result]", "-frames:v", "1", "-f", "rawvideo", str(raw)], cancel)
        if not raw.exists() or raw.stat().st_size != width * height or not source.exists():
            raise ValueError("所选帧超出视频范围，请选择更小的帧序号。")
        return {"frame": _pixel_frame(raw.read_bytes(), width, threshold=threshold, brightness=brightness,
                                     contrast=contrast, invert=invert),
                "source_ppm": source.read_bytes(), "frame_index": frame_index,
                "time_ms": frame_index * 1000 / fps}


def _transition_phases(frame_plans, *, step=1):
    # Advance for actual redraw groups, not sample numbers. This includes the
    # occasional redraw of a long still picture required by the core's drift cap.
    changes = 0
    phases = [0.0]
    for previous, current in zip(frame_plans, frame_plans[1:]):
        changes += current["note_frame"] != previous["note_frame"]
        phases.append(1 - abs(1 - (changes * step / 64) % 2))
    return phases


def _transition_phase_exposure(plan, refresh_period, origin):
    """Exact worst fixed-phase count, total exposure time and longest hit streak."""
    period = Fraction(refresh_period)
    origin = Fraction(origin)
    active = 0
    hits = 0
    cuts = 0
    events = []
    total = 0.0
    for previous, current in zip(plan["frames"], plan["frames"][1:]):
        if (previous["note_frame"] == current["note_frame"] or
                not any("#" in row for row in previous["pattern"] + current["pattern"])):
            continue
        start, end = previous["sweep_start_ms"], current["start_ms"]
        bit = 1 << cuts
        index = cuts
        cuts += 1
        duration = end - start
        total += duration
        if duration >= period:
            active += 1
            hits |= bit
            continue
        # Preserve rational refresh boundaries: floating modulo can separate
        # identical stable phases and invent a very narrow extra hit streak.
        low = (Fraction(start) - origin) % period
        high = low + Fraction(end) - Fraction(start)
        if high > period:
            active += 1
            hits |= bit
            high -= period
        events.extend(((low, 1, index), (high, -1, index)))
    worst = active
    longest = 0
    # Bit i represents visible cut i. Intersecting shifted masks tests a run
    # without scanning every cut at every phase; halving builds the full run.
    def record_streak():
        nonlocal longest
        while longest < active:
            mask, width = hits, longest + 1
            while width > 1 and mask:
                half = width // 2
                mask &= mask << half
                width -= half
            if not mask:
                break
            longest += 1

    record_streak()
    # Open intervals: departures precede arrivals at equal phase boundaries.
    for _, change, index in sorted(events):
        bit = 1 << index
        active += change
        hits = hits | bit if change > 0 else hits & ~bit
        worst = max(worst, active)
        if change > 0:
            record_streak()
    return worst, total, longest


def import_video(path, *, fps=10, width=10, height=None, start_ms=2000, scroll_speed=27,
                 progress=None, cancel=None, threshold=128, brightness=0,
                 contrast=1, invert=False, fit="stretch",
                 refresh_hz=None, merge_holds=False, target_client="lazer"):
    height = (12 if target_client == "stable" else 24) if height is None else height
    requested_fps, requested_height = fps, height
    resolved = resolve_video_options(fps=fps, width=width, height=height,
                                     start_ms=start_ms, scroll_speed=scroll_speed,
                                     threshold=threshold, brightness=brightness, contrast=contrast,
                                     invert=invert, fit=fit,
                                     refresh_hz=refresh_hz, merge_holds=merge_holds, target_client=target_client)
    fps, height = resolved["fps"], resolved["height"]
    transition = minimum_transition_ms(scroll_speed, height, target_client=target_client)
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("请选择存在的本地视频文件。")
    check_cancel(cancel)

    def report(message):
        check_cancel(cancel)
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
        log = run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:v:0",
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
        # Derive EVERY boundary from its index, never by repeatedly adding a
        # rounded period. Retain fractional refresh clocks such as 60000/1001.
        period_exact = (Fraction(1000) / Fraction(str(fps)) if refresh_hz is None else
                        Fraction(1000 * round(refresh_hz / fps)) / Fraction(str(refresh_hz)))
        if target_client == "stable":
            period_exact = (Fraction(1000) / Fraction(str(fps)).limit_denominator() if refresh_hz is None else
                            Fraction(1000 * round(refresh_hz / fps)) / Fraction(str(refresh_hz)).limit_denominator())
        period = float(period_exact)
        origin = Fraction(str(start_ms))
        if target_client == "stable":
            starts = [math.ceil(origin)] + [math.floor(origin + i * period_exact)
                                           for i in range(1, count + 1)]
        else:
            starts = [float(origin + i * period_exact) for i in range(count + 1)]
        nominal_starts = starts
        if target_client == "lazer" and refresh_hz is not None:
            refresh_period = float(period_exact / round(refresh_hz / fps))
            guard = min(transition / 2, (refresh_period - transition) / 4)
            span = refresh_period - transition - 2 * guard
            # Keep the proven sample-based walk as the baseline. A candidate
            # based on real redraws is adopted only if its phase exposure improves.
            starts = [starts[0]] + [starts[i] - guard - span * (1 - abs(1 - (i / 64) % 2))
                                   for i in range(1, count)] + [starts[-1]]
        windows = [(starts[i], starts[i + 1] - (transition if i < count - 1 else 0))
                   for i in range(count)]
        report("正在编译谱面与视频时间轴…")
        plan = compile_frames(frames, scroll_speed=scroll_speed, frame_times=windows,
                              fast_clear=True, allow_empty_frames=True, anchor_reference=True,
                              merge_holds=merge_holds, target_client=target_client)
        if refresh_hz is not None:
            refresh_period = period_exact / round(refresh_hz / fps)
            # Retain the existing candidate first. Reclaim unused guard time only
            # after compiling it, so tighter packing cannot undo earlier gains.
            selected_gap = False
            worst, total, longest = _transition_phase_exposure(plan, refresh_period, origin)
            for actual_gap, step in ((False, 1), (True, 1), (None, 9), (None, 7), (None, 5), (None, 3)):
                if actual_gap is None:
                    actual_gap = target_client == "lazer" or selected_gap
                if step > 1 and longest <= 1:
                    break
                # An odd stride visits the same 128-point triangular cycle in
                # a different order, separating hits without a wraparound jump.
                phases = _transition_phases(plan["frames"], step=step)
                if target_client == "stable":
                    sweep = plan["sweep_ms"]
                    span = max(0, refresh_period - sweep - (0 if actual_gap else 1))
                    spread_starts = [starts[0]]
                    for i in range(1, count):
                        nominal = origin + i * period_exact
                        shifted = math.floor(nominal - span * Fraction(phases[i]))
                        if actual_gap:
                            # First integer END whose sweep starts strictly after
                            # the preceding refresh. Round the smooth offset once,
                            # then clamp; interpolating rounded bounds adds jitter.
                            earliest = math.floor(nominal - refresh_period) + sweep + 1
                            shifted = min(math.floor(nominal), max(earliest, shifted))
                        spread_starts.append(shifted)
                    spread_starts.append(starts[-1])
                else:
                    sweep = plan["sweep_ms"] if actual_gap else transition
                    guard = min(sweep / 2, (float(refresh_period) - sweep) / 4)
                    span = float(refresh_period) - sweep - 2 * guard
                    spread_starts = [starts[0]] + [nominal_starts[i] - guard - span * phases[i]
                                                  for i in range(1, count)] + [starts[-1]]
                spread_windows = [(spread_starts[i], spread_starts[i + 1] - (transition if i < count - 1 else 0))
                                  for i in range(count)]
                if step > 1 and any(abs(b - a - period) > 1 + 1e-7
                                    for a, b in zip(spread_starts[:-2], spread_starts[1:-1])):
                    continue
                # Keep the original scheduling budget and minimum display time.
                if (spread_starts == [f["start_ms"] for f in plan["frames"]] + [plan["end_ms"]] or
                        any(end - start < (1 if target_client == "stable" else 1e-7)
                            for start, end in spread_windows)):
                    continue
                check_cancel(cancel)
                candidate = compile_frames(frames, scroll_speed=scroll_speed, frame_times=spread_windows,
                                           fast_clear=True, allow_empty_frames=True, anchor_reference=True,
                                           merge_holds=merge_holds, target_client=target_client)
                # Moving windows may change reuse groups and hence actual sweep
                # lengths. Validate the recompiled cuts, not just the old estimate.
                if (actual_gap or step > 1) and any(
                        a["note_frame"] != b["note_frame"] and
                        a["sweep_start_ms"] <= float(origin + i * period_exact - refresh_period) + 1e-7
                        for i, (a, b) in enumerate(zip(candidate["frames"], candidate["frames"][1:]), 1)):
                    if step > 1:
                        break
                    continue
                new_worst, new_total, new_longest = _transition_phase_exposure(candidate, refresh_period, origin)
                improves = (new_worst < worst if step == 1 else
                            new_worst <= worst and new_longest < longest)
                if improves and new_total <= total + 1e-7 and len(candidate["notes"]) <= len(plan["notes"]):
                    plan = candidate
                    selected_gap = actual_gap
                    worst, total, longest = new_worst, new_total, new_longest
                # Try smaller odd strides only when scheduling rejects a walk.
                # Compile at most one faster candidate, even if it has no benefit.
                if step > 1:
                    break
            # A long stable sweep confined to one refresh gap can intersect the
            # same display phase on every cut. At low video FPS, allow its end
            # to walk across a whole refresh period, at the cost of showing the
            # next picture up to one refresh early. Keep the audio clock fixed.
            if (target_client == "stable" and refresh_period / 2 < plan["sweep_ms"] < refresh_period
                    and period_exact - 2 * refresh_period >= transition + 1):
                wide_selected = False
                for cadenced in (False, True):
                    # Preserve clean nominal refreshes when the old wide walk
                    # was rejected; only accelerate an accepted wide schedule.
                    if cadenced and not wide_selected:
                        break
                    if not cadenced:
                        phases = _transition_phases(plan["frames"])
                        span = refresh_period - 1  # floor adds less than one ms of lead.
                        spread_starts = [starts[0]] + [
                            math.floor(origin + i * period_exact - span * Fraction(phases[i]))
                            for i in range(1, count)] + [starts[-1]]
                    else:
                        # Use the integer cadence's available speed in each
                        # direction; a faster symmetric triangle can stall on
                        # rounding. Turn only when the actual lead stops growing.
                        spread_starts, lead, forward = [starts[0]], Fraction(0), True
                        for i in range(1, count):
                            nominal = origin + i * period_exact
                            low, high = math.floor(nominal - refresh_period) + 1, math.floor(nominal)
                            redraw = plan["frames"][i]["note_frame"] != plan["frames"][i - 1]["note_frame"]
                            target = (low if forward else high) if redraw else math.floor(nominal - lead)
                            shifted = min(high, spread_starts[-1] + math.floor(period_exact + 1),
                                          max(low, spread_starts[-1] + math.ceil(period_exact - 1), target))
                            if redraw:
                                previous_lead = nominal - period_exact - spread_starts[-1]
                                lead = nominal - shifted
                                if (forward and lead <= previous_lead) or (not forward and lead >= previous_lead):
                                    forward = not forward
                            spread_starts.append(shifted)
                        spread_starts.append(starts[-1])
                    spread_windows = [(spread_starts[i], spread_starts[i + 1] - (transition if i < count - 1 else 0))
                                      for i in range(count)]
                    if (all(abs(b - a - period) <= 1 + 1e-7
                            for a, b in zip(spread_starts[:-2], spread_starts[1:-1]))
                            and all(end - start >= 1 for start, end in spread_windows)
                            and spread_starts != [f["start_ms"] for f in plan["frames"]] + [plan["end_ms"]]):
                        check_cancel(cancel)
                        candidate = compile_frames(frames, scroll_speed=scroll_speed, frame_times=spread_windows,
                                                   fast_clear=True, allow_empty_frames=True, anchor_reference=True,
                                                   merge_holds=merge_holds, target_client=target_client)
                        new_worst, new_total, new_longest = _transition_phase_exposure(candidate, refresh_period, origin)
                        if (new_worst < worst and new_longest < longest and new_total <= total + 1e-7
                                and len(candidate["notes"]) <= len(plan["notes"])
                                and all(a["note_frame"] == b["note_frame"] or
                                        a["sweep_start_ms"] > float(origin + i * period_exact - 2 * refresh_period)
                                        for i, (a, b) in enumerate(zip(candidate["frames"], candidate["frames"][1:]), 1))):
                            plan = candidate
                            worst, total, longest = new_worst, new_total, new_longest
                            wide_selected = True
        audio_data = None
        if re.search(r"^\s*Stream #0:\d+.*Audio:", log, re.MULTILINE):
            report("正在提取音乐并对齐视频开始时间…（可取消）")
            audio = directory / "audio.ogg"
            # Keep the input's relative stream timestamps, including delayed audio starts.
            # Strip original metadata; the exported project never needs the private source path.
            delay_samples = round(start_ms * 48)
            run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:a:0", "-vn",
                         "-af", f"aresample=48000:async=1:first_pts=0,adelay={delay_samples}S:all=1",
                         "-ac", "2", "-c:a", "libvorbis", "-q:a", "5",
                         "-map_metadata", "-1", "-map_chapters", "-1", str(audio)], cancel)
            audio_data = audio.read_bytes()
        check_cancel(cancel)
    video = {"filename": path.name, "fps": fps, "width": width, "height": height,
             "start_ms": start_ms, "duration_ms": count * period,
             "threshold": threshold, "brightness": brightness, "contrast": contrast, "invert": invert, "fit": fit}
    if refresh_hz is not None:
        video.update(refresh_hz=refresh_hz, requested_fps=requested_fps, requested_height=requested_height)
    plan["video"] = video.copy()
    return {"plan": plan, "audio": audio_data, "video": video}
