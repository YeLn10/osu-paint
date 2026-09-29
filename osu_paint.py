"""Generate near-stationary osu!mania lazer note frames (Python 3.10+)."""

import argparse
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
import html
import json
import math
from pathlib import Path
import wave
import zipfile


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
    if not rows or not 1 <= len(rows[0]) <= 10:
        raise ValueError("图案宽度须为 1–10 列（初版使用单舞台）。")
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
    """Match lazer Beatmap.GetMostCommonBeatLength's millisecond grouping."""
    durations = defaultdict(float)
    for i, p in enumerate(points):
        start = 0 if i == 0 else p.time
        if start > last_object_time:
            break
        end = min(points[i + 1].time if i + 1 < len(points) else last_object_time,
                  last_object_time)
        durations[round(p.beat_length * 1000) / 1000] += end - start
    result = max(durations, key=durations.get)
    return min(max(p.beat_length for p in points),
               max(min(p.beat_length for p in points), result))


def compile_pattern(rows, start_ms, end_ms, scroll_speed=27, transition_ms=12):
    return compile_frames([rows], start_ms, end_ms, scroll_speed, transition_ms)


def minimum_transition_ms(scroll_speed):
    if not math.isfinite(scroll_speed) or not 1 <= scroll_speed <= 40:
        raise ValueError("lazer 滚速须在 1–40 之间。")
    time_range = 11485 / scroll_speed * (658 / 643.2)
    # Maximum legal speed is 500 / 6 * 10. Round UP to avoid exceeding it.
    return math.ceil(1.1 * time_range / (500 / 6 * 10) * 1000) / 1000


