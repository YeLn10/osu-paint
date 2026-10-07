"""Native desktop editor for the existing osu!mania pattern compiler."""

from bisect import bisect_left, bisect_right
from fractions import Fraction
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

from osu_paint import CLIENTS, Point, Timeline, compile_frames, minimum_transition_ms, number, parse_frames, refresh_warning, write_output
from osu_paint_video import (ImportCancelled, import_video as read_video, preview_video_frame,
                             resolve_video_options)
from osu_paint_audio import AudioPreview
from osu_paint_skin import DEFAULT_ASPECT_RATIO, SKIN_PROFILES, skin_filename


HEART = [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."]
OUTPUT_FILES = ("pattern.osz", "pattern.osu", "silence.wav", "preview.html", "report.json", *SKIN_PROFILES)
BG = "#10131c"
PANEL = "#191f2c"
INK = "#edf1fa"
MUTED = "#a2aec2"
ACCENT = "#f182ad"
MINT = "#70dfcc"
BORDER = "#30394b"
FIELD = "#111722"


class PaintApp:
    def __init__(self, root):
        self.root = root
        self.frames = [HEART.copy()]
        self.frame_times = [["2000", "4000"]]
        self.uniform_times = ["2000", "4000"]
        self.free_times_initialized = False
        self.syncing_fields = False
        self.target_client = tk.StringVar(value="lazer")
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
        gap = round(6 * self.scale)
        style.configure(".", font=("Microsoft YaHei UI", 10), background=BG,
                        foreground=INK, bordercolor=BORDER)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("Panel.TLabel", background=PANEL)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Heading.TLabel", background=PANEL, font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("TButton", background="#2a3447", padding=(gap * 2, gap),
                        borderwidth=0, focusthickness=1, focuscolor=MUTED)
        style.map("TButton", background=[("disabled", PANEL), ("active", "#3b4861")],
                  foreground=[("disabled", "#748198")])
        style.configure("Quiet.TButton", background=PANEL, foreground=MUTED)
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, focuscolor=BG)
        style.map("Accent.TButton", background=[("disabled", PANEL), ("active", "#ffa4c7")])
        for name in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(name, fieldbackground=FIELD, foreground=INK, insertcolor=INK,
                            padding=gap, borderwidth=1, arrowsize=round(12 * self.scale),
                            arrowcolor=MUTED, lightcolor=BORDER, darkcolor=BORDER)
            style.map(name, fieldbackground=[("disabled", PANEL), ("readonly", FIELD)],
                      foreground=[("disabled", MUTED), ("readonly", INK)],
                      bordercolor=[("focus", ACCENT)])
        style.configure("TCheckbutton", background=PANEL, padding=(0, gap // 2),
                        indicatorbackground=FIELD, indicatorforeground=BG,
                        indicatorsize=round(14 * self.scale), indicatormargin=(0, 0, gap, 0))
        style.map("TCheckbutton", background=[("active", PANEL)],
                  foreground=[("disabled", MUTED)],
                  indicatorbackground=[("selected", ACCENT), ("active", BORDER)])
        style.configure("Horizontal.TScale", background=MINT, troughcolor=FIELD,
                        sliderlength=round(14 * self.scale), arrowsize=round(12 * self.scale),
                        gripcount=0, borderwidth=0, lightcolor=MINT, darkcolor=MINT)
        style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=PANEL,
                        arrowcolor=MUTED, borderwidth=0, arrowsize=round(10 * self.scale))
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", INK)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#57364d")
        self.root.option_add("*TCombobox*Listbox.selectForeground", INK)

    def _build(self):
        pad, gap = round(18 * self.scale), round(10 * self.scale)
        header = ttk.Frame(self.root, padding=(pad, gap, pad, gap))
        header.pack(fill="x")
        ttk.Label(header, text="osu!paint", style="Title.TLabel").pack(side="left")
        client_panel = ttk.Frame(header)
        client_panel.pack(side="left", padx=pad)
        ttk.Label(client_panel, text="目标", style="Muted.TLabel").pack(side="left", padx=(0, gap))
        self.client_choice = ttk.Combobox(client_panel, textvariable=self.target_client,
                                         values=CLIENTS, state="readonly", width=7)
        self.client_choice.pack(side="left")
        self.client_display = ttk.Label(client_panel, textvariable=self.target_client)
        self.target_client.trace_add("write", self._client_changed)
        for label, command in [("导入视频", self.import_video), ("保存项目", self.save_pattern),
                               ("打开项目", self.open_pattern)]:
            ttk.Button(header, text=label, command=command).pack(side="right", padx=(gap, 0))

        body = ttk.Frame(self.root, padding=(pad, 0, pad, 0))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=6, uniform="columns")
        body.columnconfigure(1, weight=5, uniform="columns")
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body, style="Panel.TFrame", padding=gap)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, gap))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        tools = ttk.Frame(left, style="Panel.TFrame")
        tools.grid(row=0, column=0, sticky="ew")
        ttk.Label(tools, text="像素画布", style="Heading.TLabel").pack(side="left")
        ttk.Button(tools, text="新建", style="Quiet.TButton", command=self.new_pattern).pack(side="right")
        ttk.Button(tools, text="编辑文本", style="Quiet.TButton", command=self.edit_text).pack(side="right")
        self.editor_info = tk.StringVar()
        ttk.Label(left, textvariable=self.editor_info, style="PanelMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, gap))
        self.canvas = tk.Canvas(left, background=PANEL, highlightthickness=0, height=round(240 * self.scale))
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda event: self._draw_grid())
        self.canvas.bind("<Button-1>", self._begin_stroke)
        self.canvas.bind("<B1-Motion>", self._paint)
        self.canvas.bind("<Button-3>", self._begin_stroke)
        self.canvas.bind("<B3-Motion>", self._paint)
        ttk.Label(left, text="左键绘制 · 右键擦除", style="PanelMuted.TLabel").grid(
            row=3, column=0, sticky="w", pady=(gap, gap))
        frame_bar = ttk.Frame(left, style="Panel.TFrame")
        frame_bar.grid(row=4, column=0, sticky="ew", pady=(0, gap // 2))
        ttk.Label(frame_bar, text="动画帧", style="Heading.TLabel").pack(side="left")
        self.delete_button = ttk.Button(frame_bar, text="删除", style="Quiet.TButton", command=self.delete_frame)
        self.delete_button.pack(side="right")
        ttk.Button(frame_bar, text="复制", style="Quiet.TButton",
                   command=lambda: self.add_frame(True)).pack(side="right")
        ttk.Button(frame_bar, text="＋ 空白帧", style="Quiet.TButton", command=self.add_frame).pack(side="right")
        frame_box = ttk.Frame(left, style="Panel.TFrame")
        frame_box.grid(row=5, column=0, sticky="ew")
        self.frame_list = tk.Listbox(frame_box, height=4, background=FIELD, foreground=INK,
                                    selectbackground="#57364d", selectforeground=INK,
                                    font=("Microsoft YaHei UI", 10), borderwidth=0,
                                    highlightthickness=1, highlightbackground=BORDER,
                                    highlightcolor=ACCENT, exportselection=False, activestyle="none")
        self.frame_list.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(frame_box, command=self.frame_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.frame_list.configure(yscrollcommand=scrollbar.set)
        self.frame_list.bind("<<ListboxSelect>>", self.select_frame)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        preview_panel = ttk.Frame(right, style="Panel.TFrame", padding=gap)
        preview_panel.grid(row=0, column=0, sticky="nsew", pady=(0, gap))
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(1, weight=1)
        preview_bar = ttk.Frame(preview_panel, style="Panel.TFrame")
        preview_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(preview_bar, text="舞台预览", style="Heading.TLabel").pack(side="left")
        ttk.Label(preview_bar, text="位置模拟 · 非实机", style="PanelMuted.TLabel").pack(side="right")
        self.preview = tk.Canvas(preview_panel, background=PANEL, highlightthickness=0,
                                 width=round(300 * self.scale), height=round(150 * self.scale))
        self.preview.grid(row=1, column=0, sticky="nsew")
        self.preview.bind("<Configure>", lambda event: self._draw_preview())
        self.seek_time = tk.DoubleVar(value=2000)
        self.seek = ttk.Scale(preview_panel, variable=self.seek_time, command=self._seek_changed)
        self.seek.grid(row=2, column=0, sticky="ew", pady=(gap // 2, gap // 2))
        playback = ttk.Frame(preview_panel, style="Panel.TFrame")
        playback.grid(row=3, column=0, sticky="ew")
        self.play_button = ttk.Button(playback, text="▶ 播放", command=self.toggle_play, width=6)
        self.play_button.pack(side="left")
        ttk.Button(playback, text="定位", style="Quiet.TButton", command=self.seek_selected, width=4).pack(
            side="left", padx=(gap // 2, 0))
        self.time_label = tk.StringVar()
        ttk.Label(playback, textvariable=self.time_label, style="PanelMuted.TLabel").pack(side="right")

        settings_panel = ttk.Frame(right, style="Panel.TFrame", padding=gap)
        settings_panel.grid(row=1, column=0, sticky="ew")
        settings_panel.columnconfigure(0, weight=1)
        timing_bar = ttk.Frame(settings_panel, style="Panel.TFrame")
        timing_bar.grid(row=0, column=0, sticky="ew", pady=(0, gap))
        ttk.Label(timing_bar, text="时间与滚速", style="Heading.TLabel").pack(side="left")
        ttk.Button(timing_bar, text="说明", style="Quiet.TButton", command=self.explain_timing, width=4).pack(side="right")
        self.timing_mode = tk.StringVar(value="均分模式")
        ttk.Combobox(timing_bar, textvariable=self.timing_mode, values=("均分模式", "自由模式"),
                     state="readonly", width=8).pack(side="right", padx=gap)
        settings = ttk.Frame(settings_panel, style="Panel.TFrame")
        settings.grid(row=1, column=0, sticky="ew")
        self.fields = {}
        self.time_labels = []
        self.entries = {}
        for i, (key, label, value) in enumerate([
                ("start_ms", "开始 / ms", "2000"), ("end_ms", "结束 / ms", "4000"),
                ("transition_ms", "切帧 / ms", "12"), ("scroll_speed", "游戏滚速 · 1–40", "27")]):
            row, col = divmod(i, 2)
            settings.columnconfigure(col, weight=1, uniform="fields")
            field_label = ttk.Label(settings, text=label, style="PanelMuted.TLabel")
            field_label.grid(row=row * 2, column=col, sticky="w", padx=(0, gap), pady=(0 if row == 0 else gap, 0))
            self.time_labels.append(field_label)
            variable = tk.StringVar(value=value)
            self.fields[key] = variable
            entry = ttk.Entry(settings, textvariable=variable, width=9)
            entry.grid(row=row * 2 + 1, column=col, sticky="ew", padx=(0, gap if col == 0 else 0))
            self.entries[key] = entry
            variable.trace_add("write", lambda *args, field=key: self._parameter_changed(field))
        self.automatic_transition = tk.StringVar(value="自动")
        self.entries["transition_ms"].configure(state="disabled")
        self.timing_mode.trace_add("write", self._mode_changed)
        options = ttk.Frame(settings_panel, style="Panel.TFrame")
        options.grid(row=2, column=0, sticky="ew", pady=(gap // 2, 0))
        self.fast_clear = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="极速清场", variable=self.fast_clear,
                        command=lambda: (self._clear_video_alignment(), self._timing_options_changed())).pack(side="left")
        self.merge_holds = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="合并长条", variable=self.merge_holds,
                        command=self._changed).pack(side="left", padx=pad)
        self.playback_hint = tk.StringVar()
        hint = ttk.Label(settings_panel, textvariable=self.playback_hint, style="PanelMuted.TLabel")
        hint.grid(row=3, column=0, sticky="ew", pady=(gap // 2, 0))
        settings_panel.bind("<Configure>", lambda event: hint.configure(wraplength=max(1, event.width - 2 * gap)))

        footer = ttk.Frame(self.root, padding=(pad, gap, pad, gap))
        footer.pack(fill="x")
        footer.columnconfigure(1, weight=1)
        ttk.Label(footer, text="导出到", style="Muted.TLabel").grid(row=0, column=0, padx=(0, gap))
        self.output_dir = tk.StringVar(value=str(Path.home() / "osu-paint-output"))
        ttk.Entry(footer, textvariable=self.output_dir).grid(row=0, column=1, sticky="ew")
        ttk.Button(footer, text="选择目录", command=self.choose_output).grid(row=0, column=2, padx=gap)
        self.folder_button = ttk.Button(footer, text="打开结果", command=self.open_output, state="disabled")
        self.folder_button.grid(row=0, column=3, padx=(0, gap))
        self.export_button = ttk.Button(footer, text="导出 .osz  →", style="Accent.TButton", command=self.export)
        self.export_button.grid(row=0, column=4)
        self.status = tk.StringVar()
        self.status_label = ttk.Label(footer, textvariable=self.status, style="Muted.TLabel",
                                      font=("Microsoft YaHei UI", 9))
        self.status_label.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(gap // 2, 0))
        footer.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(1, event.width - 2 * pad)))

    def _show_time_fields(self):
        free = self.timing_mode.get() == "自由模式"
        values = self.frame_times[self.selected] if free else self.uniform_times
        self.syncing_fields = True
        for i, key in enumerate(("start_ms", "end_ms")):
            self.fields[key].set(values[i])
            self.time_labels[i].configure(text=("本帧开始 / ms", "本帧结束 / ms")[i] if free
                                          else ("开始 / ms", "结束 / ms")[i])
        self.syncing_fields = False

    def _parameter_changed(self, key):
        if self.syncing_fields:
            return
        alignment_removed = self._clear_video_alignment()
        if key in ("start_ms", "end_ms"):
            values = self.frame_times[self.selected] if self.timing_mode.get() == "自由模式" else self.uniform_times
            values[0 if key == "start_ms" else 1] = self.fields[key].get()
        self._changed()
        if alignment_removed:
            self._refresh_preview()
            notice = "已撤销刷新率／游戏帧率切帧设置；需重新导入视频才能重新对齐。"
            self._status(notice if self.plan is not None else f"{self.status.get()} {notice}", error=self.plan is None)

    def _client_changed(self, *args):
        if self.syncing_fields:
            return
        self._clear_video_alignment()
        self._changed()

    def _clear_video_alignment(self):
        if self.video is None or self.video.get("refresh_hz") is None:
            return False
        self.video = {key: value for key, value in self.video.items()
                      if key not in ("refresh_hz", "refresh_phase_ms", "requested_fps", "requested_height")}
        return True

    def _mode_changed(self, *args):
        if self.syncing_fields:
            return
        self._clear_video_alignment()
        if self.timing_mode.get() == "自由模式" and not self.free_times_initialized:
            try:
                plan = compile_frames(self.frames, *map(float, self.uniform_times),
                                      float(self.fields["scroll_speed"].get()), float(self.fields["transition_ms"].get()),
                                      fast_clear=self.fast_clear.get(), merge_holds=self.merge_holds.get(), target_client=self.target_client.get())
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
        details = ""
        if self.plan is not None:
            details = (f"\n\n当前：{self.plan['target_client']} · {len(self.plan['notes'])} 音符 · "
                       f"切帧 {self.plan['sweep_ms']:.3f} ms\n"
                       f"预计最大单帧漂移 {self.plan['drift_at_768px']:.4f} px（内部高度 768 px）")
        messagebox.showinfo("参数说明",
                            "均分：所有帧平分总时间，扣除切帧时长。\n"
                            "自由：逐帧设定起止时间；可留空档，不能重叠。\n"
                            "极速清场：自动计算切帧时长；关闭后可手动填写。\n"
                            "合并长条：仅合并同帧、同列的相邻亮格，不跨空格。\n\n"
                            "游戏滚速须与这里一致；stable 使用固定滚速。\n"
                            "视频按实际刷新率排帧，音轨不随排帧调整移动。\n"
                            "换视频客户端须重新导入；保存 JSON 可保留时间与音轨，TXT 仅保存图案。\n\n"
                            "导出后分别导入 .osz 和匹配屏幕比例的 pixel-film*.osk，默认 16:10。\n"
                            "lazer >10K 强制双舞台，11/13/15/17K 少一列，皮肤无法解除。\n"
                            "stable 合并 1–18K，但每列最多 100，低键数较窄。\n"
                            "预览仅模拟位置；刷新率排帧不能保证实机零残影。" + details,
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
            items.append(f"  {i + 1:02d}    {'●' if i == self.selected else '○'}    {count} 亮格{timing}")
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
            gap = self.plan["transition_ms"] if self.plan is not None else minimum_transition_ms(rows=len(self.frames[0]), target_client=self.target_client.get())
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
            self.merge_holds.set(True)
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
                    start = float(self.frame_times[-1][1]) + minimum_transition_ms(rows=len(frames[0]), target_client=self.target_client.get())
                    self.frame_times.append([number(start), number(start + 2000)])
                except ValueError:
                    self.frame_times.append(["", ""])
        self.frames, self.selected = frames, 0
        self._show_time_fields()
        self._changed()
        if alignment_removed:
            self._refresh_preview()
            notice = "画布尺寸已改变，已撤销刷新率排帧设置；需重新导入视频才能重新对齐。"
            self._status(notice if self.plan is not None else f"{self.status.get()} {notice}", error=self.plan is None)

    def _text(self):
        return "\n---\n".join("\n".join(frame) for frame in self.frames) + "\n"

    def _project_data(self):
        settings = {key: variable.get() for key, variable in self.fields.items()}
        settings["start_ms"], settings["end_ms"] = self.uniform_times
        data = {"format": "osu-paint", "version": 1, "target_client": self.target_client.get(), "frames": self.frames,
                "frame_times": self.frame_times, "timing_mode": self.timing_mode.get(),
                "settings": settings, "fast_clear": self.fast_clear.get(),
                "merge_holds": self.merge_holds.get()}
        if self.video is not None:
            data.update(version=2, video=self.video.copy(),
                        audio=base64.b64encode(self.audio_data).decode("ascii") if self.audio_data is not None else None)
        return data

    def load_project(self, data):
        try:
            if data["format"] != "osu-paint" or data["version"] not in (1, 2):
                raise ValueError("不支持的项目版本。")
            target_client = data.get("target_client", "lazer")
            if target_client not in CLIENTS:
                raise ValueError("项目中的客户端须为 stable 或 lazer。")
            video, audio = None, None
            merge_holds = data.get("merge_holds", False)
            if not isinstance(merge_holds, bool):
                raise ValueError("项目中的长条开关无效。")
            if data["version"] == 2:
                video = data["video"]
                if not isinstance(video, dict) or not isinstance(video["filename"], str):
                    raise ValueError("项目中的视频信息无效。")
                if video.get("reference_animation"):
                    raise ValueError("此项目使用已撤销的参考动画模式，请从原视频重新导入。")
                # Keep the explicit project client, but discard obsolete scheduling controls.
                video = {key: value for key, value in video.items() if key not in ("game_fps", "frame_fps", "refresh_phase_ms")}
                effective = resolve_video_options(fps=video["fps"], width=video["width"], height=video["height"],
                                                  start_ms=video["start_ms"], scroll_speed=float(data["settings"]["scroll_speed"]),
                                                  refresh_hz=video.get("refresh_hz"),
                                                  merge_holds=merge_holds, target_client=target_client)
                if video.get("refresh_hz") is not None and (
                        effective["height"] != video["height"] or not math.isclose(effective["fps"], video["fps"], abs_tol=1e-9)):
                    raise ValueError("项目中的刷新率排帧参数与实际画面不一致，请从原视频重新导入。")
                if not math.isfinite(video["duration_ms"]) or video["duration_ms"] <= 0:
                    raise ValueError("项目中的视频时长无效。")
                if data["audio"] is not None:
                    audio = base64.b64decode(data["audio"], validate=True)
                    if not audio.startswith(b"OggS"):
                        raise ValueError("项目中的音轨无效。")
                video = video.copy()
            frames = parse_frames("\n---\n".join("\n".join(frame) for frame in data["frames"]), allow_empty=True)
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
        self.merge_holds.set(merge_holds)
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
        filename = filedialog.asksaveasfilename(parent=self.root, title="保存项目（JSON 保留时间参数）",
                                              defaultextension=".json",
                                              filetypes=[("osu-paint 项目", "*.json"), ("仅文本图案", "*.txt")])
        if not filename:
            return
        try:
            text_only = Path(filename).suffix.lower() == ".txt"
            # A project can be saved before its empty frames are ready to export.
            parse_frames(self._text(), allow_empty=not text_only or self.video is not None)
            content = self._text() if text_only else json.dumps(self._project_data(), ensure_ascii=False, indent=2)
            Path(filename).write_text(content, encoding="utf-8")
        except (OSError, ValueError) as error:
            messagebox.showerror("保存失败", str(error), parent=self.root)
            return
        if not text_only:
            self.dirty = False
        self._update_editor()
        self._status(f"图案已保存：{filename}（TXT 不保存音轨与时间参数；项目修改仍需保存为 JSON）" if text_only
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
        dialog.title("导入视频")
        dialog.configure(background=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        pad, gap = round(18 * self.scale), round(10 * self.scale)
        heading = ttk.Frame(dialog, padding=(pad, gap, pad, gap))
        heading.pack(fill="x")
        ttk.Label(heading, text="导入视频", font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        ttk.Label(heading, text=Path(filename).name, style="Muted.TLabel",
                  wraplength=round(560 * self.scale)).pack(side="left", padx=pad)
        body = ttk.Frame(dialog, padding=(pad, 0, pad, 0))
        body.pack(fill="both", expand=True)
        panel = ttk.Frame(body, style="Panel.TFrame", padding=gap)
        panel.pack(side="left", fill="both", expand=True, padx=(0, gap))
        for col in (0, 1):
            panel.columnconfigure(col, weight=1, uniform="video-fields")
        preview_panel = ttk.Frame(body, style="Panel.TFrame", padding=gap)
        preview_panel.pack(side="right", fill="both")
        ttk.Label(preview_panel, text="原画面", style="Heading.TLabel").pack(anchor="w")
        self.video_source_canvas = tk.Canvas(preview_panel, width=round(320 * self.scale),
                                             height=round(180 * self.scale), background="#000", highlightthickness=0)
        self.video_source_canvas.pack(pady=(gap // 2, gap))
        ttk.Label(preview_panel, text="像素结果", style="Heading.TLabel").pack(anchor="w")
        self.video_result_canvas = tk.Canvas(preview_panel, width=round(320 * self.scale),
                                             height=round(180 * self.scale), background="#fff", highlightthickness=0)
        self.video_result_canvas.pack(pady=(gap // 2, gap))
        self.video_preview_result = None
        self.video_preview_label = tk.StringVar(value="选择帧后预览")
        ttk.Label(preview_panel, textvariable=self.video_preview_label, wraplength=round(320 * self.scale),
                  style="PanelMuted.TLabel").pack(anchor="w", pady=(0, gap // 2))
        preview_controls = ttk.Frame(preview_panel, style="Panel.TFrame")
        preview_controls.pack(fill="x")
        ttk.Label(preview_controls, text="预览帧", style="PanelMuted.TLabel").pack(side="left", padx=(0, gap))
        self.video_frame_index = tk.StringVar(value="1")
        frame_entry = ttk.Entry(preview_controls, textvariable=self.video_frame_index, width=6)
        frame_entry.pack(side="left")

        ttk.Label(panel, text="采样设置", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, gap))
        self.video_target_client = tk.StringVar(value=self.target_client.get())
        ttk.Label(panel, text="客户端", style="PanelMuted.TLabel").grid(row=1, column=0, sticky="w")
        self.video_client_choice = ttk.Combobox(panel, textvariable=self.video_target_client,
                                               values=CLIENTS, state="readonly", width=12)
        self.video_client_choice.grid(row=2, column=0, sticky="ew", padx=(0, gap))
        self.video_refresh_hz = tk.StringVar(value="60")
        ttk.Label(panel, text="屏幕刷新率 / Hz", style="PanelMuted.TLabel").grid(row=1, column=1, sticky="w")
        refresh_entry = ttk.Spinbox(panel, textvariable=self.video_refresh_hz, from_=20, to=1000, width=12)
        refresh_entry.grid(row=2, column=1, sticky="ew")
        self.video_fields = {}
        inputs = [self.video_client_choice, refresh_entry, frame_entry]
        for key, label, value, row, col in [
                ("fps", "帧率 / FPS · ≤60", "10", 3, 0),
                ("start_ms", "音画开始 / ms", self.uniform_times[0], 3, 1),
                ("width", "列数 · 1–18", "10", 5, 0),
                ("height", "行数 · 1–128", "12" if self.target_client.get() == "stable" else "24", 5, 1),
                ("threshold", "黑白阈值 · 0–255", "128", 8, 0),
                ("brightness", "亮度 · −255–255", "0", 10, 0),
                ("contrast", "对比度 · >0–5", "1", 10, 1)]:
            ttk.Label(panel, text=label, style="PanelMuted.TLabel").grid(
                row=row, column=col, sticky="w", pady=(gap, 0))
            variable = self.video_fields[key] = tk.StringVar(value=value)
            entry = ttk.Entry(panel, textvariable=variable, width=12)
            entry.grid(row=row + 1, column=col, sticky="ew", padx=(0, gap if col == 0 else 0))
            inputs.append(entry)
        ttk.Label(panel, text="画面调整", style="Heading.TLabel").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        self.video_fit = tk.StringVar(value="拉伸")
        ttk.Label(panel, text="缩放", style="PanelMuted.TLabel").grid(row=8, column=1, sticky="w", pady=(gap, 0))
        combo = ttk.Combobox(panel, textvariable=self.video_fit, values=("拉伸", "等比留边", "等比裁剪"),
                             state="readonly", width=12)
        combo.grid(row=9, column=1, sticky="ew")
        inputs.append(combo)
        self.video_invert = tk.BooleanVar(value=False)
        invert = ttk.Checkbutton(panel, text="亮暗反转", variable=self.video_invert)
        invert.grid(row=12, column=0, sticky="w", pady=(gap, 0))
        inputs.append(invert)
        self.video_merge_holds = tk.BooleanVar(value=True)
        hold_option = ttk.Checkbutton(panel, text="合并长条", variable=self.video_merge_holds)
        hold_option.grid(row=12, column=1, sticky="w", pady=(gap, 0))
        inputs.append(hold_option)
        ttk.Label(panel, text="刷新率支持 59.94、60000/1001。\n成功导入后替换画布，取消或失败不影响原项目。",
                  style="PanelMuted.TLabel", wraplength=round(360 * self.scale)).grid(
                      row=13, column=0, columnspan=2, sticky="w", pady=(pad, 0))
        footer = ttk.Frame(dialog, padding=(pad, gap, pad, gap))
        footer.pack(fill="x")
        self.import_status = tk.StringVar(value="视频音轨将一并导入")
        ttk.Label(footer, textvariable=self.import_status, wraplength=round(540 * self.scale),
                  style="Muted.TLabel").pack(side="left")
        buttons = ttk.Frame(footer)
        buttons.pack(side="right")

        def request_options():
            options = {key: (int(variable.get()) if key in ("width", "height") else float(variable.get()))
                       for key, variable in self.video_fields.items()}
            options["scroll_speed"] = float(self.fields["scroll_speed"].get())
            options.update(invert=self.video_invert.get(),
                           fit={"拉伸": "stretch", "等比留边": "contain", "等比裁剪": "cover"}[self.video_fit.get()],
                           merge_holds=self.video_merge_holds.get(), target_client=self.video_target_client.get())
            try:
                options["refresh_hz"] = float(Fraction(self.video_refresh_hz.get()))
            except (ValueError, ZeroDivisionError):
                raise ValueError("刷新率须为数字或分数，例如 59.94 或 60000/1001。") from None
            return options

        def describe_options(*args):
            self.video_preview_label.set("参数已修改，点击刷新预览")

        # Client defaults may follow the selection until the user edits height;
        # never silently discard a requested row count when switching clients.
        height_edited = False

        def height_changed(*args):
            nonlocal height_edited
            height_edited = True

        def client_changed(*args):
            nonlocal height_edited
            if not height_edited:
                self.video_fields["height"].set("12" if self.video_target_client.get() == "stable" else "24")
                height_edited = False

        self.video_fields["height"].trace_add("write", height_changed)
        self.video_target_client.trace_add("write", client_changed)
        for variable in [*self.video_fields.values(), self.video_invert, self.video_fit, self.video_frame_index,
                         self.video_refresh_hz, self.video_merge_holds, self.video_target_client]:
            variable.trace_add("write", describe_options)

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
        self.video_start_button = ttk.Button(buttons, text="开始导入", command=start, style="Accent.TButton")
        self.video_start_button.pack(side="left")
        self.video_preview_button = ttk.Button(preview_controls, text="刷新预览", command=lambda: start(preview=True))
        self.video_preview_button.pack(side="right")
        self.video_inputs = inputs
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self.video_preview_label.set("选择帧后点击刷新预览")

    def _apply_video(self, result):
        plan = result["plan"]
        self.video, self.audio_data = result["video"].copy(), result["audio"]
        self.frames = [frame["pattern"].copy() for frame in plan["frames"]]
        self.frame_times = [[number(frame["start_ms"]), number(frame["end_ms"])] for frame in plan["frames"]]
        self.uniform_times = [number(plan["start_ms"]), number(plan["end_ms"])]
        self.selected = 0
        self.free_times_initialized = True
        self.syncing_fields = True
        self.target_client.set(plan["target_client"])
        self.timing_mode.set("自由模式")
        self.fast_clear.set(True)
        self.merge_holds.set(plan.get("merge_holds", False))
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
                source = tk.PhotoImage(data=result["source_ppm"], format="PPM")
                scale = Fraction(self.scale).limit_denominator(4)
                self.video_source_image = source.zoom(scale.numerator).subsample(scale.denominator)
                self.video_source_canvas.delete("all")
                self.video_source_canvas.create_image(int(self.video_source_canvas["width"]) / 2,
                    int(self.video_source_canvas["height"]) / 2, image=self.video_source_image)
                self.video_result_canvas.delete("all")
                rows = result["frame"]
                width, height = int(self.video_result_canvas["width"]), int(self.video_result_canvas["height"])
                for y, row in enumerate(rows):
                    for x, pixel in enumerate(row):
                        if pixel == "#":
                            self.video_result_canvas.create_rectangle(x * width / len(row), y * height / len(rows),
                                (x + 1) * width / len(row), (y + 1) * height / len(rows), fill="black", outline="")
                self.video_preview_label.set(f"第 {result['frame_index'] + 1} 帧 · 源时间 {result['time_ms'] / 1000:.2f} s")
                self.import_status.set("预览就绪 · 导入将使用完整视频")
                for entry in self.video_inputs:
                    entry.configure(state="readonly" if isinstance(entry, ttk.Combobox) else "normal")
                self.video_start_button.configure(state="normal")
                self.video_preview_button.configure(state="normal")
                continue
            if error is not None and not isinstance(error, ImportCancelled):
                for entry in self.video_inputs:
                    entry.configure(state="readonly" if isinstance(entry, ttk.Combobox) else "normal")
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
                    self._status(f"视频导入完成，{audio}。请保存 JSON 项目保留音轨。")

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
        if self.video is None:
            self.client_display.pack_forget()
            self.client_choice.pack(side="left")
        else:
            self.client_choice.pack_forget()
            self.client_display.pack(side="left")
        self.entries["transition_ms"].configure(
            state="disabled" if self.fast_clear.get() else "normal",
            textvariable=self.automatic_transition if self.fast_clear.get() else self.fields["transition_ms"])
        self.time_labels[2].configure(text="自动切帧 / ms" if self.fast_clear.get() else "切帧 / ms")
        self.automatic_transition.set("自动")
        hint = "向下滚动 · " + ("固定滚速" if self.target_client.get() == "stable" else "同步游戏滚速") + " · NF，勿用 Auto"
        if self.target_client.get() == "lazer" and len(self.frames[0][0]) > 10:
            hint += "\nlazer >10K 双舞台；11/13/15/17K 会少一列。"
        elif self.target_client.get() == "stable" and len(self.frames[0][0]) * 100 < 480 * DEFAULT_ASPECT_RATIO:
            hint += "\nstable 每列最多 100，当前画布无法铺满横向。"
        self.playback_hint.set(hint)
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
                                            merge_holds=self.merge_holds.get(), target_client=self.target_client.get())
            if self.video is not None:
                self.plan["video"] = self.video.copy()
        except ValueError as error:
            self.plan = None
            self._status(str(error), error=True)
        if self.plan is not None:
            self.timeline = Timeline([Point(**point) for point in self.plan["points"]],
                                     self.plan["base_beat_length_ms"])
            self.note_distances = [self.timeline.position(note["time_ms"]) for note in self.plan["notes"]]
            self.note_end_distances = [self.timeline.position(note.get("end_time_ms", note["time_ms"]))
                                       for note in self.plan["notes"]]
            self.max_note_span = max(end - start for start, end in zip(self.note_distances, self.note_end_distances))
            self.frame_starts = [frame["start_ms"] for frame in self.plan["frames"]]
            self.seek_min = max(0, self.plan["start_ms"] - self.plan["transition_ms"] - 180)
            self.seek_max = self.plan["end_ms"] + self.plan["transition_ms"] + 180
            self.seek.configure(from_=self.seek_min, to=self.seek_max)
            self.seek_time.set(self.plan["frames"][self.selected]["start_ms"])
            self.automatic_transition.set(f"{self.plan['sweep_ms']:.3f}")
            warning = refresh_warning(self.plan)
            self._status(f"就绪 · {len(self.plan['notes'])} 音符"
                         + (" · 含音轨" if self.audio_data is not None else "")
                         + (" · " + warning if warning else ""))
        state = "normal" if self.plan is not None else "disabled"
        self.play_button.configure(state=state)
        self.seek.configure(state=state)
        self.export_button.configure(state=state if not self.exporting else "disabled")
        self._draw_preview()

    def _draw_preview(self):
        self.preview.delete("all")
        width, height = self.preview.winfo_width(), self.preview.winfo_height()
        if self.plan is None:
            self.preview.create_text(width / 2, height / 2, text="绘制图案后预览", fill=MUTED, justify="center")
            self.time_label.set("等待预览")
            return
        full_h = max(1, min(height - 34 * self.scale, (width - 24 * self.scale) / DEFAULT_ASPECT_RATIO))
        stage_h = full_h
        full_w = full_h * DEFAULT_ASPECT_RATIO
        stage_w = full_w * self.plan.get("stage_width_fraction", 1)
        left, top = (width - full_w) / 2, 10 * self.scale
        note_height = stage_h / len(self.plan["pattern"])
        lane = stage_w / self.plan["keys"]
        current = self.seek_time.get()
        position = self.timeline.position(current)
        for col in range(self.plan["keys"]):
            self.preview.create_rectangle(left + col * lane, top, left + (col + 1) * lane, top + full_h,
                                          fill="white", outline="")
            self.preview.create_text(left + (col + 0.5) * lane, top + full_h + 13 * self.scale, text=str(col + 1), fill=MUTED, font=("Segoe UI", 9))
        first = bisect_left(self.note_distances, position - note_height / stage_h * self.plan["time_range_ms"] - self.max_note_span)
        last = bisect_right(self.note_distances, position + self.plan["time_range_ms"])
        for index in range(first, last):
            note, distance = self.plan["notes"][index], self.note_distances[index]
            y = (1 - (distance - position) / self.plan["time_range_ms"]) * stage_h
            tail_y = (1 - (self.note_end_distances[index] - position) / self.plan["time_range_ms"]) * stage_h
            # Keep drawing the body below judgement until the tail is off stage.
            if y > 0 and tail_y < full_h + note_height:
                x = left + note["column"] * lane
                self.preview.create_rectangle(x, max(top, top + tail_y - note_height), x + lane,
                                              min(top + full_h, top + y),
                                              fill="black", outline="",
                                              tags=("note", "hold") if "end_time_ms" in note else "note")
        index = bisect_right(self.frame_starts, current) - 1
        frames = self.plan["frames"]
        holding = index >= 0 and (current <= max(frames[index]["end_ms"], frames[index]["sweep_start_ms"]) or
                                  (index + 1 < len(frames) and
                                   frames[index].get("note_frame", index) == frames[index + 1].get("note_frame", index + 1)))
        frame = index + 1 if holding else None
        phase = f"帧 {frame}/{len(self.frames)}" if frame is not None else "过渡 / 空档"
        self.time_label.set(f"{current / 1000:.2f} s · {phase}")

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
                    self._status("已导出 pattern.osz · 请一并导入对应比例的 pixel-film*.osk"
                                 + (" · 刷新率见播放设置.txt"
                                    if self.video is not None and self.video.get("refresh_hz") is not None else ""))
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
            names = tuple("audio.ogg" if name == "silence.wav" and self.audio_data is not None else skin_filename(name, self.plan["target_client"])
                          for name in OUTPUT_FILES)
            if (output / "播放设置.txt").exists():
                names += ("播放设置.txt",)
            exists = any((output / name).exists() for name in names)
        except (OSError, ValueError) as error:
            self._status(f"导出目录无效：{error}", error=True)
            return
        if exists and not messagebox.askyesno("确认覆盖", "目录中已有生成文件。要覆盖同名的谱面、音频、皮肤、预览和报告吗？\n其他文件不会删除。", parent=self.root):
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
