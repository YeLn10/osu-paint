"""Pixel-film mania animation, with an explicit 30 FPS / custom-skin contract."""

from bisect import bisect_left
import json
import math
import struct
import zipfile
import zlib

from osu_paint import Point, Timeline


REFERENCE_FPS = 30
HIT_POSITION = 480


def compile_reference_frames(frames, start, end, scroll_speed, windows=None):
    height, keys = len(frames[0]), len(frames[0][0])
    if keys > 10 and keys not in (12, 14, 16, 18):
        raise ValueError("stable 双舞台列数须为 12、14、16 或 18。")
    if not math.isfinite(scroll_speed) or not 1 <= scroll_speed <= 40:
        raise ValueError("游戏滚速须在 1–40 之间。")
    if height + 2 > math.floor(1000 / REFERENCE_FPS):
        raise ValueError("30 FPS 参考动画最多支持 31 行；推荐使用 16×12。")
    if windows is None:
        if start is None or end is None or not all(math.isfinite(t) for t in (start, end)):
            raise ValueError("开始和结束时间必须是有限数值。")
        if abs(end - start - len(frames) * 1000 / REFERENCE_FPS) > 1:
            raise ValueError("参考动画的总时长须与 30 FPS 帧数一致。")
        starts = [math.floor(start + i * 1000 / REFERENCE_FPS + 1e-7) for i in range(len(frames))]
        windows = [(s, starts[i + 1] - height if i + 1 < len(starts) else round(end))
                   for i, s in enumerate(starts)]
    if len(windows) != len(frames):
        raise ValueError("每帧都需要开始和结束时间。")
    if any(len(w) != 2 or not all(math.isfinite(t) for t in w) or w[1] <= w[0] for w in windows):
        raise ValueError("帧时间须为有限数值，且结束大于开始。")
    windows = [(round(s), round(e)) for s, e in windows]
    start, end = windows[0][0], windows[-1][1]
    if start - height < 100:
        raise ValueError("进场前至少保留 100 ms；请推迟开始时间。")
    for i, (s, e) in enumerate(windows):
        expected = math.floor(start + i * 1000 / REFERENCE_FPS + 1e-7)
        if abs(s - expected) > 1 or (i + 1 < len(windows) and windows[i + 1][0] - e != height):
            raise ValueError("参考动画需要固定 30 FPS 时间表；请按参考预设重新导入。")
    # Fixed-speed stable uses 21*scroll*100/reference_BPM / effective_beat.
    # The supplied skin has a 480-unit judgement line instead of the default 402.
    time_range = HIT_POSITION * 600 / (21 * scroll_speed)
    fast_speed = time_range / height
    points = [Point(0, 500, 1), Point(start - height, 500 / fast_speed, 1)]
    plans, notes = [], []
    pending = [None] * keys
    for index, (rows, (s, e)) in enumerate(zip(frames, windows)):
        slow_beat = 1000000 + index
        points.append(Point(s, slow_beat, 1))
        # Unique red values preserve stable's exact-double reference-BPM grouping.
        # Compensate SV so every row still spans precisely one integer millisecond.
        beat = 500 / fast_speed * (1 + (index + 1) / (len(frames) + 1))
        points.append(Point(e, beat, fast_speed * beat / 500))
        drift = (e - s) * 500 / slow_beat / time_range
        plans.append({"pattern": rows, "start_ms": s, "end_ms": e,
                      "entry_start_ms": s - height, "exit_end_ms": e + height,
                      "drift_playfield_fraction": drift, "drift_at_658px": drift * 658})
        for row in range(height - 1, -1, -1):
            t = e + height - 1 - row
            for column, pixel in enumerate(rows[row]):
                # White is the lane background; merge consecutive black cells into LNs.
                # This avoids emitting hundreds of thousands of invisible white notes.
                if pixel == ".":
                    if pending[column] is None:
                        pending[column] = {"frame": index, "column": column, "row": row,
                                           "time_ms": t, "end_ms": t + 1, "y": (row + 1) / height}
                    else:
                        pending[column]["end_ms"] = t + 1
                elif pending[column] is not None:
                    notes.append(pending[column])
                    pending[column] = None
    notes.extend(n for n in pending if n is not None)
    if not notes:
        raise ValueError("参考动画需要至少一个黑色像素；白色由舞台背景显示。")
    notes.sort(key=lambda n: (n["time_ms"], n["column"]))
    points.append(Point(end + height, 500, 1))
    # Native stable groups positive beat lengths exactly, not at 0.001 precision.
    last_time = max(n["end_ms"] for n in notes)
    durations = {}
    for i, p in enumerate(points[:-1]):
        duration = max(0, min(points[i + 1].time, last_time) - p.time)
        durations[p.beat_length] = durations.get(p.beat_length, 0) + duration
    if max(durations, key=durations.get) != 500:
        raise ValueError("参考 BPM 改变；请在动画开始前保留更长的正常 BPM 时间。")
    drift = max(f["drift_playfield_fraction"] for f in plans)
    return {"pattern": frames[0], "frames": plans, "notes": notes,
            "points": [p.__dict__ for p in points], "keys": keys,
            "start_ms": start, "end_ms": end, "transition_ms": height,
            "requested_transition_ms": height, "fast_clear": True, "timing_mode": "free",
            "scroll_speed": scroll_speed, "time_range_ms": time_range, "base_beat_length_ms": 500,
            "target_client": "stable", "reference_animation": True, "render_fps": REFERENCE_FPS,
            "hit_position": HIT_POSITION, "drift_playfield_fraction": drift, "drift_at_658px": drift * 658,
            "skin_assumption": "supplied pixel skin; fixed scroll speed; downscroll; NF; matching 30 FPS render clock"}


