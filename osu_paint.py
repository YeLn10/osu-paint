"""Generate near-stationary osu!mania lazer note frames (Python 3.10+)."""

import argparse
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
import html
import json
import math
from pathlib import Path
import wave
import zipfile

from osu_paint_skin import DEFAULT_ASPECT_RATIO, build_skins


SUPPORTED_KEY_COUNTS = tuple(range(1, 19))
PLAYFIELD_HEIGHT = 768
# Clear the bottom-anchor inset plus one internal pixel for rounding, not a 10% white band.
SWEEP_HEIGHT = 1 + 2 / PLAYFIELD_HEIGHT
SCROLL_SPEED = 27


@dataclass(frozen=True)
class Point:
    time: float
    beat_length: float
    sv: float


class Timeline:
    def __init__(self, points, base_beat_length=500):
        self.points = points
        self.times = [p.time for p in points]
        self.speeds = [base_beat_length / p.beat_length * p.sv for p in points]
        self.distances = [0.0]
        for i in range(1, len(points)):
            self.distances.append(self.distances[-1] +
                                  (self.times[i] - self.times[i - 1]) * self.speeds[i - 1])

    def position(self, time):
        i = max(0, bisect_right(self.times, time) - 1)
        return self.distances[i] + (time - self.times[i]) * self.speeds[i]

    def time_at(self, distance):
        i = max(0, bisect_right(self.distances, distance) - 1)
        return self.times[i] + (distance - self.distances[i]) / self.speeds[i]


def parse_pattern(text, *, allow_empty=False):
    rows = text.strip().splitlines()
    if not rows or len(rows[0]) not in SUPPORTED_KEY_COUNTS:
        raise ValueError("图案列数须为 1–18。")
    if any(len(row) != len(rows[0]) or set(row) - {"#", "."} for row in rows):
        raise ValueError("图案每行必须等宽，只能使用 # 和 .。")
    if not allow_empty and not any("#" in row for row in rows):
        raise ValueError("图案至少需要一个 #。")
    return rows


def parse_frames(text, *, allow_empty=False):
    """Separate equally sized text frames with a line containing --- ."""
    blocks = [[]]
    for line in text.strip().splitlines():
        if line.strip() == "---":
            blocks.append([])
        else:
            blocks[-1].append(line)
    frames = [parse_pattern("\n".join(block), allow_empty=allow_empty) for block in blocks]
    if any((len(frame), len(frame[0])) != (len(frames[0]), len(frames[0][0]))
           for frame in frames):
        raise ValueError("动画的所有帧必须具有相同的行数和列数。")
    return frames


def most_common_beat_length(points, last_object_time):
    """Match lazer's reference-BPM grouping and object-time boundary."""
    durations = defaultdict(float)
    for i, p in enumerate(points):
        start = 0 if i == 0 else p.time
        if start > last_object_time:
            break
        end = min(points[i + 1].time if i + 1 < len(points) else last_object_time,
                  last_object_time)
        beat = round(p.beat_length * 1000) / 1000
        duration = end - start
        durations[beat] += duration
    result = max(durations, key=durations.get)
    return min(max(p.beat_length for p in points),
               max(min(p.beat_length for p in points), result))


def compile_pattern(rows, start_ms, end_ms, scroll_speed=27, transition_ms=12):
    return compile_frames([rows], start_ms, end_ms, scroll_speed, transition_ms)


def minimum_transition_ms(scroll_speed=SCROLL_SPEED):
    if not math.isfinite(scroll_speed) or not 1 <= scroll_speed <= 40:
        raise ValueError("lazer 滚速须在 1–40 之间。")
    time_range = 11485 / scroll_speed * 480 / 402
    # Reserve a legal sweep at the conservative 500 ms reference; fast-clear may
    # shorten the actual sweep after checking the complete picture's drift budget.
    minimum = math.ceil(SWEEP_HEIGHT * time_range / (500 / 6 * 10) * 1000) / 1000
    return minimum


