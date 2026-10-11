"""Shared desktop colours and Tk style setup."""

from tkinter import ttk


BG = "#10131c"
PANEL = "#191f2c"
INK = "#edf1fa"
MUTED = "#a2aec2"
ACCENT = "#f182ad"
MINT = "#70dfcc"
BORDER = "#30394b"
FIELD = "#111722"


def configure_theme(root, scale):
    style = ttk.Style(root)
    style.theme_use("clam")
    gap = round(6 * scale)
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
                        padding=gap, borderwidth=1, arrowsize=round(12 * scale),
                        arrowcolor=MUTED, lightcolor=BORDER, darkcolor=BORDER)
        style.map(name, fieldbackground=[("disabled", PANEL), ("readonly", FIELD)],
                  foreground=[("disabled", MUTED), ("readonly", INK)],
                  bordercolor=[("focus", ACCENT)])
    style.configure("TCheckbutton", background=PANEL, padding=(0, gap // 2),
                    indicatorbackground=FIELD, indicatorforeground=BG,
                    indicatorsize=round(14 * scale), indicatormargin=(0, 0, gap, 0))
    style.map("TCheckbutton", background=[("active", PANEL)],
              foreground=[("disabled", MUTED)],
              indicatorbackground=[("selected", ACCENT), ("active", BORDER)])
    style.configure("Horizontal.TScale", background=MINT, troughcolor=FIELD,
                    sliderlength=round(14 * scale), arrowsize=round(12 * scale),
                    gripcount=0, borderwidth=0, lightcolor=MINT, darkcolor=MINT)
    style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=PANEL,
                    arrowcolor=MUTED, borderwidth=0, arrowsize=round(10 * scale))
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", "#57364d")
    root.option_add("*TCombobox*Listbox.selectForeground", INK)