def reference_sample_time(plan, time):
    if not plan["start_ms"] <= time < plan["end_ms"]:
        return time
    index = math.floor((time - plan["start_ms"]) * REFERENCE_FPS / 1000 + 1e-7)
    return plan["frames"][min(index, len(plan["frames"]) - 1)]["start_ms"]


class ReferenceGeometry:
    """Intersect actual LN bodies with the viewport, including old active LN heads."""
    def __init__(self, plan):
        self.plan = plan
        self.timeline = Timeline([Point(**p) for p in plan["points"]])
        self.lanes = [[] for _ in range(plan["keys"])]
        for note in plan["notes"]:
            self.lanes[note["column"]].append((self.timeline.position(note["time_ms"]),
                                               self.timeline.position(note["end_ms"])))
        self.ends = [[end for _, end in lane] for lane in self.lanes]

    def rectangles(self, time):
        current = self.timeline.position(time)
        distance = self.plan["time_range_ms"]
        for column, lane in enumerate(self.lanes):
            first = bisect_left(self.ends[column], current)
            for index in range(first, len(lane)):
                bottom, top = lane[index]
                if bottom >= current + distance:
                    break
                y0 = max(0, 1 - (top - current) / distance)
                y1 = min(1, 1 - (bottom - current) / distance)
                if y1 > y0:
                    yield column, y0, y1