def _note_runs(rows, merge_holds):
    for column in range(len(rows[0])):
        row = 0
        while row < len(rows):
            if rows[row][column] == ".":
                row += 1
                continue
            top = row
            if merge_holds:
                while row + 1 < len(rows) and rows[row + 1][column] == "#":
                    row += 1
            yield column, top, row
            row += 1


def compile_frames(frames, start_ms=None, end_ms=None, scroll_speed=27, transition_ms=12,
                   *, frame_times=None, fast_clear=False, allow_empty_frames=False,
                   anchor_reference=False, merge_holds=False):
    if not isinstance(merge_holds, bool):
        raise ValueError("连续单键转长条必须是开关值。")
    if not frames:
        raise ValueError("至少需要一帧图案。")
    frames = parse_frames("\n---\n".join("\n".join(rows) for rows in frames),
                          allow_empty=allow_empty_frames)
    has_notes = [any("#" in row for row in rows) for rows in frames]
    if not all(math.isfinite(v) for v in (scroll_speed, transition_ms)):
        raise ValueError("时间和滚速必须是有限数值。")
    if not 1 <= scroll_speed <= 40:
        raise ValueError("lazer 滚速须在 1–40 之间。")
    # Pixel Film puts judgement at the bottom: 480 instead of legacy 402.
    minimum = minimum_transition_ms(scroll_speed)
    time_range = 11485 / scroll_speed * 480 / 402
    requested_transition = transition_ms
    if transition_ms <= 0:
        raise ValueError("切帧时长必须大于 0。")
    if fast_clear:
        transition_ms = minimum
    # One full stage plus the bottom-anchor clearance; shared frames almost touch.
    fast_multiplier = SWEEP_HEIGHT * time_range / transition_ms
    fast_beat = 500 * 10 / fast_multiplier
    if not 6 <= fast_beat <= 60000:
        raise ValueError("换帧时间超出 lazer 合法 BPM 范围；请调整 --transition-ms。")

    timing_mode = "free" if frame_times is not None else "uniform"
    if frame_times is None:
        if start_ms is None or end_ms is None or not all(math.isfinite(v) for v in (start_ms, end_ms)):
            raise ValueError("开始与结束时间必须是有限数值。")
        hold_ms = (end_ms - start_ms - (len(frames) - 1) * transition_ms) / len(frames)
        if hold_ms <= 0:
            raise ValueError("时间范围不足以容纳所有换帧；请扩大范围或缩短 --transition-ms。")
        frame_times = [(start_ms + i * (hold_ms + transition_ms),
                        end_ms if i == len(frames) - 1 else start_ms + i * (hold_ms + transition_ms) + hold_ms)
                       for i in range(len(frames))]
    if len(frame_times) != len(frames):
        raise ValueError("每一帧都需要一组开始和结束时间。")
    for i, window in enumerate(frame_times):
        if len(window) != 2 or not all(math.isfinite(v) for v in window) or window[1] <= window[0]:
            raise ValueError(f"第 {i + 1} 帧需要有限的开始、结束时间，且结束 > 开始。")
    for i, window in enumerate(frame_times):
        if i and window[0] - frame_times[i - 1][1] < transition_ms - 1e-7:
            raise ValueError(f"第 {i}、{i + 1} 帧重叠或间隔不足；至少需要 {transition_ms:.3f} ms 切帧。")
    start_ms, end_ms = frame_times[0][0], frame_times[-1][1]
    if start_ms - transition_ms < 100:
        raise ValueError("进场前至少保留 100 ms；请推迟第一帧开始时间。")
    anchors = [min(transition_ms * 2, (end - start) / 2) if anchor_reference else 0
               for start, end in frame_times]
    counts = [math.ceil((end - start - anchor) / 50)
              for (start, end), anchor in zip(frame_times, anchors)]
    if 60000 - (sum(counts) - 1) * 0.01 < 6:
        raise ValueError("展示时间过长，无法分配不同的合法慢速 BPM。")
    note_frames = list(range(len(frames)))
    # Reuse identical pictures, but never bridge a deliberate gap
    # or let the total (including reference anchors) drift beyond half a row.
    maximum_counts = sum(math.ceil((end - start) / 50) for start, end in frame_times)
    slow_beat = 60000 - (maximum_counts - 1) * 0.01
    reuse_distance = min(0.5 * time_range / len(frames[0]), 0.5 * time_range / PLAYFIELD_HEIGHT)
    for i in range(1, len(frames)):
        first = note_frames[i - 1]
        gap = frame_times[i][0] - frame_times[i - 1][1]
        hold = frame_times[i][1] - frame_times[first][0]
        anchored = anchors[first]
        distance = anchored * 0.01 + (hold - anchored) * 500 / slow_beat * 0.01
        if frames[i] == frames[i - 1] and gap <= 2 * transition_ms + 1e-7 and distance < reuse_distance:
            note_frames[i] = first
            anchors[i] = 0  # No sweep means no corresponding reference-BPM anchor is needed.
    counts = [math.ceil((end - start - anchor) / 50)
              for (start, end), anchor in zip(frame_times, anchors)]
    if 60000 - (sum(counts) - 1) * 0.01 < 6:
        raise ValueError("展示时间过长，无法分配不同的合法慢速 BPM。")
    reference_beat = 500
    if fast_clear:
        # A longer reference beat permits faster sweeps, but also increases slow
        # drift. Keep the existing picture groups and cap their WHOLE held span
        # (including the extended plateau before a shared sweep) at half a pixel.
        limit = 5000
        for i, first in enumerate(note_frames):
            # Blank pictures cannot drift visibly or constrain other frames' sweeps.
            if not has_notes[first]:
                continue
            if i + 1 < len(frames) and note_frames[i + 1] == first:
                continue
            until = frame_times[i][1]
            if i + 1 < len(frames) and frame_times[i + 1][0] - until <= 2 * transition_ms + 1e-7:
                until = frame_times[i + 1][0]
            anchored = anchors[first]
            slow_time = until - frame_times[first][0] - anchored
            if slow_time > 0:
                limit = min(limit, (reuse_distance - anchored * .01) * slow_beat / (slow_time * .01))
        # Match lazer's millisecond beat grouping, with a little rounding margin.
        reference_beat = max(500, math.floor(limit * .98 * 1000) / 1000)
    sweep_ms = transition_ms * 500 / reference_beat
    points = [Point(0, reference_beat, 1), Point(start_ms - sweep_ms, fast_beat, 10)]
    frame_plans = []
    slow_index = 0
    entry_start = start_ms - sweep_ms

    for index, (rows, (start, end), count) in enumerate(zip(frames, frame_times, counts)):
        frame = {"pattern": rows, "start_ms": start, "end_ms": end,
                 "entry_start_ms": entry_start, "exit_end_ms": end + sweep_ms, "sweep_start_ms": end}
        frame_plans.append(frame)
        if anchors[index]:
            # Brief near-stationary reference segments keep that BPM dominant
            # even when thousands of video transitions would otherwise outweigh the lead-in.
            points.append(Point(start, reference_beat, 0.01))
        for i in range(count):
            # Keep values unique across ALL frames, not just within one hold.
            beat = 60000 - slow_index * 0.01
            points.append(Point(start + anchors[index] + i * 50, beat, 0.01))
            slow_index += 1
        if index == len(frames) - 1:
            points.append(Point(end, fast_beat, 10))
        else:
            next_start = frame_times[index + 1][0]
            gap = next_start - end
            if note_frames[index + 1] == note_frames[index]:
                # Keep the same notes on stage instead of sweeping an identical picture.
                continue
            if gap > 2 * transition_ms + 1e-7:
                # Clear the old frame now, then bring the next in at its own start.
                points.append(Point(end, fast_beat, 10))
                points.extend([Point(end + sweep_ms, reference_beat, 1),
                               Point(next_start - sweep_ms, fast_beat, 10)])
                entry_start = next_start - sweep_ms
            else:
                # Hold the old picture longer; compress the sweep, not the saved
                # frame windows. Old video projects benefit on re-export too.
                entry_start = next_start - gap * 500 / reference_beat
                frame["sweep_start_ms"] = entry_start
                points.append(Point(entry_start, fast_beat, min(10, 10 * transition_ms / gap)))
                frame["exit_end_ms"] = next_start
    points.append(Point(end_ms + sweep_ms, reference_beat, 1))
    timeline = Timeline(points, reference_beat)

    for index in range(len(frame_plans) - 2, -1, -1):
        if note_frames[index] == note_frames[index + 1]:
            frame_plans[index]["exit_end_ms"] = frame_plans[index + 1]["exit_end_ms"]
            frame_plans[index]["sweep_start_ms"] = frame_plans[index + 1]["sweep_start_ms"]
    notes = []
    for index, frame in enumerate(frame_plans):
        first = note_frames[index]
        frame["note_frame"] = first
        frame["entry_start_ms"] = frame_plans[first]["entry_start_ms"]
        drift = ((timeline.position(frame["end_ms"]) - timeline.position(frame_plans[first]["start_ms"])) / time_range
                 if has_notes[index] else 0)
        if drift >= 0.5 / len(frame["pattern"]):
            raise ValueError("展示时间过长，图案会接近判定线；请缩短时间范围。")
        frame["drift_playfield_fraction"] = drift
        frame["drift_at_768px"] = drift * PLAYFIELD_HEIGHT
        if index != first or not has_notes[index]:
            continue
        rows = frame["pattern"]
        # Legacy lazer notes extend upward from their bottom anchor. Keep the
        # bottom head ahead of judgement until this entire reused picture exits.
        held_drift = (timeline.position(frame["sweep_start_ms"]) - timeline.position(frame["start_ms"])) / time_range
        inset = held_drift + 1 / PLAYFIELD_HEIGHT
        times = {}
        for row in {r for _, top, bottom in _note_runs(rows, merge_holds) for r in (top, bottom)}:
            # Row zero is at the top. Hold heads are the BOTTOM of a lit run,
            # with their later tail timestamp at the top; never span dark gaps.
            y = (row + 1) / len(rows) - inset
            times[row] = timeline.time_at(timeline.position(frame["start_ms"]) + (1 - y) * time_range)
        for column, top, bottom in _note_runs(rows, merge_holds):
            note = {"frame": index, "column": column, "row": bottom, "time_ms": times[bottom],
                    "y": (bottom + 1) / len(rows) - inset}
            if top != bottom:
                note.update(end_row=top, end_time_ms=times[top], end_y=(top + 1) / len(rows) - inset)
            notes.append(note)
    if not notes:
        raise ValueError("所有帧均为空白，至少需要一个 #；视频需要包含亮部。")
    notes.sort(key=lambda n: (n["time_ms"], n["column"]))
    last_object_time = max(n.get("end_time_ms", n["time_ms"]) for n in notes)
    base = most_common_beat_length(points, last_object_time)
    if not math.isclose(base, reference_beat, abs_tol=1e-9):
        raise ValueError("该时间组合改变了参考 BPM；请增加 start 或缩短 transition。")

    drift = max(frame["drift_playfield_fraction"] for frame in frame_plans)
    return {
        "pattern": frames[0], "frames": frame_plans, "keys": len(frames[0][0]),
        "screen_aspect_ratio": DEFAULT_ASPECT_RATIO,
        "start_ms": start_ms, "end_ms": end_ms,
        "transition_ms": transition_ms, "sweep_ms": sweep_ms, "scroll_speed": scroll_speed,
        "requested_transition_ms": requested_transition, "fast_clear": fast_clear,
        "timing_mode": timing_mode, "target_client": "lazer", "merge_holds": merge_holds,
        "time_range_ms": time_range, "base_beat_length_ms": base,
        "skin_assumption": "Pixel Film full-screen skin, HitPosition 480, fixed scroll speed, downscroll, no speed/column mods",
        "drift_playfield_fraction": drift, "drift_at_768px": drift * PLAYFIELD_HEIGHT,
        "points": [p.__dict__ for p in points], "notes": notes,
    }


