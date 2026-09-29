"""Native desktop editor for the existing osu!mania pattern compiler."""

from pathlib import Path
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from osu_paint import Point, Timeline, compile_frames, number, parse_frames, write_output


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
                               ("编辑文本", self.edit_text)]:
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
        settings = ttk.Frame(left)
        settings.grid(row=7, column=0, sticky="ew")
        self.fields = {}
        self.time_labels = []
        self.entries = {}
        for i, (key, label, value) in enumerate([
                ("start_ms", "展示开始 / ms", "2000"), ("end_ms", "展示结束 / ms", "4000"),
                ("transition_ms", "切帧时长 / ms", "12"), ("scroll_speed", "lazer 滚速 / 1–40", "27")]):
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
        ttk.Label(right, text="位置模拟 · 非 lazer 实机画面", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 8))
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
        ttk.Label(right, text="展示为近似停帧。请使用 lazer 默认皮肤、向下滚动，\n同步上方滚速并开启 No Fail；不要启用恒速或变速 MOD。",
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
        if key in ("start_ms", "end_ms"):
            values = self.frame_times[self.selected] if self.timing_mode.get() == "自由模式" else self.uniform_times
            values[0 if key == "start_ms" else 1] = self.fields[key].get()
        self._changed()

    def _mode_changed(self, *args):
        if self.syncing_fields:
            return
        if self.timing_mode.get() == "自由模式" and not self.free_times_initialized:
            try:
                plan = compile_frames(self.frames, *map(float, self.uniform_times),
                                      float(self.fields["scroll_speed"].get()), float(self.fields["transition_ms"].get()),
                                      fast_clear=self.fast_clear.get())
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
                            "lazer 滚速：必须与游戏设置一致。它决定时间距离如何换算成舞台位置，不是动画帧率；"
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
        for i, frame in enumerate(self.frames):
            timing = f"  ·  {self.frame_times[i][0]}–{self.frame_times[i][1]} ms" if self.timing_mode.get() == "自由模式" else ""
            self.frame_list.insert("end", f"  {i + 1:02d}    {'●' if i == self.selected else '○'}    {sum(row.count('#') for row in frame)} 个音符{timing}")
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
        keys = simpledialog.askinteger("新建画布", "按键列数（1–10）：", initialvalue=7, minvalue=1, maxvalue=10, parent=self.root)
        if keys is None:
            return
        rows = simpledialog.askinteger("新建画布", "图案行数：", initialvalue=6, minvalue=1, parent=self.root)
        if rows is not None:
            self.frames, self.selected = [["." * keys for _ in range(rows)]], 0
            self.frame_times = [self.uniform_times.copy()]
            self.free_times_initialized = False
            self._show_time_fields()
            self._changed()

    def load_text(self, text):
        frames = parse_frames(text)
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

    def _text(self):
        return "\n---\n".join("\n".join(frame) for frame in self.frames) + "\n"

    def _project_data(self):
        settings = {key: variable.get() for key, variable in self.fields.items()}
        settings["start_ms"], settings["end_ms"] = self.uniform_times
        return {"format": "osu-paint", "version": 1, "frames": self.frames,
                "frame_times": self.frame_times, "timing_mode": self.timing_mode.get(),
                "settings": settings, "fast_clear": self.fast_clear.get()}

    def load_project(self, data):
        try:
            if data["format"] != "osu-paint" or data["version"] != 1:
                raise ValueError("不支持的项目版本。")
            frames = parse_frames("\n---\n".join("\n".join(frame) for frame in data["frames"]))
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
        self.frames, self.frame_times, self.selected = frames, windows, 0
        self.uniform_times = [settings["start_ms"], settings["end_ms"]]
        self.free_times_initialized = True
        self.syncing_fields = True
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
                self.load_text(text)
        except (OSError, ValueError) as error:
            messagebox.showerror("无法打开图案", str(error), parent=self.root)
            return
        self.dirty = False
        self._update_editor()

    def save_pattern(self):
        try:
            parse_frames(self._text())
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
        self.dirty = text_only and self.timing_mode.get() == "自由模式"
        self._update_editor()
        self._status(f"图案已保存：{filename}（TXT 不保存时间参数，请用 JSON 保存项目）" if text_only
                     else f"项目已保存：{filename}（包含各帧时间与参数）")

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
        self.play_button.configure(text="▶ 播放")

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

    def _refresh_preview(self):
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
            self.preview_job = None
        self._stop()
        try:
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
            self.plan = compile_frames(self.frames, **values, frame_times=windows, fast_clear=self.fast_clear.get())
        except ValueError as error:
            self.plan = None
            self._status(str(error), error=True)
        if self.plan is not None:
            self.timeline = Timeline([Point(**point) for point in self.plan["points"]])
            self.note_distances = [self.timeline.position(note["time_ms"]) for note in self.plan["notes"]]
            self.seek_min = max(0, self.plan["start_ms"] - self.plan["transition_ms"] - 180)
            self.seek_max = self.plan["end_ms"] + self.plan["transition_ms"] + 180
            self.seek.configure(from_=self.seek_min, to=self.seek_max)
            self.seek_time.set(self.plan["frames"][self.selected]["start_ms"])
            self._status(f"{self.plan['keys']}K · {len(self.frames)} 帧 · {len(self.plan['notes'])} 音符 · "
                         f"{'极速' if self.fast_clear.get() else ''}切帧 {self.plan['transition_ms']:.3f} ms · "
                         f"单帧最大预计漂移 {self.plan['drift_at_658px']:.4f} px / 658 px")
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
        for note, distance in zip(self.plan["notes"], self.note_distances):
            y = (1 - (distance - position) / self.plan["time_range_ms"]) * stage_h
            # Keep drawing below judgement until physically off stage. Miss fades aren't simulated.
            if -note_half <= y <= full_h + note_half:
                x = left + note["column"] * lane
                self.preview.create_rectangle(x + 2 * self.scale, max(top, top + y - note_half), x + lane - 2 * self.scale,
                                              min(top + full_h, top + y + note_half),
                                              fill=ACCENT if note["column"] % 2 == 0 else MINT, outline="", tags="note")
        self.preview.create_line(left, top + stage_h, left + stage_w, top + stage_h, fill=INK, width=2)
        frame = next((i + 1 for i, item in enumerate(self.plan["frames"]) if item["start_ms"] <= current <= item["end_ms"]), None)
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
            self._stop()
        else:
            if self.seek_time.get() >= self.seek_max:
                self.seek_time.set(self.seek_min)
            self.playing = True
            self.last_tick = time.perf_counter()
            self.play_button.configure(text="Ⅱ 暂停")

    def _tick(self):
        if self.playing and self.plan is not None:
            now = time.perf_counter()
            current = min(self.seek_max, self.seek_time.get() + (now - self.last_tick) * 1000)
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
                    self._status(f"已导出：{output / 'pattern.osz'} · 可拖入 lazer；也已生成 HTML 预览与报告。")
        self.tick_job = self.root.after(16 if self.playing else 80, self._tick)

    def choose_output(self):
        directory = filedialog.askdirectory(parent=self.root, title="选择导出目录")
        if directory:
            self.output_dir.set(directory)

    def export(self):
        if self.exporting:
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
            exists = any((output / name).exists() for name in OUTPUT_FILES)
        except (OSError, ValueError) as error:
            self._status(f"导出目录无效：{error}", error=True)
            return
        if exists and not messagebox.askyesno("确认覆盖", "目录中已有生成文件。要覆盖同名的谱面、音频、预览和报告吗？\n其他文件不会删除。", parent=self.root):
            return
        plan = self.plan
        self.exporting = True
        self.export_button.configure(state="disabled", text="正在导出…")
        self._status("正在导出当前图案快照…")

        def run():
            try:
                write_output(plan, output)
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