def compile_frames(frames, start_ms=None, end_ms=None, scroll_speed=27, transition_ms=12,
                   *, frame_times=None, fast_clear=False, allow_empty_frames=False,
                   anchor_reference=False):
    if not frames:
        raise ValueError("至少需要一帧图案。")
    frames = parse_frames("\n---\n".join("\n".join(rows) for rows in frames),
                          allow_empty=allow_empty_frames)
    if not all(math.isfinite(v) for v in (scroll_speed, transition_ms)):
        raise ValueError("时间和滚速必须是有限数值。")
    if not 1 <= scroll_speed <= 40:
        raise ValueError("lazer 滚速须在 1–40 之间。")
    # Native lazer skin: 768 - 110 = 658; legacy baseline: 402 * 1.6 = 643.2.
    time_range = 11485 / scroll_speed * (658 / 643.2)
    requested_transition = transition_ms
    if transition_ms <= 0:
        raise ValueError("切帧时长必须大于 0。")
    if fast_clear:
        transition_ms = minimum_transition_ms(scroll_speed)
    # A transition moves 1.1 complete playfield heights, including edge margins.
    fast_multiplier = 1.1 * time_range / transition_ms
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
    points = [Point(0, 500, 1), Point(start_ms - transition_ms, fast_beat, 10)]
    frame_plans = []
    slow_index = 0
    entry_start = start_ms - transition_ms
    for index, (rows, (start, end), count) in enumerate(zip(frames, frame_times, counts)):
        frame = {"pattern": rows, "start_ms": start, "end_ms": end,
                 "entry_start_ms": entry_start, "exit_end_ms": end + transition_ms}
        frame_plans.append(frame)
        if anchors[index]:
            # Brief near-stationary 500 ms segments keep the reference BPM dominant
            # even when thousands of video transitions would otherwise outweigh the lead-in.
            points.append(Point(start, 500, 0.01))
        for i in range(count):
            # Keep values unique across ALL frames, not just within one hold.
            points.append(Point(start + anchors[index] + i * 50, 60000 - slow_index * 0.01, 0.01))
            slow_index += 1
        if index == len(frames) - 1:
            points.append(Point(end, fast_beat, 10))
        else:
            next_start = frame_times[index + 1][0]
            gap = next_start - end
            if gap > 2 * transition_ms + 1e-7:
                # Clear the old frame now, then bring the next in at its own start.
                points.extend([Point(end, fast_beat, 10), Point(end + transition_ms, 500, 1),
                               Point(next_start - transition_ms, fast_beat, 10)])
                entry_start = next_start - transition_ms
            else:
                # Close neighbours share one sweep, as in the original equal-time mode.
                points.append(Point(end, fast_beat, min(10, 10 * transition_ms / gap)))
                frame["exit_end_ms"] = next_start
                entry_start = end
    points.append(Point(end_ms + transition_ms, 500, 1))
    timeline = Timeline(points)

    notes = []
    for index, frame in enumerate(frame_plans):
        drift = (timeline.position(frame["end_ms"]) - timeline.position(frame["start_ms"])) / time_range
        if drift >= 0.19:
            raise ValueError("展示时间过长，图案会接近判定线；请缩短时间范围。")
        frame["drift_playfield_fraction"] = drift
        frame["drift_at_658px"] = drift * 658
        rows = frame["pattern"]
        for row, line in enumerate(rows):
            # Row centres occupy the middle 60%; row 0 is the TOP of the picture.
            y = 0.2 + (row + 0.5) * 0.6 / len(rows)
            distance = timeline.position(frame["start_ms"]) + (1 - y) * time_range
            time = timeline.time_at(distance)
            for column, pixel in enumerate(line):
                if pixel == "#":
                    notes.append({"frame": index, "column": column, "row": row, "time_ms": time, "y": y})
    if not notes:
        raise ValueError("所有帧均为空白，至少需要一个 #；视频需要包含亮部。")
    notes.sort(key=lambda n: (n["time_ms"], n["column"]))
    base = most_common_beat_length(points, notes[-1]["time_ms"])
    if not math.isclose(base, 500, abs_tol=1e-9):
        raise ValueError("该时间组合改变了参考 BPM；请增加 start 或缩短 transition。")

    drift = max(frame["drift_playfield_fraction"] for frame in frame_plans)
    return {
        "pattern": frames[0], "frames": frame_plans, "keys": len(frames[0][0]),
        "start_ms": start_ms, "end_ms": end_ms,
        "transition_ms": transition_ms, "scroll_speed": scroll_speed,
        "requested_transition_ms": requested_transition, "fast_clear": fast_clear,
        "timing_mode": timing_mode,
        "time_range_ms": time_range, "base_beat_length_ms": base,
        "skin_assumption": "lazer default skin, downscroll, no speed/column mods",
        "drift_playfield_fraction": drift, "drift_at_658px": drift * 658,
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
        f"Version: {plan['keys']}K - Scroll speed {number(plan['scroll_speed'])} - Use NF",
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
<p>几何模型预览；不是 lazer 实机画面。速度设置、皮肤和判定会影响实际外观。</p>
<main><canvas id="view" width="360" height="768"></canvas><div>
<pre id="pattern">""" + pattern + """</pre><p id="info"></p><button id="play">播放</button>
<p><input id="seek" type="range" step="0.01"></p><output id="time"></output>
<p>白色横线是判定线；包含判定线下方区域。<br>按位置清场，不在判定时间直接隐藏音符。<br>不模拟皮肤或 Miss 淡出。</p>
</div></main><script>
const plan=""" + data + """;
const canvas=document.getElementById('view'),ctx=canvas.getContext('2d');
const seek=document.getElementById('seek'),time=document.getElementById('time');
const points=plan.points,positions=[0];
const speed=p=>plan.base_beat_length_ms/p.beat_length*p.sv;
for(let i=1;i<points.length;i++)positions.push(positions[i-1]+(points[i].time-points[i-1].time)*speed(points[i-1]));
function position(t){let i=points.length-1;while(i>0&&points[i].time>t)i--;return positions[i]+(t-points[i].time)*speed(points[i]);}
const notePositions=plan.notes.map(n=>position(n.time_ms));
function lowerBound(a,x){let lo=0,hi=a.length;while(lo<hi){let m=(lo+hi)>>>1;if(a[m]<x)lo=m+1;else hi=m;}return lo;}
seek.min=plan.start_ms-plan.transition_ms-40;seek.max=plan.end_ms+plan.transition_ms+40;seek.value=plan.start_ms;
document.getElementById('info').textContent=`${plan.keys}K · ${plan.frames.length} 帧 · 滚速 ${plan.scroll_speed} · ${plan.start_ms}–${plan.end_ms} ms；单帧最大漂移约 ${plan.drift_at_658px.toFixed(4)} px（658 px 高度）。`;
function draw(){let t=+seek.value,w=canvas.width/plan.keys;ctx.clearRect(0,0,360,768);
ctx.strokeStyle='#293047';for(let c=1;c<plan.keys;c++){ctx.beginPath();ctx.moveTo(c*w,0);ctx.lineTo(c*w,768);ctx.stroke();}
const current=position(t),lower=current+(1-772/658)*plan.time_range_ms,upper=current+(1+4/658)*plan.time_range_ms;
ctx.fillStyle='#80e0de';for(let i=lowerBound(notePositions,lower);i<plan.notes.length&&notePositions[i]<=upper;i++){const n=plan.notes[i];let y=(1-(notePositions[i]-current)/plan.time_range_ms)*658;ctx.fillRect(n.column*w+2,y-4,w-4,8);}
const index=plan.frames.findIndex(f=>t>=f.start_ms&&t<=f.end_ms);
document.getElementById('pattern').textContent=index<0?'空档 / 进场 / 换帧 / 退场':plan.frames[index].pattern.join('\\n');
ctx.fillStyle='white';ctx.fillRect(0,657,360,2);time.textContent=t.toFixed(2)+' ms'+(index<0?'':` · 第 ${index+1} 帧`);}
let playing=false,last=0;document.getElementById('play').onclick=()=>{playing=!playing;if(playing&&+seek.value>=+seek.max)seek.value=seek.min;last=performance.now();};
seek.oninput=()=>{playing=false;draw();};function tick(now){if(playing){seek.value=Math.min(+seek.max,+seek.value+now-last);if(+seek.value>=+seek.max)playing=false;draw();}last=now;requestAnimationFrame(tick);}draw();requestAnimationFrame(tick);
</script></html>"""


def write_output(plan, output, *, audio_data=None):
    output.mkdir(parents=True, exist_ok=True)
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


def main():
    parser = argparse.ArgumentParser(description="用文本像素图生成 osu!mania lazer 近似停帧谱面。")
    parser.add_argument("pattern", type=Path, help="文本图案；配合 --video 时为本地视频文件")
    parser.add_argument("--video", action="store_true", help="导入视频及音轨，自动使用极速清场")
    parser.add_argument("--fps", type=float, default=10, help="视频每秒帧数，可填小数，默认 10")
    parser.add_argument("--width", type=int, default=10, help="视频画面宽度 / 按键列，1–10，默认 10")
    parser.add_argument("--height", type=int, default=24, help="视频画面高度 / 行，1–128，默认 24")
    parser.add_argument("--start-ms", type=float, required=True, help="完整展示开始时间（ms）")
    parser.add_argument("--end-ms", type=float, help="文本图案必填；视频结束时间由 FPS 与实际帧数确定")
    parser.add_argument("--scroll-speed", type=float, default=27, help="须与 lazer 设置相同，默认 27")
    parser.add_argument("--transition-ms", type=float, default=12, help="进场/退场各自时长，默认 12 ms")
    parser.add_argument("--fast-clear", action="store_true", help="自动以合法最高速度清场，覆盖手动切帧时长")
    parser.add_argument("--output", type=Path, default=Path("output"), help="输出目录，同名生成文件会覆盖")
    args = parser.parse_args()
    try:
        if args.video:
            if args.end_ms is not None:
                raise ValueError("视频结束时间自动计算，请不要传 --end-ms。")
            from osu_paint_video import import_video
            result = import_video(args.pattern, fps=args.fps, width=args.width, height=args.height,
                                  start_ms=args.start_ms, scroll_speed=args.scroll_speed)
            plan = result["plan"]
            write_output(plan, args.output, audio_data=result["audio"])
        else:
            if args.end_ms is None:
                raise ValueError("文本图案需要 --end-ms。")
            frames = parse_frames(args.pattern.read_text(encoding="utf-8-sig"))
            plan = compile_frames(frames, args.start_ms, args.end_ms, args.scroll_speed, args.transition_ms,
                                  fast_clear=args.fast_clear)
            write_output(plan, args.output)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"已生成 {args.output.resolve() / 'pattern.osz'}")
    print(f"{plan['keys']}K / {len(plan['frames'])} 帧 / {len(plan['notes'])} 音符 / lazer 滚速 {number(args.scroll_speed)}")
    print(f"单帧最大预计漂移 {plan['drift_at_658px']:.4f} px（658 px 高度），不是精确零速。")


if __name__ == "__main__":
    main()