def number(value):
    return f"{value:.9f}".rstrip("0").rstrip(".")


def encode_osu(plan, audio_filename="silence.wav"):
    lines = [
        "osu file format v14", "", "[General]", f"AudioFilename: {audio_filename}",
        "AudioLeadIn: 0", f"PreviewTime: {int(plan['start_ms'])}", "Countdown: 0",
        "SampleSet: Soft", "Mode: 3", "", "[Metadata]", "Title: SV Pattern",
        "Artist: osu-paint", "Creator: osu-paint",
        f"Version: lazer {plan['keys']}K - Scroll speed {number(plan['scroll_speed'])} - Use NF",
        "Tags: sv animation prototype", "BeatmapID: 0", "BeatmapSetID: -1", "",
        "[Difficulty]", "HPDrainRate: 0", f"CircleSize: {plan['keys']}",
        "OverallDifficulty: 5", "ApproachRate: 5", "SliderMultiplier: 1",
        "SliderTickRate: 1", "", "[Events]", "", "[TimingPoints]",
    ]
    for p in plan["points"]:
        # Red lines reset inherited speed; ALWAYS follow with the intended green line.
        lines.append(f"{number(p['time'])},{number(p['beat_length'])},4,2,0,5,1,8")
        lines.append(f"{number(p['time'])},{number(-100 / p['sv'])},4,2,0,5,0,0")
    lines.extend(["", "[HitObjects]"])
    for note in plan["notes"]:
        x = int((note["column"] + 0.5) * 512 / plan["keys"])
        if "end_time_ms" in note:
            lines.append(f"{x},192,{number(note['time_ms'])},128,0,{number(note['end_time_ms'])}:0:0:0:0:")
        else:
            lines.append(f"{x},192,{number(note['time_ms'])},1,0,0:0:0:0:")
    return "\n".join(lines) + "\n"


