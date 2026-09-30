"""Native desktop editor for the existing osu!mania pattern compiler."""

from bisect import bisect_left, bisect_right
from pathlib import Path
import base64
import math
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from osu_paint import Point, Timeline, compile_frames, number, parse_frames, write_output
from osu_paint_video import (ImportCancelled, import_video as read_video, preview_video_frame,
                             resolve_video_options)
from osu_paint_audio import AudioPreview


HEART = [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."]
OUTPUT_FILES = ("pattern.osz", "pattern.osu", "silence.wav", "preview.html", "report.json")
BG = "#101522"
PANEL = "#192131"
INK = "#edf1fa"
MUTED = "#a0aec3"
ACCENT = "#ef76a7"
MINT = "#70dfcc"


class PaintApp:
    def __init__(self, root):
        self.root = root
        self.frames = [HEART.copy()]
        self.frame_times = [["2000", "4000"]]
        self.uniform_times = ["2000", "4000"]
        self.free_times_initialized = False
        self.syncing_fields = False
        self.selected = 0
        self.dirty = False
        self.plan = None
        self.playing = False
        self.exporting = False
        self.importing = False
        self.import_dialog = None
        self.import_results = queue.Queue()
        self.import_cancel = threading.Event()
        self.video = None
        self.audio_data = None
        self.audio_player = AudioPreview()
        self.root.bind("<Destroy>", self._destroy_audio, add="+")
        self.preview_job = None
        self.export_results = queue.Queue()
        self.last_output = None
        self.stroke_value = "#"
        self.root.title("osu!paint — 桌面图案编辑器")
        self.scale = self.root.winfo_fpixels("1i") / 96
        width = min(round(1120 * self.scale), self.root.winfo_screenwidth() - 60)
        height = min(round(820 * self.scale), self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(round(960 * self.scale), width), min(round(720 * self.scale), height))
        self.root.configure(background=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._build()
        self._update_editor()
        self._refresh_preview()
        self.tick_job = self.root.after(16, self._tick)

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background=BG,
                        foreground=INK, bordercolor=PANEL)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("TButton", background="#29354a", padding=(12, 7), borderwidth=0)
        style.map("TButton", background=[("active", "#394962")],
                  foreground=[("disabled", "#68778e")])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG)
        style.map("Accent.TButton", background=[("active", "#ff9cc4"), ("disabled", PANEL)])
        style.configure("TEntry", fieldbackground=PANEL, insertcolor=INK, padding=7)
        style.configure("TCombobox", fieldbackground=PANEL, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", INK)])
        style.configure("Horizontal.TScale", background=BG, troughcolor=PANEL)

    def _build(self):
        header = ttk.Frame(self.root, padding=(24, 16, 24, 12))
        header.pack(fill="x")
        ttk.Label(header, text="osu!paint", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  /  MANIA SV STUDIO", style="Muted.TLabel").pack(side="left", pady=(9, 0))
        for label, command in [("保存项目", self.save_pattern), ("打开", self.open_pattern),
                               ("编辑文本", self.edit_text), ("导入视频", self.import_video)]:
            ttk.Button(header, text=label, command=command).pack(side="right", padx=(8, 0))

        body = ttk.Frame(self.root, padding=(24, 0, 24, 0))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3, uniform="columns")
        body.columnconfigure(1, weight=2, uniform="columns")
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body, padding=(0, 0, 24, 0))
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        tools = ttk.Frame(left)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(tools, text="像素画布", style="Heading.TLabel").pack(side="left")
        ttk.Button(tools, text="新建", command=self.new_pattern).pack(side="right")
        self.editor_info = tk.StringVar()
        ttk.Label(left, textvariable=self.editor_info, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.canvas = tk.Canvas(left, background=PANEL, highlightthickness=0, height=240)
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda event: self._draw_grid())
        self.canvas.bind("<Button-1>", self._begin_stroke)
        self.canvas.bind("<B1-Motion>", self._paint)
        self.canvas.bind("<Button-3>", self._begin_stroke)
        self.canvas.bind("<B3-Motion>", self._paint)
        ttk.Label(left, text="左键点按 / 拖动绘制，右键擦除 · 每列对应一个按键列", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 12))

        frame_bar = ttk.Frame(left)
        frame_bar.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(frame_bar, text="动画帧", style="Heading.TLabel").pack(side="left")
        self.delete_button = ttk.Button(frame_bar, text="删除", command=self.delete_frame)
        self.delete_button.pack(side="right")
        ttk.Button(frame_bar, text="复制", command=lambda: self.add_frame(True)).pack(side="right", padx=6)
        ttk.Button(frame_bar, text="＋ 空白帧", command=self.add_frame).pack(side="right")
        frame_box = ttk.Frame(left)
        frame_box.grid(row=5, column=0, sticky="ew")
        self.frame_list = tk.Listbox(frame_box, height=3, background=PANEL, foreground=INK,
                                    selectbackground="#593750", selectforeground=INK,
                                    font=("Microsoft YaHei UI", 10), borderwidth=0,
                                    highlightthickness=0, exportselection=False)
        self.frame_list.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame_box, command=self.frame_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.frame_list.configure(yscrollcommand=scrollbar.set)
        self.frame_list.bind("<<ListboxSelect>>", self.select_frame)

        timing_bar = ttk.Frame(left)
        timing_bar.grid(row=6, column=0, sticky="ew", pady=(12, 6))
        self.timing_mode = tk.StringVar(value="均分模式")
        ttk.Combobox(timing_bar, textvariable=self.timing_mode, values=("均分模式", "自由模式"),
                     state="readonly", width=9).pack(side="left")
        self.fast_clear = tk.BooleanVar(value=True)
        ttk.Checkbutton(timing_bar, text="极速清场", variable=self.fast_clear,
                        command=self._timing_options_changed).pack(side="left", padx=8)
        ttk.Button(timing_bar, text="参数说明", command=self.explain_timing).pack(side="right")
        self.target_client = tk.StringVar(value="lazer")
        ttk.Combobox(timing_bar, textvariable=self.target_client, values=("lazer", "stable"),
                     state="readonly", width=7).pack(side="left")
        self.target_client.trace_add("write", lambda *args: self._parameter_changed("target_client"))
        settings = ttk.Frame(left)
        settings.grid(row=7, column=0, sticky="ew")
        self.fields = {}
        self.time_labels = []
        self.entries = {}
        for i, (key, label, value) in enumerate([
                ("start_ms", "展示开始 / ms", "2000"), ("end_ms", "展示结束 / ms", "4000"),
                ("transition_ms", "切帧时长 / ms", "12"), ("scroll_speed", "游戏滚速 / 1–40", "27")]):
            settings.columnconfigure(i, weight=1, uniform="fields")
            field_label = ttk.Label(settings, text=label, style="Muted.TLabel")
            field_label.grid(row=0, column=i, sticky="w", padx=(0, 8))
            self.time_labels.append(field_label)
            variable = tk.StringVar(value=value)
            self.fields[key] = variable
            entry = ttk.Entry(settings, textvariable=variable, width=9)
            entry.grid(row=1, column=i, sticky="ew", padx=(0, 8), pady=(6, 0))
            self.entries[key] = entry
            variable.trace_add("write", lambda *args, field=key: self._parameter_changed(field))
        self.entries["transition_ms"].configure(state="disabled")
        self.timing_mode.trace_add("write", self._mode_changed)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        ttk.Label(right, text="舞台预览", style="Heading.TLabel").grid(row=0, column=0, sticky="w", pady=(8, 6))
        ttk.Label(right, text="位置模拟 · 非游戏实机画面", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.preview = tk.Canvas(right, background="#0b101b", highlightthickness=0, width=300, height=360)
        self.preview.grid(row=2, column=0, sticky="nsew")
        self.preview.bind("<Configure>", lambda event: self._draw_preview())
        self.seek_time = tk.DoubleVar(value=2000)
        self.seek = ttk.Scale(right, variable=self.seek_time, command=self._seek_changed)
        self.seek.grid(row=3, column=0, sticky="ew", pady=(10, 6))
        playback = ttk.Frame(right)
        playback.grid(row=4, column=0, sticky="ew")
        self.play_button = ttk.Button(playback, text="▶ 播放", command=self.toggle_play)
        self.play_button.pack(side="left")
        ttk.Button(playback, text="回到当前帧", command=self.seek_selected).pack(side="left", padx=8)
        self.time_label = tk.StringVar()
        ttk.Label(right, textvariable=self.time_label, style="Muted.TLabel").grid(row=5, column=0, sticky="w", pady=(8, 4))
        ttk.Label(right, text="近似停帧 · 向下滚动 · 同步游戏滚速 · 开启 No Fail。\nstable 为实验兼容，关闭随 BPM 缩放；高行数需降低 FPS。",
                  style="Muted.TLabel", font=("Microsoft YaHei UI", 9)).grid(row=6, column=0, sticky="w", pady=(6, 0))

        footer = ttk.Frame(self.root, padding=(24, 18, 24, 16))
        footer.pack(fill="x")
        ttk.Label(footer, text="导出目录", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        footer.columnconfigure(0, weight=1)
        self.output_dir = tk.StringVar(value=str(Path.home() / "osu-paint-output"))
        ttk.Entry(footer, textvariable=self.output_dir).grid(row=1, column=0, sticky="ew")
        ttk.Button(footer, text="浏览…", command=self.choose_output).grid(row=1, column=1, padx=8)
        self.folder_button = ttk.Button(footer, text="打开结果", command=self.open_output, state="disabled")
        self.folder_button.grid(row=1, column=2, padx=(0, 8))
        self.export_button = ttk.Button(footer, text="导出 .osz  →", style="Accent.TButton", command=self.export)
        self.export_button.grid(row=1, column=3)
        self.status = tk.StringVar()
        self.status_label = ttk.Label(footer, textvariable=self.status, style="Muted.TLabel", wraplength=round(1040 * self.scale))
        self.status_label.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _show_time_fields(self):
        free = self.timing_mode.get() == "自由模式"
        values = self.frame_times[self.selected] if free else self.uniform_times
        self.syncing_fields = True
        for i, key in enumerate(("start_ms", "end_ms")):
            self.fields[key].set(values[i])
            self.time_labels[i].configure(text=("本帧开始 / ms", "本帧结束 / ms")[i] if free
                                          else ("展示开始 / ms", "展示结束 / ms")[i])
        self.syncing_fields = False

    def _parameter_changed(self, key):
        if self.syncing_fields:
            return
        alignment_removed = key == "target_client" and self.target_client.get() == "lazer" and self._clear_video_alignment()
        if key in ("start_ms", "end_ms"):
            values = self.frame_times[self.selected] if self.timing_mode.get() == "自由模式" else self.uniform_times
            values[0 if key == "start_ms" else 1] = self.fields[key].get()
        self._changed()
        if alignment_removed:
            self._refresh_preview()
            notice = "已撤销游戏帧率切帧设置；需重新导入视频才能重新对齐。"
            self._status(notice if self.plan is not None else f"{self.status.get()} {notice}", error=self.plan is None)

    def _clear_video_alignment(self):
        if self.video is None or self.video.get("game_fps") is None:
            return False
        self.video = {key: value for key, value in self.video.items()
                      if key not in ("game_fps", "frame_fps", "requested_fps", "requested_height")}
        return True

    def _mode_changed(self, *args):
        if self.syncing_fields:
            return
        if self.timing_mode.get() == "自由模式" and not self.free_times_initialized:
            try:
                plan = compile_frames(self.frames, *map(float, self.uniform_times),
                                      float(self.fields["scroll_speed"].get()), float(self.fields["transition_ms"].get()),
                                      fast_clear=self.fast_clear.get(), target_client=self.target_client.get())
            except ValueError:
                pass
            else:
                self.frame_times = [[number(f["start_ms"]), number(f["end_ms"])] for f in plan["frames"]]
            self.free_times_initialized = True
        self._show_time_fields()
        self._changed()

    def _timing_options_changed(self):
        self.entries["transition_ms"].configure(state="disabled" if self.fast_clear.get() else "normal")
        self._changed()

    def explain_timing(self):
        messagebox.showinfo("时间与滚速说明",
                            "均分模式：所有帧平分总时间，先扣除切帧时间。\n"
                            "自由模式：选中一帧，填写本帧开始、结束时间。允许留空档，不能重叠；间隔须足够切帧。\n\n"
                            "切帧时长：推进图案所需的时间。越短移动越快，越长越容易看到下落。远离的两帧分别退场、进场。\n"
                            "极速清场：自动用合法最高速度计算时长，覆盖手动切帧值；滚速 27 时约 0.575 ms。不能保证零过渡画面。\n\n"
                            "stable：整数毫秒音符，各行先排整数时间，再计算分段滚速。连续相同画面复用音符。\n"
                            "stable 使用分段滚速；默认滚速下 24 行切帧为 25 ms，可使用 10 FPS。仍有滚动切换。\n"
                            "按游戏帧率安排切帧：按指定渲染 FPS 调整切帧位置，必要时降低行数或采样 FPS；导入前会显示实际参数。\n"
                            "需要在游戏中限帧并对齐刷新；播放时预览仍按真实时间绘制。\n\n"
                            "游戏滚速：必须与游戏设置一致。它决定时间距离如何换算成舞台位置，不是动画帧率；"
                            "更改后会重新计算音符与变速点，不会改变你填写的展示时间。\n\n"
                            "保存为 JSON 项目可保留全部时间与参数；TXT 仅保存图案。",
                            parent=self.root)

    def _status(self, text, error=False):
        self.status.set(text)
        self.status_label.configure(foreground=ACCENT if error else MUTED)

    def _update_editor(self):
        rows = self.frames[self.selected]
        self.editor_info.set(f"{len(rows[0])}K  ·  {len(rows)} 行  ·  第 {self.selected + 1} / {len(self.frames)} 帧")
        self.frame_list.delete(0, "end")
        items = []
        for i, frame in enumerate(self.frames):
            timing = f"  ·  {self.frame_times[i][0]}–{self.frame_times[i][1]} ms" if self.timing_mode.get() == "自由模式" else ""
            count = sum(row.count('#') for row in frame)
            items.append(f"  {i + 1:02d}    {'●' if i == self.selected else '○'}    {count} 个音符{timing}")
        self.frame_list.insert("end", *items)
        self.frame_list.selection_set(self.selected)
        self.frame_list.see(self.selected)
        self.delete_button.configure(state="normal" if len(self.frames) > 1 else "disabled")
        self.root.title(f"{'* ' if self.dirty else ''}osu!paint — 桌面图案编辑器")
        self._draw_grid()

    def _grid_geometry(self):
        rows = self.frames[self.selected]
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        cell = max(1, min((width - 32 * self.scale) / len(rows[0]),
                          (height - 36 * self.scale) / len(rows), 52 * self.scale))
        return (width - cell * len(rows[0])) / 2, (height - cell * len(rows)) / 2 - 6 * self.scale, cell

    def _draw_grid(self):
        self.canvas.delete("all")
        x, y, size = self._grid_geometry()
        gap = min(2 * self.scale, size / 8)
        for r, row in enumerate(self.frames[self.selected]):
            for c, pixel in enumerate(row):
                self.canvas.create_rectangle(x + c * size + gap, y + r * size + gap,
                                             x + (c + 1) * size - gap, y + (r + 1) * size - gap,
                                             fill=ACCENT if pixel == "#" else "#253146", outline="")
        for c in range(len(self.frames[self.selected][0])):
            self.canvas.create_text(x + (c + 0.5) * size, y + len(self.frames[self.selected]) * size + 14 * self.scale,
                                    text=str(c + 1), fill=MUTED, font=("Segoe UI", 9))

    def _cell_at(self, event):
        x, y, size = self._grid_geometry()
        col, row = int((event.x - x) // size), int((event.y - y) // size)
        rows = self.frames[self.selected]
        return (row, col) if 0 <= row < len(rows) and 0 <= col < len(rows[0]) else None

    def _begin_stroke(self, event):
        cell = self._cell_at(event)
        if cell is not None:
            row, col = cell
            self.stroke_value = "." if event.num == 3 or self.frames[self.selected][row][col] == "#" else "#"
            self._paint(event)

    def _paint(self, event):
        cell = self._cell_at(event)
        if cell is None:
            return
        row, col = cell
        line = self.frames[self.selected][row]
        if line[col] != self.stroke_value:
            self.frames[self.selected][row] = line[:col] + self.stroke_value + line[col + 1:]
            self._changed()

    def _changed(self):
        self.dirty = True
        self._update_editor()
        self._schedule_preview()

    def select_frame(self, event=None):
        selection = self.frame_list.curselection()
        if selection and selection[0] != self.selected:
            self.selected = selection[0]
            self._show_time_fields()
            self._update_editor()
            self.seek_selected()

    def add_frame(self, duplicate=False):
        rows = self.frames[self.selected]
        frame = rows.copy() if duplicate else ["." * len(rows[0]) for _ in rows]
        try:
            start, end = map(float, self.frame_times[self.selected])
            gap = self.plan["transition_ms"] if self.plan is not None else 12
            window = [number(end + gap), number(end + gap + max(1, end - start))]
        except ValueError:
            window = ["", ""]
        self.selected += 1
        self.frames.insert(self.selected, frame)
        self.frame_times.insert(self.selected, window)
        self._show_time_fields()
        self._changed()

    def delete_frame(self):
        if len(self.frames) > 1:
            self.frames.pop(self.selected)
            self.frame_times.pop(self.selected)
            self.selected = min(self.selected, len(self.frames) - 1)
            self._show_time_fields()
            self._changed()

    def _can_discard(self):
        return not self.dirty or messagebox.askyesno("未保存的项目", "当前图案或时间参数尚未保存。要放弃修改吗？", parent=self.root)

    def new_pattern(self):
        if not self._can_discard():
            return
        keys = simpledialog.askinteger("新建画布", "按键列数（1–18）：", initialvalue=7, minvalue=1, maxvalue=18, parent=self.root)
        if keys is None:
            return
        try:
            parse_frames("#" * keys)
        except ValueError as error:
            messagebox.showerror("按键列数无效", str(error), parent=self.root)
            return
        rows = simpledialog.askinteger("新建画布", "图案行数：", initialvalue=6, minvalue=1, parent=self.root)
        if rows is not None:
            self.video, self.audio_data = None, None
            self.frames, self.selected = [["." * keys for _ in range(rows)]], 0
            self.frame_times = [self.uniform_times.copy()]
            self.free_times_initialized = False
            self._show_time_fields()
            self._changed()

    def load_text(self, text, *, keep_video=True):
        frames = parse_frames(text, allow_empty=keep_video and self.video is not None)
        alignment_removed = False
        if keep_video and self.video is not None:
            if len(frames[0]) > 128:
                raise ValueError("视频项目的画面高度须为 1–128 行。")
            if (len(frames[0]), len(frames[0][0])) != (self.video["height"], self.video["width"]):
                alignment_removed = self._clear_video_alignment()
            self.video = dict(self.video, width=len(frames[0][0]), height=len(frames[0]))
        if not keep_video:
            self.video, self.audio_data = None, None
        if len(frames) != len(self.frames):
            self.frame_times = self.frame_times[:len(frames)]
            while len(self.frame_times) < len(frames):
                try:
                    start = float(self.frame_times[-1][1]) + 12
                    self.frame_times.append([number(start), number(start + 2000)])
                except ValueError:
                    self.frame_times.append(["", ""])
        self.frames, self.selected = frames, 0
        self._show_time_fields()
        self._changed()
        if alignment_removed:
            self._refresh_preview()
            notice = "画布尺寸已改变，已撤销游戏帧率切帧设置；需重新导入视频才能重新对齐。"
            self._status(notice if self.plan is not None else f"{self.status.get()} {notice}", error=self.plan is None)

    def _text(self):
        return "\n---\n".join("\n".join(frame) for frame in self.frames) + "\n"

    def _project_data(self):
        settings = {key: variable.get() for key, variable in self.fields.items()}
        settings["start_ms"], settings["end_ms"] = self.uniform_times
        data = {"format": "osu-paint", "version": 1, "frames": self.frames,
                "frame_times": self.frame_times, "timing_mode": self.timing_mode.get(),
                "settings": settings, "fast_clear": self.fast_clear.get(), "target_client": self.target_client.get()}
        if self.video is not None:
            data.update(version=2, video=self.video.copy(),
                        audio=base64.b64encode(self.audio_data).decode("ascii") if self.audio_data is not None else None)
        return data

    def load_project(self, data):
        try:
            if data["format"] != "osu-paint" or data["version"] not in (1, 2):
                raise ValueError("不支持的项目版本。")
            video, audio = None, None
            target_client = data.get("target_client", "lazer")
            if target_client not in ("lazer", "stable"):
                raise ValueError("项目中的目标客户端无效。")
            if data["version"] == 2:
                video = data["video"]
                if not isinstance(video, dict) or not isinstance(video["filename"], str):
                    raise ValueError("项目中的视频信息无效。")
                if video.get("reference_animation"):
                    raise ValueError("此项目使用已撤销的参考动画模式，请从原视频重新导入。")
                effective = resolve_video_options(fps=video["fps"], width=video["width"], height=video["height"],
                                                  start_ms=video["start_ms"], scroll_speed=float(data["settings"]["scroll_speed"]),
                                                  target_client=target_client, game_fps=video.get("game_fps"))
                if video.get("game_fps") is not None and (
                        effective["height"] != video["height"] or not math.isclose(effective["fps"], video["fps"], abs_tol=1e-9)):
                    raise ValueError("项目中的游戏帧率优化参数与实际画面不一致，请从原视频重新导入。")
                if not math.isfinite(video["duration_ms"]) or video["duration_ms"] <= 0:
                    raise ValueError("项目中的视频时长无效。")
                if data["audio"] is not None:
                    audio = base64.b64decode(data["audio"], validate=True)
                    if not audio.startswith(b"OggS"):
                        raise ValueError("项目中的音轨无效。")
                video = video.copy()
            frames = parse_frames("\n---\n".join("\n".join(frame) for frame in data["frames"]), allow_empty=video is not None)
            if video is not None and (len(frames[0]), len(frames[0][0])) != (video["height"], video["width"]):
                raise ValueError("视频分辨率与项目画面不一致。")
            windows = data["frame_times"]
            if len(windows) != len(frames) or any(len(w) != 2 for w in windows):
                raise ValueError("项目中的帧时间不完整。")
            windows = [[str(value) for value in window] for window in windows]
            settings = {key: str(data["settings"][key]) for key in self.fields}
            mode = data["timing_mode"]
            if mode not in ("均分模式", "自由模式") or not isinstance(data["fast_clear"], bool):
                raise ValueError("项目中的模式设置无效。")
        except (KeyError, TypeError) as error:
            raise ValueError("无法识别此项目文件。") from error
        self.video, self.audio_data = video, audio
        self.frames, self.frame_times, self.selected = frames, windows, 0
        self.uniform_times = [settings["start_ms"], settings["end_ms"]]
        self.free_times_initialized = True
        self.syncing_fields = True
        self.target_client.set(target_client)
        self.timing_mode.set(mode)
        self.fast_clear.set(data["fast_clear"])
        for key, value in settings.items():
            self.fields[key].set(value)
        self._show_time_fields()
        self._timing_options_changed()

    def open_pattern(self):
        if not self._can_discard():
            return
        filename = filedialog.askopenfilename(parent=self.root, title="打开项目或文本图案",
                                             filetypes=[("项目 / 文本图案", "*.json *.txt"), ("所有文件", "*.*")])
        if not filename:
            return
        try:
            text = Path(filename).read_text(encoding="utf-8-sig")
            if Path(filename).suffix.lower() == ".json":
                self.load_project(json.loads(text))
            else:
                self.load_text(text, keep_video=False)
        except (OSError, ValueError) as error:
            messagebox.showerror("无法打开图案", str(error), parent=self.root)
            return
        self.dirty = False
        self._update_editor()

    def save_pattern(self):
        try:
            parse_frames(self._text(), allow_empty=self.video is not None)
        except ValueError as error:
            messagebox.showerror("图案还不能保存", str(error), parent=self.root)
            return
        filename = filedialog.asksaveasfilename(parent=self.root, title="保存项目（JSON 保留时间参数）",
                                              defaultextension=".json",
                                              filetypes=[("osu-paint 项目", "*.json"), ("仅文本图案", "*.txt")])
        if not filename:
            return
        try:
            text_only = Path(filename).suffix.lower() == ".txt"
            content = self._text() if text_only else json.dumps(self._project_data(), ensure_ascii=False, indent=2)
            Path(filename).write_text(content, encoding="utf-8")
        except OSError as error:
            messagebox.showerror("保存失败", str(error), parent=self.root)
            return
        self.dirty = text_only and (self.timing_mode.get() == "自由模式" or self.video is not None)
        self._update_editor()
        self._status(f"图案已保存：{filename}（TXT 不保存音轨与时间参数，请用 JSON 保存项目）" if text_only
                     else f"项目已保存：{filename}（包含各帧时间、参数及已导入的音轨）")

    def import_video(self):
        if self.exporting or self.importing:
            messagebox.showinfo("任务正在运行", "请等当前导入或导出完成。", parent=self.root)
            return
        if not self._can_discard():
            return
        filename = filedialog.askopenfilename(parent=self.root, title="导入视频及音乐",
                                             filetypes=[("视频", "*.mp4 *.mkv *.webm *.avi *.mov *.wmv *.m4v"),
                                                        ("所有文件", "*.*")])
        if not filename:
            return
        dialog = self.import_dialog = tk.Toplevel(self.root)
        dialog.title("视频 → 音符动画 + 音乐")
        dialog.configure(background=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        panel = ttk.Frame(dialog, padding=20)
        panel.pack(side="left", fill="both", expand=True)
        preview_panel = ttk.Frame(dialog, padding=(0, 20, 20, 20))
        preview_panel.pack(side="right", fill="both")
        ttk.Label(preview_panel, text="所选帧原画面", style="Heading.TLabel").pack(anchor="w")
        self.video_source_canvas = tk.Canvas(preview_panel, width=320, height=180, background="#000", highlightthickness=0)
        self.video_source_canvas.pack(pady=(8, 12))
        self.video_preview_label = tk.StringVar(value="填写帧序号后点击预览；参数修改后需刷新。")
        ttk.Label(preview_panel, textvariable=self.video_preview_label, wraplength=320, style="Muted.TLabel").pack(anchor="w")
        self.video_result_canvas = tk.Canvas(preview_panel, width=320, height=180, background="#000", highlightthickness=0)
        self.video_result_canvas.pack(pady=8)
        self.video_preview_result = None
        ttk.Label(panel, text=Path(filename).name, style="Heading.TLabel", wraplength=480).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        self.video_fields = {}
        inputs = []
        for row, (key, label, value) in enumerate([
                ("fps", "每秒帧数 / FPS（可填小数，≤60）", "10"),
                ("width", "画面宽度 / 列（1–18）", "10"),
                ("height", "画面高度 / 行（1–128）", "24"),
                ("start_ms", "视频与音乐开始 / ms", self.uniform_times[0]),
                ("threshold", "黑白阈值 / 0–255", "128"),
                ("brightness", "亮度 / -255–255", "0"),
                ("contrast", "对比度 / >0–5", "1")], 1):
            ttk.Label(panel, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 16), pady=5)
            variable = self.video_fields[key] = tk.StringVar(value=value)
            entry = ttk.Entry(panel, textvariable=variable, width=12)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            inputs.append(entry)
        self.video_invert = tk.BooleanVar(value=False)
        invert = ttk.Checkbutton(panel, text="亮暗反转", variable=self.video_invert)
        invert.grid(row=8, column=0, columnspan=2, sticky="w", pady=5)
        inputs.append(invert)
        self.video_fit = tk.StringVar(value="拉伸")
        self.video_target = tk.StringVar(value=self.target_client.get())
        for row, label, variable, choices in [(9, "缩放方式", self.video_fit, ("拉伸", "等比留边", "等比裁剪")),
                                               (10, "目标客户端", self.video_target, ("lazer", "stable"))]:
            ttk.Label(panel, text=label, style="Muted.TLabel").grid(row=row, column=0, sticky="w")
            combo = ttk.Combobox(panel, textvariable=variable, values=choices, state="readonly", width=12)
            combo.grid(row=row, column=1, pady=5)
            inputs.append(combo)
        self.video_game_fps = tk.StringVar(value="60")
        ttk.Label(panel, text="游戏渲染 FPS（60–999）", style="Muted.TLabel").grid(row=11, column=0, sticky="w")
        game_entry = ttk.Spinbox(panel, textvariable=self.video_game_fps, from_=60, to=999, width=12)
        game_entry.grid(row=11, column=1, pady=5)
        inputs.append(game_entry)
        self.video_game_sync = tk.BooleanVar(value=self.video_target.get() == "stable")
        game_sync = ttk.Checkbutton(panel, text="按游戏帧率安排切帧（必要时降低行数）", variable=self.video_game_sync)
        game_sync.grid(row=12, column=0, columnspan=2, sticky="w", pady=5)
        inputs.append(game_sync)
        self.video_effective_label = tk.StringVar()
        ttk.Label(panel, textvariable=self.video_effective_label, wraplength=480, style="Muted.TLabel").grid(
            row=13, column=0, columnspan=2, sticky="w", pady=5)
        self.video_frame_index = tk.StringVar(value="1")
        ttk.Label(panel, text="预览帧序号 / 从 1 开始", style="Muted.TLabel").grid(row=14, column=0, sticky="w", pady=(12, 0))
        frame_entry = ttk.Entry(panel, textvariable=self.video_frame_index, width=12)
        frame_entry.grid(row=14, column=1, pady=(12, 0))
        inputs.append(frame_entry)
        self.import_status = tk.StringVar(value="导入会替换当前画布；失败或取消时保留原项目。")
        ttk.Label(panel, textvariable=self.import_status, wraplength=480, style="Muted.TLabel").grid(
            row=15, column=0, columnspan=2, sticky="w", pady=8)
        buttons = ttk.Frame(panel)
        buttons.grid(row=16, column=0, columnspan=2, sticky="e", pady=(8, 0))

        def request_options():
            options = {key: (int(variable.get()) if key in ("width", "height") else float(variable.get()))
                       for key, variable in self.video_fields.items()}
            options["scroll_speed"] = float(self.fields["scroll_speed"].get())
            options.update(invert=self.video_invert.get(),
                           fit={"拉伸": "stretch", "等比留边": "contain", "等比裁剪": "cover"}[self.video_fit.get()],
                           target_client=self.video_target.get())
            if self.video_target.get() == "stable" and self.video_game_sync.get():
                options["game_fps"] = int(self.video_game_fps.get())
            return options

        def option_controls():
            stable = self.video_target.get() == "stable"
            game_sync.configure(state="normal" if stable else "disabled")
            game_entry.configure(state="normal" if stable and self.video_game_sync.get() else "disabled")

        def describe_options(*args):
            self.video_preview_label.set("参数或帧已修改，请点击预览刷新。")
            if self.importing:
                return
            option_controls()
            try:
                requested = request_options()
                effective = resolve_video_options(**requested)
            except ValueError as error:
                self.video_effective_label.set(f"参数无效：{error}")
                return
            text = f"实际导入：{effective['width']} × {effective['height']} 行 · {number(effective['fps'])} FPS"
            if "game_fps" in requested:
                text += (f"（请求 {requested['width']} × {requested['height']} 行 · {number(requested['fps'])} FPS）\n"
                         f"游戏 {requested['game_fps']} FPS；需要游戏限帧和刷新对齐。")
            self.video_effective_label.set(text)

        def target_changed(*args):
            self.video_game_sync.set(self.video_target.get() == "stable")

        for variable in [*self.video_fields.values(), self.video_invert, self.video_fit, self.video_frame_index,
                         self.video_target, self.video_game_fps, self.video_game_sync]:
            variable.trace_add("write", describe_options)
        self.video_target.trace_add("write", target_changed)
        self.video_option_controls = option_controls

        def cancel():
            if self.importing:
                self.import_cancel.set()
                self.import_status.set("正在取消并回收视频处理进程…")
                self.video_cancel_button.configure(state="disabled")
            else:
                dialog.destroy()
                self.import_dialog = None

        def start(preview=False):
            if self.importing:
                return
            try:
                options = request_options()
                resolve_video_options(**options)
                frame_index = int(self.video_frame_index.get()) - 1 if preview else None
            except ValueError as error:
                messagebox.showerror("视频参数无效", str(error), parent=dialog)
                return
            self._stop()
            self.importing = True
            self.import_job = "preview" if preview else "import"
            self.import_cancel.clear()
            for entry in inputs:
                entry.configure(state="disabled")
            self.video_start_button.configure(state="disabled")
            self.video_preview_button.configure(state="disabled")
            self.import_status.set("正在准备视频处理…")

            def run():
                try:
                    if preview:
                        result = preview_video_frame(filename, frame_index=frame_index, **options, cancel=self.import_cancel)
                    else:
                        result = read_video(filename, **options, cancel=self.import_cancel,
                                            progress=lambda message: self.import_results.put(("progress", message)))
                except Exception as error:
                    self.import_results.put(("finished", (None, error)))
                else:
                    self.import_results.put(("finished", (result, None)))

            threading.Thread(target=run, daemon=True).start()

        self.video_cancel_button = ttk.Button(buttons, text="取消", command=cancel)
        self.video_cancel_button.pack(side="left", padx=8)
        self.video_start_button = ttk.Button(buttons, text="导入视频和音乐", command=start, style="Accent.TButton")
        self.video_start_button.pack(side="left")
        self.video_preview_button = ttk.Button(preview_panel, text="预览所选帧", command=lambda: start(preview=True))
        self.video_preview_button.pack(anchor="e", pady=8)
        self.video_inputs = inputs
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        describe_options()

    def _apply_video(self, result):
        plan = result["plan"]
        self.video, self.audio_data = result["video"].copy(), result["audio"]
        self.frames = [frame["pattern"].copy() for frame in plan["frames"]]
        self.frame_times = [[number(frame["start_ms"]), number(frame["end_ms"])] for frame in plan["frames"]]
        self.uniform_times = [number(plan["start_ms"]), number(plan["end_ms"])]
        self.selected = 0
        self.free_times_initialized = True
        self.syncing_fields = True
        self.target_client.set(plan.get("target_client", "lazer"))
        self.timing_mode.set("自由模式")
        self.fast_clear.set(True)
        self.fields["scroll_speed"].set(number(plan["scroll_speed"]))
        self._show_time_fields()
        self.entries["transition_ms"].configure(state="disabled")
        self._changed()
        self._refresh_preview(compiled_plan=plan)

    def _poll_video_import(self):
        while True:
            try:
                kind, payload = self.import_results.get_nowait()
            except queue.Empty:
                return
            if kind == "progress":
                self.import_status.set(payload)
                continue
            self.importing = False
            result, error = payload
            if error is None and self.import_cancel.is_set():
                error = ImportCancelled("已取消视频导入，原项目未改变。")
            if error is None and self.import_job == "preview":
                self.video_preview_result = result
                self.video_source_image = tk.PhotoImage(data=result["source_ppm"], format="PPM")
                self.video_source_canvas.delete("all")
                self.video_source_canvas.create_image(0, 0, image=self.video_source_image, anchor="nw")
                self.video_result_canvas.delete("all")
                rows = result["frame"]
                for y, row in enumerate(rows):
                    for x, pixel in enumerate(row):
                        if pixel == "#":
                            self.video_result_canvas.create_rectangle(x * 320 / len(row), y * 180 / len(rows),
                                (x + 1) * 320 / len(row), (y + 1) * 180 / len(rows), fill=INK, outline="")
                self.video_preview_label.set(f"第 {result['frame_index'] + 1} 帧 · 源时间 {result['time_ms']:.2f} ms · 转换结果")
                self.import_status.set("预览完成。可调整参数、选择其他帧，或导入整个视频。")
                for entry in self.video_inputs:
                    entry.configure(state="readonly" if isinstance(entry, ttk.Combobox) else "normal")
                self.video_option_controls()
                self.video_start_button.configure(state="normal")
                self.video_preview_button.configure(state="normal")
                continue
            if error is not None and not isinstance(error, ImportCancelled):
                for entry in self.video_inputs:
                    entry.configure(state="readonly" if isinstance(entry, ttk.Combobox) else "normal")
                self.video_option_controls()
                self.video_start_button.configure(state="normal")
                self.video_preview_button.configure(state="normal")
                self.video_cancel_button.configure(state="normal")
                self.import_status.set("导入失败，原项目未改变。请检查文件或参数后重试。")
                messagebox.showerror("视频导入失败", str(error), parent=self.import_dialog)
            else:
                self.import_dialog.destroy()
                self.import_dialog = None
                if error is not None:
                    self._status(str(error))
                else:
                    self._apply_video(result)
                    audio = "音乐已导入，导出时会打包进谱面" if self.audio_data is not None else "视频没有音轨，导出使用静音"
                    self._status(f"已导入 {len(self.frames)} 帧 · {number(self.video['fps'])} FPS · "
                                 f"{self.video['width']} × {self.video['height']} · {audio}。请保存 JSON 项目保留音轨。"
                                 + (f" 游戏 {self.video['game_fps']} FPS；需要游戏限帧和刷新对齐。"
                                    if self.video.get("game_fps") is not None else ""))

    def edit_text(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑文本图案")
        dialog.geometry(f"{round(520 * self.scale)}x{round(460 * self.scale)}")
        dialog.configure(background=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="# = 音符，. = 空白；多帧以独立的 --- 行分隔", padding=12).pack(anchor="w")
        text = tk.Text(dialog, background=PANEL, foreground=INK, insertbackground=INK,
                       font=("Consolas", 13), undo=True, wrap="none", padx=12, pady=12)
        text.insert("1.0", self._text())

        def apply():
            try:
                self.load_text(text.get("1.0", "end-1c"))
            except ValueError as error:
                messagebox.showerror("图案格式错误", str(error), parent=dialog)
                return
            dialog.destroy()

        ttk.Button(dialog, text="应用到画布", command=apply, style="Accent.TButton").pack(side="bottom", anchor="e", padx=12, pady=12)
        text.pack(fill="both", expand=True, padx=12)
        text.focus_set()

    def _stop(self):
        self.playing = False
        self.audio_player.stop()
        self.play_button.configure(text="▶ 播放")

    def _destroy_audio(self, event):
        if event.widget == self.root:
            self.audio_player.close()

    def _schedule_preview(self, *args):
        self._stop()
        self.plan = None
        self.play_button.configure(state="disabled")
        self.seek.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self._draw_preview()
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(180, self._refresh_preview)

    def _refresh_preview(self, compiled_plan=None):
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
            self.preview_job = None
        self._stop()
        try:
            if compiled_plan is not None:
                self.plan = compiled_plan
            else:
                values = {}
                for key, variable in self.fields.items():
                    try:
                        values[key] = float(variable.get())
                    except ValueError:
                        raise ValueError("时间与滚速必须填写数字。") from None
                windows = None
                if self.timing_mode.get() == "自由模式":
                    try:
                        windows = [tuple(map(float, window)) for window in self.frame_times]
                    except ValueError:
                        raise ValueError("每一帧的开始和结束时间都必须填写数字。") from None
                self.plan = compile_frames(self.frames, **values, frame_times=windows, fast_clear=self.fast_clear.get(),
                                            allow_empty_frames=self.video is not None, anchor_reference=self.video is not None,
                                            target_client=self.target_client.get())
            if self.video is not None:
                self.plan["video"] = self.video.copy()
        except ValueError as error:
            self.plan = None
            self._status(str(error), error=True)
        if self.plan is not None:
            self.timeline = Timeline([Point(**point) for point in self.plan["points"]])
            self.note_distances = [self.timeline.position(note["time_ms"]) for note in self.plan["notes"]]
            self.frame_starts = [frame["start_ms"] for frame in self.plan["frames"]]
            self.seek_min = max(0, self.plan["start_ms"] - self.plan["transition_ms"] - 180)
            self.seek_max = self.plan["end_ms"] + self.plan["transition_ms"] + 180
            self.seek.configure(from_=self.seek_min, to=self.seek_max)
            self.seek_time.set(self.plan["frames"][self.selected]["start_ms"])
            self._status(f"{self.plan['keys']}K · {len(self.frames)} 帧 · {len(self.plan['notes'])} 音符 · "
                         f"{'极速' if self.fast_clear.get() else ''}切帧 {self.plan['transition_ms']:.3f} ms · "
                         f"单帧最大预计漂移 {self.plan['drift_at_658px']:.4f} px / 658 px"
                         + (" · 已带视频音轨" if self.audio_data is not None else "")
                         + (f" · {number(self.video['fps'])} FPS / {self.video['height']} 行 · "
                            f"游戏 {self.video['game_fps']} FPS；需要游戏限帧和刷新对齐"
                            if self.video is not None and self.video.get("game_fps") is not None else ""))
        state = "normal" if self.plan is not None else "disabled"
        self.play_button.configure(state=state)
        self.seek.configure(state=state)
        self.export_button.configure(state=state if not self.exporting else "disabled")
        self._draw_preview()

    def _draw_preview(self):
        self.preview.delete("all")
        width, height = self.preview.winfo_width(), self.preview.winfo_height()
        if self.plan is None:
            self.preview.create_text(width / 2, height / 2, text="画好图案并填写有效参数后\n这里会显示舞台预览", fill=MUTED, justify="center")
            self.time_label.set("等待有效图案与参数")
            return
        full_h = max(1, height - 34 * self.scale)
        stage_h = full_h * 658 / 768
        stage_w = max(1, min(width - 24 * self.scale, stage_h * 360 / 658))
        left, top = (width - stage_w) / 2, 10 * self.scale
        note_half = max(1, 4 * stage_h / 658)
        lane = stage_w / self.plan["keys"]
        current = self.seek_time.get()
        position = self.timeline.position(current)
        for col in range(self.plan["keys"]):
            self.preview.create_rectangle(left + col * lane, top, left + (col + 1) * lane, top + full_h,
                                          fill="#141c2b" if col % 2 == 0 else "#101725", outline="#253044")
            self.preview.create_text(left + (col + 0.5) * lane, top + full_h + 13 * self.scale, text=str(col + 1), fill=MUTED, font=("Segoe UI", 9))
        first = bisect_left(self.note_distances, position + (1 - (full_h + note_half) / stage_h) * self.plan["time_range_ms"])
        last = bisect_right(self.note_distances, position + (1 + note_half / stage_h) * self.plan["time_range_ms"])
        for index in range(first, last):
            note, distance = self.plan["notes"][index], self.note_distances[index]
            y = (1 - (distance - position) / self.plan["time_range_ms"]) * stage_h
            # Keep drawing below judgement until physically off stage. Miss fades aren't simulated.
            if -note_half <= y <= full_h + note_half:
                x = left + note["column"] * lane
                self.preview.create_rectangle(x + 2 * self.scale, max(top, top + y - note_half), x + lane - 2 * self.scale,
                                              min(top + full_h, top + y + note_half),
                                              fill=ACCENT if note["column"] % 2 == 0 else MINT, outline="", tags="note")
        self.preview.create_line(left, top + stage_h, left + stage_w, top + stage_h, fill=INK, width=2)
        index = bisect_right(self.frame_starts, current) - 1
        frames = self.plan["frames"]
        holding = index >= 0 and (current <= frames[index]["end_ms"] or
                                  (index + 1 < len(frames) and
                                   frames[index].get("note_frame", index) == frames[index + 1].get("note_frame", index + 1)))
        frame = index + 1 if holding else None
        phase = f"第 {frame} / {len(self.frames)} 帧" if frame is not None else "空档 / 进场 / 换帧 / 退场"
        self.time_label.set(f"{current:,.2f} ms   ·   {phase}")

    def _seek_changed(self, value):
        self._stop()
        self._draw_preview()

    def seek_selected(self):
        self._stop()
        if self.plan is not None:
            self.seek_time.set(self.plan["frames"][self.selected]["start_ms"])
            self._draw_preview()

    def toggle_play(self):
        if self.plan is None:
            return
        if self.playing:
            position = self.audio_player.position_ms()
            if position is not None:
                self.seek_time.set(min(self.seek_max, position))
            self._stop()
            self._draw_preview()
        else:
            if self.seek_time.get() >= self.seek_max:
                self.seek_time.set(self.seek_min)
            try:
                self.audio_player.play(self.audio_data, self.seek_time.get())
            except RuntimeError as error:
                self._status(f"{error} 画面继续无声预览。", error=True)
            self.playing = True
            self.last_tick = time.perf_counter()
            self.play_button.configure(text="Ⅱ 暂停")

    def _tick(self):
        if self.importing:
            self._poll_video_import()
        if self.playing and self.plan is not None:
            now = time.perf_counter()
            position = self.audio_player.position_ms()
            current = min(self.seek_max, position if position is not None else
                          self.seek_time.get() + (now - self.last_tick) * 1000)
            self.last_tick = now
            self.seek_time.set(current)
            if current >= self.seek_max:
                self._stop()
            self._draw_preview()
        if self.exporting:
            try:
                output, error = self.export_results.get_nowait()
            except queue.Empty:
                pass
            else:
                self.exporting = False
                self.export_button.configure(text="导出 .osz  →", state="normal" if self.plan is not None else "disabled")
                if error is not None:
                    self._status(f"导出失败：{error}", error=True)
                    messagebox.showerror("导出失败", str(error), parent=self.root)
                else:
                    self.last_output = output
                    self.folder_button.configure(state="normal")
                    self._status(f"已导出：{output / 'pattern.osz'} · "
                                 + ("请按播放设置.txt 限帧并对齐刷新。"
                                    if self.video is not None and self.video.get("game_fps") is not None else
                                    "也已生成 HTML 预览与报告。"))
        self.tick_job = self.root.after(16 if self.playing else 80, self._tick)

    def choose_output(self):
        directory = filedialog.askdirectory(parent=self.root, title="选择导出目录")
        if directory:
            self.output_dir.set(directory)

    def export(self):
        if self.exporting or self.importing:
            return
        # Recompile immediately so edits still waiting for the debounce are never lost.
        self._refresh_preview()
        if self.plan is None:
            return
        if not self.output_dir.get().strip():
            self._status("请选择导出目录。", error=True)
            return
        try:
            output = Path(self.output_dir.get()).expanduser().resolve()
            names = tuple("audio.ogg" if name == "silence.wav" and self.audio_data is not None else name
                          for name in OUTPUT_FILES)
            if ((self.video is not None and self.video.get("game_fps") is not None)
                    or (output / "播放设置.txt").exists()):
                names += ("播放设置.txt",)
            exists = any((output / name).exists() for name in names)
        except (OSError, ValueError) as error:
            self._status(f"导出目录无效：{error}", error=True)
            return
        if exists and not messagebox.askyesno("确认覆盖", "目录中已有生成文件。要覆盖同名的谱面、音频、预览和报告吗？\n其他文件不会删除。", parent=self.root):
            return
        plan, audio_data = self.plan, self.audio_data
        self.exporting = True
        self.export_button.configure(state="disabled", text="正在导出…")
        self._status("正在导出当前图案快照…")

        def run():
            try:
                write_output(plan, output, audio_data=audio_data)
            except Exception as error:
                self.export_results.put((output, error))
            else:
                self.export_results.put((output, None))

        threading.Thread(target=run, daemon=True).start()

    def open_output(self):
        if self.last_output is not None:
            try:
                os.startfile(self.last_output)
            except OSError as error:
                messagebox.showerror("无法打开目录", str(error), parent=self.root)

    def close(self):
        if self.importing:
            messagebox.showinfo("正在导入", "请先取消视频导入或等它完成，再关闭窗口。", parent=self.root)
            return
        if self.exporting:
            messagebox.showinfo("正在导出", "请等导出完成后再关闭窗口。", parent=self.root)
            return
        if self._can_discard():
            if self.preview_job is not None:
                self.root.after_cancel(self.preview_job)
            self.root.after_cancel(self.tick_job)
            self.root.destroy()


def main():
    # Use physical pixels on Windows rather than a bitmap-scaled blurry window.
    if os.name == "nt":
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    PaintApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