def _png(width, height, rgba):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = (b"\0" + bytes(rgba) * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def write_reference_skin(plan, output):
    keys = plan["keys"]
    width = min(40, 640 / keys)
    settings = ["[General]", "Name: osu-paint Pixel Film", "Author: osu-paint", "Version: 2.7",
                "", "[Mania]", f"Keys: {keys}", "SplitStages: 0", "StageSeparation: 0",
                f"ColumnStart: {(640 - width * keys) / 2:g}", "HitPosition: 480",
                "ColumnWidth: " + ",".join([f"{width:g}"] * keys),
                "ColumnSpacing: " + ",".join(["0"] * (keys - 1)),
                "ColumnLineWidth: " + ",".join(["0"] * (keys + 1)),
                "BarlineHeight: 0", "ColourBarline: 255,255,255,0", "JudgementLine: 0",
                "ScorePosition: 1000", "ComboPosition: 1000", "WidthForNoteHeightScale: 40", "UpsideDown: 0",
                "StageLeft: blank", "StageRight: blank", "StageBottom: blank", "StageHint: blank",
                "LightingN: blank", "LightingL: blank", "StageLight: blank"]
    for column in range(keys):
        settings.extend([f"Colour{column + 1}: 255,255,255,255",
                         f"KeyImage{column}: blank", f"KeyImage{column}D: blank",
                         f"NoteImage{column}: pixel-white", f"NoteImage{column}H: blank",
                         f"NoteImage{column}L: pixel-black", f"NoteImage{column}T: blank",
                         f"NoteBodyStyle{column}: 0"])
    assets = {"skin.ini": ("\n".join(settings) + "\n").encode(),
              "blank.png": _png(40, 1, (0, 0, 0, 0)),
              "pixel-black.png": _png(40, 1, (0, 0, 0, 255)),
              "pixel-white.png": _png(40, 40, (255, 255, 255, 255))}
    with zipfile.ZipFile(output / "pixel-film.osk", "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in assets.items():
            archive.writestr(name, data)
    (output / "播放说明.txt").write_text(
        "本模式用真实长条音符显示黑色像素，白色由舞台背景显示。\n"
        "1. 导入 pixel-film.osk 并在 osu!stable 选择 osu-paint Pixel Film 皮肤。\n"
        "2. 导入 pattern.osz，开启 No Fail，关闭随 BPM 缩放，向下滚动。\n"
        f"3. 将游戏滚速设为 {plan['scroll_speed']:g}；将游戏渲染帧率固定为 30 FPS。\n"
        "   关闭 osu! 后，在自己的 osu!.用户名.cfg 中设置 FrameSync = Custom、CustomFrameLimit = 30，保存后重开。\n"
        "   设置步骤来源：https://osu.ppy.sh/wiki/en/Performance_troubleshooting#custom\n"
        "4. 30 FPS 仅固定刷新间隔，不自动固定刷新相位；作者演示依赖刷新落在展示段。\n"
        "   若刷新落在 12 ms 切帧段，仍会显示下落/混帧；可调整共同开始时间重新导入，但游戏抖动仍可能破坏同步。\n"
        "   谱面不能强制游戏渲染时钟，本模式不保证任意刷新条件下零残影。\n"
        "编辑器播放默认提供 30 FPS 同步几何预览；暂停拖动可检查真实过渡。\n"
        "皮肤必须单独安装：mania 音符皮肤不能依靠谱面内图片自动覆盖。\n"
        "本产物尚未通过用户客户端的实际渲染验收。\n", encoding="utf-8")


def make_reference_preview(plan):
    data = json.dumps(plan, ensure_ascii=False).replace("<", "\\u003c")
    return """<!doctype html><meta charset="utf-8"><title>mania 像素长条动画</title>
<style>body{background:#18202c;color:white;font:16px system-ui;margin:24px}canvas{background:white;max-width:90vw}input{width:640px;max-width:90vw}</style>
<p>真实长条音符的几何预览；游戏需配套皮肤与 30 FPS 同步刷新。暂停拖动可查看滚动过渡。</p>
<canvas id="view" width="640" height="480"></canvas><p><button id="play">播放 / 暂停</button>
<label><input id="sync" type="checkbox" checked style="width:auto">30 FPS 同步</label></p>
<input id="seek" type="range" step="0.01"><output id="time"></output><script>
const plan=""" + data + """, points=plan.points, times=points.map(p=>p.time), distances=[0];
const speed=p=>500/p.beat_length*p.sv;
for(let i=1;i<points.length;i++)distances.push(distances[i-1]+(points[i].time-points[i-1].time)*speed(points[i-1]));
function lower(a,x){let l=0,r=a.length;while(l<r){let m=(l+r)>>>1;if(a[m]<x)l=m+1;else r=m;}return l;}
function position(t){let i=lower(times,t);if(i===points.length||points[i].time>t)i--;i=Math.max(0,i);return distances[i]+(t-points[i].time)*speed(points[i]);}
const lanes=Array.from({length:plan.keys},()=>[]);
for(const n of plan.notes)lanes[n.column].push([position(n.time_ms),position(n.end_ms)]);
const ends=lanes.map(a=>a.map(n=>n[1])),seek=document.getElementById('seek'),ctx=document.getElementById('view').getContext('2d');
seek.min=plan.start_ms;seek.max=plan.end_ms;seek.value=plan.start_ms;
let playing=false,last=0;
function draw(){let t=+seek.value;if(playing&&document.getElementById('sync').checked&&t<plan.end_ms){let i=Math.floor((t-plan.start_ms)*30/1000+1e-7);t=plan.frames[Math.min(i,plan.frames.length-1)].start_ms;}
ctx.fillStyle='white';ctx.fillRect(0,0,640,480);ctx.fillStyle='black';const s=position(t),r=plan.time_range_ms,w=640/plan.keys;
for(let c=0;c<plan.keys;c++)for(let i=lower(ends[c],s);i<lanes[c].length&&lanes[c][i][0]<s+r;i++){let n=lanes[c][i],a=Math.max(0,1-(n[1]-s)/r),b=Math.min(1,1-(n[0]-s)/r);if(b>a)ctx.fillRect(c*w,a*480,w,(b-a)*480);}
document.getElementById('time').textContent=t.toFixed(2)+' ms';}
document.getElementById('play').onclick=()=>{playing=!playing;if(+seek.value>=plan.end_ms)seek.value=plan.start_ms;last=performance.now();draw();};
seek.oninput=()=>{playing=false;draw();};document.getElementById('sync').onchange=draw;
function tick(now){if(playing){seek.value=Math.min(plan.end_ms,+seek.value+now-last);if(+seek.value>=plan.end_ms)playing=false;draw();}last=now;requestAnimationFrame(tick);}draw();requestAnimationFrame(tick);
</script>"""