def make_preview(plan):
    # Geometry preview only: native skins, object lifetime and judgement aren't simulated.
    data = json.dumps(plan, ensure_ascii=False).replace("<", "\\u003c")
    pattern = html.escape("\n".join(plan["pattern"]))
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>osu-paint 位置预览</title><style>
body{font:16px system-ui;background:#121520;color:#edf0ff;max-width:880px;margin:32px auto}
main{display:flex;gap:32px}canvas{background:#090c14;border:1px solid #434b67}
input{width:100%}button{padding:8px 20px}pre{line-height:1.4;color:#80e0de}
</style><h1>SV 图案位置预览</h1>
<p>几何模型预览；不是游戏实机画面。速度设置、皮肤和判定会影响实际外观。</p>
<main><canvas id="view" width="960" height="600" style="width:60%;height:auto;align-self:flex-start"></canvas><div>
<pre id="pattern">""" + pattern + """</pre><p id="info"></p><button id="play">播放</button>
<p><input id="seek" type="range" step="0.01"></p><output id="time"></output>
<p>全屏位置预览：白底黑色像素，判定线在底边。<br>按位置清场，不在判定时间直接隐藏音符。<br>不模拟判定或 Miss 淡出。</p>
</div></main><script>
const plan=""" + data + """;
const canvas=document.getElementById('view'),ctx=canvas.getContext('2d');
canvas.width=Math.round(canvas.height*plan.screen_aspect_ratio);
const seek=document.getElementById('seek'),time=document.getElementById('time');
const points=plan.points,positions=[0];
const speed=p=>plan.base_beat_length_ms/p.beat_length*p.sv;
for(let i=1;i<points.length;i++)positions.push(positions[i-1]+(points[i].time-points[i-1].time)*speed(points[i-1]));
function position(t){let i=points.length-1;while(i>0&&points[i].time>t)i--;return positions[i]+(t-points[i].time)*speed(points[i]);}
const notePositions=plan.notes.map(n=>position(n.time_ms));
const noteEndPositions=plan.notes.map(n=>position(n.end_time_ms??n.time_ms));
const maxNoteSpan=notePositions.reduce((span,start,i)=>Math.max(span,noteEndPositions[i]-start),0);
function lowerBound(a,x){let lo=0,hi=a.length;while(lo<hi){let m=(lo+hi)>>>1;if(a[m]<x)lo=m+1;else hi=m;}return lo;}
seek.min=plan.start_ms-plan.transition_ms-40;seek.max=plan.end_ms+plan.transition_ms+40;seek.value=plan.start_ms;
document.getElementById('info').textContent=`${plan.keys}K · ${plan.frames.length} 帧 · 滚速 ${plan.scroll_speed} · ${plan.start_ms}–${plan.end_ms} ms；单帧最大漂移约 ${plan.drift_at_768px.toFixed(4)} px（768 px 高度）。`;
function draw(){let t=+seek.value,h=canvas.height,w=canvas.width/plan.keys,size=h/plan.pattern.length;
ctx.clearRect(0,0,canvas.width,h);ctx.fillStyle='white';ctx.fillRect(0,0,w*plan.keys,h);
const current=position(t),lower=current-size/h*plan.time_range_ms-maxNoteSpan,upper=current+plan.time_range_ms;
ctx.fillStyle='black';for(let i=lowerBound(notePositions,lower);i<plan.notes.length&&notePositions[i]<=upper;i++){
const n=plan.notes[i],y=(1-(notePositions[i]-current)/plan.time_range_ms)*h,tailY=(1-(noteEndPositions[i]-current)/plan.time_range_ms)*h;
if(y>0&&tailY<h+size){const top=Math.max(0,tailY-size);ctx.fillRect(n.column*w,top,w,Math.min(h,y)-top);}}
const index=plan.frames.findIndex((f,i)=>t>=f.start_ms&&(t<=Math.max(f.end_ms,f.sweep_start_ms??f.end_ms)||
    (i+1<plan.frames.length&&t<plan.frames[i+1].start_ms&&f.note_frame!==undefined&&f.note_frame===plan.frames[i+1].note_frame)));
document.getElementById('pattern').textContent=index<0?'空档 / 进场 / 换帧 / 退场':plan.frames[index].pattern.join('\\n');
time.textContent=t.toFixed(2)+' ms'+(index<0?'':` · 第 ${index+1} 帧`);}
let playing=false,last=0;document.getElementById('play').onclick=()=>{playing=!playing;if(playing&&+seek.value>=+seek.max)seek.value=seek.min;last=performance.now();};
seek.oninput=()=>{playing=false;draw();};function tick(now){if(playing){seek.value=Math.min(+seek.max,+seek.value+now-last);if(+seek.value>=+seek.max)playing=false;draw();}last=now;requestAnimationFrame(tick);}draw();requestAnimationFrame(tick);
</script></html>"""


def write_output(plan, output, *, audio_data=None):
    output.mkdir(parents=True, exist_ok=True)
    build_skins(output, len(plan["pattern"]))
    audio_filename = "silence.wav" if audio_data is None else "audio.ogg"
    (output / "pattern.osu").write_text(encode_osu(plan, audio_filename), encoding="utf-8")
    if audio_data is not None:
        (output / audio_filename).write_bytes(audio_data)
    else:
        with wave.open(str(output / audio_filename), "wb") as audio:
            audio.setparams((1, 1, 8000, 0, "NONE", "not compressed"))
            remaining = math.ceil((plan["end_ms"] + plan["transition_ms"] + 1000) * 8)
            while remaining:
                size = min(remaining, 8000)
                audio.writeframes(b"\x80" * size)
                remaining -= size
    with zipfile.ZipFile(output / "pattern.osz", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("pattern.osu", audio_filename):
            archive.write(output / name, name)
    (output / "report.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "preview.html").write_text(make_preview(plan), encoding="utf-8")
    video = plan.get("video", {})
    settings_path = output / "播放设置.txt"
    if video.get("refresh_hz") is not None:
        settings_path.write_text(
            "osu!lazer 播放设置\n"
            f"屏幕刷新率：{number(video['refresh_hz'])} Hz\n"
            "已自动安排换帧；音轨不移动。\n"
            f"mania 使用固定滚速 {number(plan['scroll_speed'])}、向下滚动与 NF；不要使用变速或改变列数的 Mod。\n"
            "游戏与系统使用填写的刷新率，舞台缩放保持默认值。\n"
            "导入同目录中匹配屏幕比例的 pixel-film*.osk。\n"
            "lazer 的 >10K 仍拆分，11/13/15/17K 会少一列。\n",
            encoding="utf-8")
    elif settings_path.exists():
        settings_path.unlink()


def main():
    parser = argparse.ArgumentParser(description="用文本像素图或视频生成 osu!mania 音符动画。")
    parser.add_argument("pattern", type=Path, help="文本图案；配合 --video 时为本地视频文件")
    parser.add_argument("--video", action="store_true", help="导入视频及音轨，自动使用极速清场")
    parser.add_argument("--fps", type=float, default=10, help="视频每秒帧数，可填小数，默认 10")
    parser.add_argument("--refresh-hz", help="实际刷新率，支持 59.94 或 60000/1001；按整次刷新安排视频采样")
    parser.add_argument("--merge-holds", action="store_true", help="同一帧同列连续亮格转长条，不跨空格")
    parser.add_argument("--width", type=int, default=10, help="视频列数：1–18，默认 10")
    parser.add_argument("--height", type=int, default=24, help="视频画面高度 / 行，1–128，默认 24")
    parser.add_argument("--threshold", type=float, default=128, help="视频黑白阈值，0–255")
    parser.add_argument("--brightness", type=float, default=0, help="视频亮度偏移，-255–255")
    parser.add_argument("--contrast", type=float, default=1, help="视频对比度，>0–5")
    parser.add_argument("--invert", action="store_true", help="交换画面亮暗")
    parser.add_argument("--fit", choices=("stretch", "contain", "cover"), default="stretch", help="拉伸、等比留边、等比裁剪")
    parser.add_argument("--start-ms", type=float, required=True, help="完整展示开始时间（ms）")
    parser.add_argument("--end-ms", type=float, help="文本图案必填；视频结束时间由 FPS 与实际帧数确定")
    parser.add_argument("--scroll-speed", type=float, default=27, help="须与 lazer 设置相同，默认 27")
    parser.add_argument("--transition-ms", type=float, default=12, help="进场/退场各自时长，默认 12 ms")
    parser.add_argument("--fast-clear", action="store_true", help="自动以合法最高速度清场，覆盖手动切帧时长")
    parser.add_argument("--output", type=Path, default=Path("output"), help="输出目录，同名生成文件会覆盖")
    args = parser.parse_args()
    try:
        refresh_hz = float(Fraction(args.refresh_hz)) if args.refresh_hz is not None else None
    except (ValueError, ZeroDivisionError):
        parser.error("--refresh-hz 须为数字或分数，例如 59.94 或 60000/1001。")
    try:
        if args.video:
            if args.end_ms is not None:
                raise ValueError("视频结束时间自动计算，请不要传 --end-ms。")
            from osu_paint_video import import_video
            result = import_video(args.pattern, fps=args.fps, width=args.width, height=args.height,
                                  start_ms=args.start_ms, scroll_speed=args.scroll_speed,
                                  threshold=args.threshold, brightness=args.brightness, contrast=args.contrast,
                                  invert=args.invert, fit=args.fit,
                                  refresh_hz=60 if refresh_hz is None else refresh_hz,
                                  merge_holds=args.merge_holds)
            plan = result["plan"]
            write_output(plan, args.output, audio_data=result["audio"])
        else:
            if refresh_hz is not None:
                raise ValueError("--refresh-hz 仅可用于视频导入。")
            if args.end_ms is None:
                raise ValueError("文本图案需要 --end-ms。")
            frames = parse_frames(args.pattern.read_text(encoding="utf-8-sig"))
            plan = compile_frames(frames, args.start_ms, args.end_ms, args.scroll_speed, args.transition_ms,
                                  fast_clear=args.fast_clear,
                                  merge_holds=args.merge_holds)
            write_output(plan, args.output)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"已生成 {args.output.resolve() / 'pattern.osz'}")
    print("请导入同目录中匹配屏幕比例的 pixel-film*.osk；默认 pixel-film.osk 适用于 16:10（3072×1920）。")
    print(f"{plan['keys']}K / {len(plan['frames'])} 帧 / {len(plan['notes'])} 音符 / 游戏滚速 {number(args.scroll_speed)}")
    print(f"单帧最大预计漂移 {plan['drift_at_768px']:.4f} px（768 px 高度），不是精确零速。")


if __name__ == "__main__":
    main()
