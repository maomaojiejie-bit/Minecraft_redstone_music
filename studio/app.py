"""Tkinter GUI for the Minecraft RedPiano music workflow."""
import glob
import json
import os
import re
import subprocess
import queue
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path
import numpy as np
import soundfile as sf
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, scrolledtext, simpledialog, ttk

try:
    from PIL import Image, ImageOps, ImageTk
    PIL_OK = True
    try:
        RESAMPLE = Image.Resampling.LANCZOS
    except Exception:
        RESAMPLE = Image.LANCZOS
except Exception:
    PIL_OK = False
    RESAMPLE = None

from .paths import (
    ASSETS_DIR, BASE_DIR, BINARIES_DIR, OUTPUT_DIR, PYTHON,
    SCRIPTS_DIR, SKILL_DIR, ensure_dir, script_path,
)
from . import online_soundpack
from . import preview_audio
from .preview3d import TrackPreviewWindow
from .runner import ProcessRunner
from .sf2_synth import SoundFont, SR
from .soundpack import extend_note_durations, make_custom_pack, remap_voice_to_piano


FORM_OPTIONS = [
    ("原地紧凑型 (inplace)", "inplace"),
    ("S 形折线型 (swave)", "swave"),
    ("直线型 (straight)", "straight"),
    ("自定义路线 (custom)", "custom"),
    ("多轨并行型 (multilane)", "multilane"),
]
FORM_LABEL_TO_VALUE = {label: val for label, val in FORM_OPTIONS}
FORM_VALUE_TO_LABEL = {val: label for label, val in FORM_OPTIONS}

MC_VERSIONS = [
    "1.21", "1.21.1", "1.21.2", "1.21.3", "1.21.4",
    "1.21.5", "1.21.6", "1.21.7", "1.21.8", "1.21.9", "1.21.10",
]


class StudioApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("红石音乐工作室 - Minecraft RedPiano")
        self.geometry("1180x780")
        self.minsize(980, 680)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.project = self.default_project()
        try:
            self.project.update({k: v for k, v in self._load_settings().items() if k in self.project})
        except Exception:
            pass
        self.runner = ProcessRunner(self, self.append_log, self.on_process_done)
        self._target_text = None
        self._busy = False
        self._preview_wav = None
        self._preview_playing = False
        self._preview_thread = None
        self._preview_queue = queue.Queue()
        self._pending_musescore_out = None
        self._pending_flstudio_out = None
        self._pending_online_out = None
        self._online_results = []
        self._preset_display = {}
        self._online_queue = queue.Queue()
        self._make_vars()
        self._build_menu()
        self._build_ui()
        self.apply_project(self.project)
        self.detect_defaults(silent=True)
        self.after(200, self._poll_online_queue)

    def default_project(self):
        return {
            "midi": "", "ns": "putao",
            "origin_x": "0", "origin_z": "0", "origin_y": "200",
            "mc_version": "1.21.1", "form": "multilane",
            "params": "", "world_dir": "", "profile_dir": "",
            "dist": "dist", "prebuilt_mod_jar": "", "fabric_api_jar": "",
            "force_cap": True, "sound_mode": "default", "custom_rp": "",
            "sound_preset": "默认（skill 自带）",
            "guitar": True, "pad_flute": True, "voice_to_piano": False,
            "crash_volume": 35, "pno_vol": 100, "lead_vol": 100,
            "pad_vol": 100, "bass_vol": 100, "drum_vol": 100,
            "sustain": False,
            "sustain_max_gap": 2.0, "melcap": 4.0,
            "bg_image": "", "bg_color": "#dfe6e9",
            "bg_fit": "填充窗口（裁剪）", "theme": "浅色",
            "preview_seconds": 30,
        }

    def _make_vars(self):
        self.var_midi = tk.StringVar()
        self.var_ns = tk.StringVar()
        self.var_origin_x = tk.StringVar()
        self.var_origin_z = tk.StringVar()
        self.var_origin_y = tk.StringVar()
        self.var_mc_version = tk.StringVar()
        self.var_form = tk.StringVar()
        self.var_params = tk.StringVar()
        self.var_world_dir = tk.StringVar()
        self.var_profile_dir = tk.StringVar()
        self.var_dist = tk.StringVar()
        self.var_mod_jar = tk.StringVar()
        self.var_fabric_api = tk.StringVar()
        self.var_force_cap = tk.BooleanVar()
        self.var_sound_mode = tk.StringVar(value="default")
        self.var_sound_preset = tk.StringVar(value="默认（skill 自带）")
        self.var_custom_rp = tk.StringVar()
        self.var_guitar = tk.BooleanVar(value=True)
        self.var_pad_flute = tk.BooleanVar(value=True)
        self.var_voice_to_piano = tk.BooleanVar(value=False)
        self.var_crash_volume = tk.IntVar(value=35)
        self.var_pno_vol = tk.IntVar(value=100)
        self.var_lead_vol = tk.IntVar(value=100)
        self.var_pad_vol = tk.IntVar(value=100)
        self.var_bass_vol = tk.IntVar(value=100)
        self.var_drum_vol = tk.IntVar(value=100)
        self.var_sustain = tk.BooleanVar(value=False)
        self.var_sustain_gap = tk.DoubleVar(value=2.0)
        self.var_melcap = tk.DoubleVar(value=4.0)
        self.var_bg_image = tk.StringVar()
        self.var_bg_color = tk.StringVar(value="#dfe6e9")
        self.var_bg_fit = tk.StringVar(value="填充窗口（裁剪）")
        self.var_theme = tk.StringVar(value="浅色")
        self.var_online_query = tk.StringVar()
        self.var_online_sf2 = tk.StringVar()
        self.var_online_status = tk.StringVar(value="就绪")
        self.var_map_pno = tk.StringVar()
        self.var_map_lead = tk.StringVar()
        self.var_map_pad = tk.StringVar()
        self.var_map_bass = tk.StringVar()
        self.var_map_drum = tk.StringVar()
        self.var_preview_seconds = tk.IntVar(value=30)
        self.var_preview_status = tk.StringVar(value="未生成预览")
        self.var_status = tk.StringVar(value="就绪")

    def apply_project(self, p):
        self.var_midi.set(p.get("midi", ""))
        self.var_ns.set(p.get("ns", "putao"))
        self.var_origin_x.set(str(p.get("origin_x", "0")))
        self.var_origin_z.set(str(p.get("origin_z", "0")))
        self.var_origin_y.set(str(p.get("origin_y", "200")))
        self.var_mc_version.set(p.get("mc_version", "1.21.1"))
        self.var_form.set(FORM_VALUE_TO_LABEL.get(p.get("form", "multilane"), p.get("form", "multilane")))
        self.var_params.set(p.get("params", ""))
        self.var_world_dir.set(p.get("world_dir", ""))
        self.var_profile_dir.set(p.get("profile_dir", ""))
        self.var_dist.set(p.get("dist", "dist"))
        self.var_mod_jar.set(p.get("prebuilt_mod_jar", ""))
        self.var_fabric_api.set(p.get("fabric_api_jar", ""))
        self.var_force_cap.set(bool(p.get("force_cap", True)))
        self.var_sound_mode.set(p.get("sound_mode", "default"))
        self.var_sound_preset.set(p.get("sound_preset", "默认（skill 自带）"))
        self.var_custom_rp.set(p.get("custom_rp", ""))
        self.var_guitar.set(bool(p.get("guitar", True)))
        self.var_pad_flute.set(bool(p.get("pad_flute", True)))
        self.var_voice_to_piano.set(bool(p.get("voice_to_piano", False)))
        self.var_crash_volume.set(int(p.get("crash_volume", 35)))
        self.var_pno_vol.set(int(p.get("pno_vol", 100)))
        self.var_lead_vol.set(int(p.get("lead_vol", 100)))
        self.var_pad_vol.set(int(p.get("pad_vol", 100)))
        self.var_bass_vol.set(int(p.get("bass_vol", 100)))
        self.var_drum_vol.set(int(p.get("drum_vol", 100)))
        self.var_sustain.set(bool(p.get("sustain", False)))
        self.var_sustain_gap.set(float(p.get("sustain_max_gap", 2.0)))
        self.var_melcap.set(float(p.get("melcap", 4.0)))
        self.var_bg_image.set(p.get("bg_image", ""))
        self.var_bg_color.set(p.get("bg_color", "#dfe6e9"))
        self.var_bg_fit.set(p.get("bg_fit", "填充窗口（裁剪）"))
        self.var_theme.set(p.get("theme", "浅色"))
        self.var_preview_seconds.set(int(p.get("preview_seconds", 30)))
        self.var_preview_status.set("未生成预览")
        self._sync_sound_widgets()
        self.apply_theme(self.var_theme.get())
        self.apply_background(silent=True)

    def collect_project(self):
        return {
            "midi": self.var_midi.get().strip(),
            "ns": self.var_ns.get().strip() or "putao",
            "origin_x": self.var_origin_x.get().strip() or "0",
            "origin_z": self.var_origin_z.get().strip() or "0",
            "origin_y": self.var_origin_y.get().strip() or "200",
            "mc_version": self.var_mc_version.get().strip() or "1.21.1",
            "form": FORM_LABEL_TO_VALUE.get(self.var_form.get().strip(), self.var_form.get().strip()) or "multilane",
            "params": self.var_params.get().strip(),
            "world_dir": self.var_world_dir.get().strip(),
            "profile_dir": self.var_profile_dir.get().strip(),
            "dist": self.var_dist.get().strip() or "dist",
            "prebuilt_mod_jar": self.var_mod_jar.get().strip(),
            "fabric_api_jar": self.var_fabric_api.get().strip(),
            "force_cap": bool(self.var_force_cap.get()),
            "sound_mode": self.var_sound_mode.get(),
            "sound_preset": self.var_sound_preset.get(),
            "custom_rp": self.var_custom_rp.get().strip(),
            "guitar": bool(self.var_guitar.get()),
            "pad_flute": bool(self.var_pad_flute.get()),
            "voice_to_piano": bool(self.var_voice_to_piano.get()),
            "crash_volume": int(self.var_crash_volume.get()),
            "pno_vol": int(self.var_pno_vol.get()),
            "lead_vol": int(self.var_lead_vol.get()),
            "pad_vol": int(self.var_pad_vol.get()),
            "bass_vol": int(self.var_bass_vol.get()),
            "drum_vol": int(self.var_drum_vol.get()),
            "sustain": bool(self.var_sustain.get()),
            "sustain_max_gap": float(self.var_sustain_gap.get()),
            "melcap": float(self.var_melcap.get()),
            "bg_image": self.var_bg_image.get().strip(),
            "bg_color": self.var_bg_color.get().strip(),
            "bg_fit": self.var_bg_fit.get(),
            "theme": self.var_theme.get(),
            "preview_seconds": int(self.var_preview_seconds.get()),
        }

    # ------------------------------------------------------------------- menu
    def _build_menu(self):
        menu = tk.Menu(self)
        fm = tk.Menu(menu, tearoff=False)
        fm.add_command(label="新建项目", command=self.new_project)
        fm.add_command(label="打开项目...", command=self.load_project_dialog)
        fm.add_command(label="保存项目", command=self.save_project)
        fm.add_command(label="另存为...", command=self.save_project_as)
        fm.add_separator()
        fm.add_command(label="退出", command=self.destroy)
        menu.add_cascade(label="文件", menu=fm)
        tm = tk.Menu(menu, tearoff=False)
        tm.add_command(label="原版布局设计器", command=self.open_layout_designer)
        tm.add_command(label="打开粒子编辑器", command=self.open_particle_editor)
        tm.add_command(label="打开 skill 目录", command=lambda: self.open_path(SKILL_DIR))
        tm.add_command(label="试听预览", command=self.generate_preview)
        menu.add_cascade(label="工具", menu=tm)
        vm = tk.Menu(menu, tearoff=False)
        vm.add_command(label="界面设置", command=self._show_appearance_tab)
        vm.add_command(label="选择背景图片...", command=self.choose_background_image)
        vm.add_command(label="选择背景颜色...", command=self.choose_background_color)
        vm.add_command(label="清除背景", command=self.clear_background)
        vm.add_separator()
        vm.add_command(label="浅色主题", command=lambda: self.apply_theme("浅色"))
        vm.add_command(label="深色主题", command=lambda: self.apply_theme("深色"))
        menu.add_cascade(label="界面", menu=vm)
        hm = tk.Menu(menu, tearoff=False)
        hm.add_command(label="关于", command=self.show_about)
        menu.add_cascade(label="帮助", menu=hm)
        self.config(menu=menu)

    # -------------------------------------------------------------------- ui
    def _build_ui(self):
        self._setup_style()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.bg_label = tk.Label(self, bd=0, highlightthickness=0)
        self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.bg_label.lower()
        self.card = tk.Frame(self, bd=0, highlightthickness=1)
        self.card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.96, relheight=0.94)
        self.card.columnconfigure(0, weight=1)
        self.card.rowconfigure(1, weight=1)
        header = ttk.Frame(self.card)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="红石音乐工作室", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Minecraft RedPiano · MIDI → 红石音乐", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        self.nb = ttk.Notebook(self.card)
        self.nb.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 4))
        self._build_song_tab()
        self._build_build_tab()
        self._build_sound_tab()
        self._build_online_tab()
        self._build_deploy_tab()
        self._build_appearance_tab()
        status = ttk.Frame(self.card)
        status.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.var_status, anchor="w").grid(row=0, column=0, sticky="ew")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.progress.grid_remove()
        self._bg_source = None
        self._bg_photo = None
        self._bg_preview_photo = None
        self._bg_after = None
        self._bg_silent = False
        self._apply_card_colors()
        self.bind("<Configure>", self._on_window_configure)

    def destroy(self):
        try:
            self._save_settings()
        except Exception:
            pass
        super().destroy()

    def _load_settings(self):
        path = BASE_DIR / "studio_settings.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def _save_settings(self):
        data = {
            "bg_image": self.var_bg_image.get(),
            "bg_color": self.var_bg_color.get(),
            "bg_fit": self.var_bg_fit.get(),
            "theme": self.var_theme.get(),
        }
        try:
            (BASE_DIR / "studio_settings.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _show_appearance_tab(self):
        if hasattr(self, "tab_appearance"):
            self.nb.select(self.tab_appearance)

    def _theme_palette(self, theme):
        dark = theme == "深色"
        if dark:
            return {
                "window_bg": "#181825", "card_bg": "#1e1e2e", "fg": "#cdd6f4",
                "muted": "#a6adc8", "entry_bg": "#313244", "button_bg": "#45475a",
                "button_active": "#585b70", "accent": "#89b4fa", "border": "#313244",
                "select_bg": "#89b4fa", "select_fg": "#1e1e2e",
            }
        return {
            "window_bg": "#dfe6e9", "card_bg": "#ffffff", "fg": "#2f3542",
            "muted": "#747d8c", "entry_bg": "#f8f9fa", "button_bg": "#e8ecf1",
            "button_active": "#4a69bd", "accent": "#4a69bd", "border": "#dcdde1",
            "select_bg": "#4a69bd", "select_fg": "#ffffff",
        }

    def _setup_style(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        p = self._theme_palette(self.var_theme.get() if hasattr(self, "var_theme") else "浅色")
        self._palette = p
        f = ("Microsoft YaHei UI", 10)
        try:
            self.option_add("*Font", "{Microsoft YaHei UI} 10")
            self.option_add("*Text.Font", "{Microsoft YaHei UI} 10")
        except Exception:
            pass
        self.style.configure(".", font=f, background=p["card_bg"], foreground=p["fg"])
        self.style.configure("TFrame", background=p["card_bg"])
        self.style.configure("TLabel", background=p["card_bg"], foreground=p["fg"])
        self.style.configure("Muted.TLabel", background=p["card_bg"], foreground=p["muted"])
        self.style.configure("Title.TLabel", background=p["card_bg"], foreground=p["accent"],
                             font=("Microsoft YaHei UI", 15, "bold"))
        self.style.configure("TButton", background=p["button_bg"], foreground=p["fg"],
                             padding=(10, 5), borderwidth=0, focusthickness=0, focuscolor=p["card_bg"])
        self.style.map("TButton",
                       background=[("active", p["button_active"]), ("pressed", p["button_active"]), ("disabled", p["button_bg"])],
                       foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])
        self.style.configure("Accent.TButton", background=p["accent"], foreground="#ffffff",
                             padding=(12, 6), borderwidth=0, focusthickness=0, focuscolor=p["accent"])
        self.style.map("Accent.TButton",
                       background=[("active", p["button_active"]), ("pressed", p["button_active"])],
                       foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])
        self.style.configure("TEntry", fieldbackground=p["entry_bg"], foreground=p["fg"],
                             insertcolor=p["fg"], borderwidth=1, bordercolor=p["border"], padding=4)
        self.style.map("TEntry", bordercolor=[("focus", p["accent"])])
        self.style.configure("TCombobox", fieldbackground=p["entry_bg"], background=p["button_bg"],
                             foreground=p["fg"], arrowcolor=p["fg"], borderwidth=1,
                             bordercolor=p["border"], padding=4)
        self.style.map("TCombobox",
                       fieldbackground=[("readonly", p["entry_bg"])],
                       foreground=[("readonly", p["fg"])],
                       bordercolor=[("focus", p["accent"])])
        self.style.configure("TNotebook", background=p["card_bg"], borderwidth=0, tabmargins=(4, 4, 4, 0))
        self.style.configure("TNotebook.Tab", background=p["button_bg"], foreground=p["fg"],
                             padding=(14, 7), borderwidth=0)
        self.style.map("TNotebook.Tab",
                       background=[("selected", p["card_bg"])],
                       foreground=[("selected", p["accent"])])
        self.style.configure("TLabelframe", background=p["card_bg"], foreground=p["accent"],
                             bordercolor=p["border"], borderwidth=1, relief="solid")
        self.style.configure("TLabelframe.Label", background=p["card_bg"], foreground=p["accent"],
                             font=("Microsoft YaHei UI", 10, "bold"))
        self.style.configure("TCheckbutton", background=p["card_bg"], foreground=p["fg"])
        self.style.map("TCheckbutton", background=[("active", p["card_bg"])])
        self.style.configure("Horizontal.TScale", background=p["card_bg"], troughcolor=p["entry_bg"])
        self.style.configure("TProgressbar", background=p["accent"], troughcolor=p["entry_bg"])

    def _apply_card_colors(self):
        p = getattr(self, "_palette", self._theme_palette("浅色"))
        if hasattr(self, "card"):
            self.card.configure(bg=p["card_bg"], highlightbackground=p["border"], highlightcolor=p["border"])
        if hasattr(self, "bg_label") and not getattr(self, "_bg_source", None):
            self.bg_label.configure(bg=self.var_bg_color.get().strip() or p["window_bg"])
        for name in ("song_text", "build_text", "deploy_text"):
            w = getattr(self, name, None)
            if w is not None:
                try:
                    w.configure(bg=p["entry_bg"], fg=p["fg"], insertbackground=p["fg"],
                                selectbackground=p["select_bg"], selectforeground=p["select_fg"])
                except Exception:
                    pass

    def apply_theme(self, theme=None):
        if theme:
            self.var_theme.set(theme)
        self._setup_style()
        self._apply_card_colors()
        self._render_background()
        self._save_settings()

    def _on_window_configure(self, event=None):
        if event is not None and event.widget is not self:
            return
        if getattr(self, "_bg_after", None):
            try:
                self.after_cancel(self._bg_after)
            except Exception:
                pass
        self._bg_after = self.after(120, self._render_background)

    def _render_background(self):
        self._bg_after = None
        if not hasattr(self, "bg_label"):
            return
        p = getattr(self, "_palette", self._theme_palette("浅色"))
        color = self.var_bg_color.get().strip() or p["window_bg"]
        self.bg_label.configure(bg=color)
        src = getattr(self, "_bg_source", None)
        if src is None:
            self.bg_label.configure(image="")
            self._bg_photo = None
            return
        if not PIL_OK:
            self.var_bg_image.set("")
            self._bg_source = None
            self.bg_label.configure(image="")
            self._bg_photo = None
            if not getattr(self, "_bg_silent", False):
                messagebox.showwarning("缺少 Pillow", "需要 Pillow 才能加载和缩放背景图片。")
            return
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        if w <= 2 or h <= 2:
            self.after(200, self._render_background)
            return
        fit = self.var_bg_fit.get()
        try:
            if fit == "平铺":
                tile = src.convert("RGB")
                img = Image.new("RGB", (w, h), color)
                tw, th = tile.size
                for y in range(0, h, th):
                    for x in range(0, w, tw):
                        img.paste(tile, (x, y))
            elif fit == "居中":
                img = Image.new("RGB", (w, h), color)
                x = max(0, (w - src.width) // 2)
                y = max(0, (h - src.height) // 2)
                img.paste(src.convert("RGB"), (x, y))
            elif fit == "适应窗口（留边）":
                img = Image.new("RGB", (w, h), color)
                thumb = ImageOps.contain(src, (w, h), RESAMPLE)
                x = (w - thumb.width) // 2
                y = (h - thumb.height) // 2
                img.paste(thumb, (x, y))
            else:
                img = ImageOps.fit(src, (w, h), RESAMPLE)
            self._bg_photo = ImageTk.PhotoImage(img)
            self.bg_label.configure(image=self._bg_photo)
        except Exception as exc:
            self.var_bg_image.set("")
            self._bg_source = None
            self.bg_label.configure(image="")
            self._bg_photo = None
            if not getattr(self, "_bg_silent", False):
                messagebox.showerror("背景加载失败", str(exc))

    def apply_background(self, silent=False):
        self._bg_silent = silent
        path = self.var_bg_image.get().strip()
        if path:
            if not Path(path).is_file():
                if not silent:
                    messagebox.showerror("背景图片不存在", path)
                self._bg_source = None
                self.bg_label.configure(image="")
                self._bg_photo = None
                return
            if not PIL_OK:
                if not silent:
                    messagebox.showwarning("缺少 Pillow", "需要 Pillow 才能加载背景图片。")
                self._bg_source = None
                self.bg_label.configure(image="")
                self._bg_photo = None
                return
            try:
                self._bg_source = Image.open(path)
            except Exception as exc:
                if not silent:
                    messagebox.showerror("无法打开图片", str(exc))
                self._bg_source = None
                self.bg_label.configure(image="")
                self._bg_photo = None
                return
        else:
            self._bg_source = None
        self._render_background()
        self._save_settings()

    def choose_background_image(self):
        path = filedialog.askopenfilename(
            title="选择背景图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("所有文件", "*.*")])
        if not path:
            return
        self.var_bg_image.set(path)
        self.apply_background()
        self._show_appearance_tab()

    def choose_background_color(self):
        picked = colorchooser.askcolor(color=self.var_bg_color.get() or "#dfe6e9", title="选择背景颜色")
        if not picked or not picked[1]:
            return
        self.var_bg_color.set(picked[1])
        self.apply_background()
        self._show_appearance_tab()

    def clear_background(self):
        self.var_bg_image.set("")
        self._bg_source = None
        self._bg_photo = None
        self.bg_label.configure(image="")
        self.apply_background(silent=True)

    def reset_appearance(self):
        self.var_bg_image.set("")
        self.var_bg_color.set("#dfe6e9")
        self.var_bg_fit.set("填充窗口（裁剪）")
        self.var_theme.set("浅色")
        self._bg_source = None
        self._bg_photo = None
        self.bg_label.configure(image="")
        self.apply_theme("浅色")
        self.apply_background(silent=True)

    def _build_appearance_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="界面设置")
        self.tab_appearance = tab
        tab.columnconfigure(0, weight=1)
        bgf = ttk.LabelFrame(tab, text="自定义背景")
        bgf.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        bgf.columnconfigure(1, weight=1)
        self._row(bgf, "背景图片", self.var_bg_image, 0, browse_file=True,
                  filetypes=[("图片", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("所有文件", "*.*")])
        ttk.Label(bgf, text="背景颜色").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(bgf, textvariable=self.var_bg_color, width=16).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Button(bgf, text="选择颜色", command=self.choose_background_color).grid(row=1, column=2, padx=(6, 0), pady=3)
        self._row_combo(bgf, "适应方式", self.var_bg_fit,
                        ["填充窗口（裁剪）", "适应窗口（留边）", "平铺", "居中"], 2)
        thf = ttk.LabelFrame(tab, text="界面主题")
        thf.grid(row=1, column=0, sticky="ew", padx=8, pady=8)
        thf.columnconfigure(1, weight=1)
        self._row_combo(thf, "主题", self.var_theme, ["浅色", "深色"], 0)
        ttk.Label(thf, text="提示：深色主题适合夜间使用；界面设置会自动保存到 studio_settings.json。",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=4)
        act = ttk.Frame(tab)
        act.grid(row=2, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Button(act, text="应用背景", command=self.apply_background, style="Accent.TButton").pack(side="left")
        ttk.Button(act, text="清除背景", command=self.clear_background).pack(side="left", padx=(8, 0))
        ttk.Button(act, text="恢复默认外观", command=self.reset_appearance).pack(side="left", padx=(8, 0))
        ttk.Button(act, text="立即应用主题", command=lambda: self.apply_theme(self.var_theme.get())).pack(side="left", padx=(8, 0))
        prev = ttk.LabelFrame(tab, text="背景预览")
        prev.grid(row=3, column=0, sticky="nsew", padx=8, pady=8)
        tab.rowconfigure(3, weight=1)
        prev.columnconfigure(0, weight=1)
        prev.rowconfigure(0, weight=1)
        self.bg_preview = tk.Canvas(prev, height=180, highlightthickness=0, bd=0)
        self.bg_preview.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.bg_preview.bind("<Configure>", lambda e: self._draw_bg_preview())
        ttk.Label(prev, text="当前背景会显示在主窗口四周。", style="Muted.TLabel").grid(row=1, column=0, sticky="w", padx=6, pady=(0, 6))
        self.after(300, self._draw_bg_preview)

    def _draw_bg_preview(self):
        if not hasattr(self, "bg_preview"):
            return
        c = self.bg_preview
        w = max(1, c.winfo_width())
        h = max(1, c.winfo_height())
        color = self.var_bg_color.get().strip() or "#dfe6e9"
        c.delete("all")
        c.configure(bg=color)
        src = getattr(self, "_bg_source", None)
        if src is None or not PIL_OK:
            c.create_text(w // 2, h // 2, text="未选择背景图片", fill="#888888")
            return
        try:
            fit = self.var_bg_fit.get()
            if fit == "平铺":
                tile = src.convert("RGB")
                img = Image.new("RGB", (w, h), color)
                tw, th = tile.size
                for y in range(0, h, th):
                    for x in range(0, w, tw):
                        img.paste(tile, (x, y))
            elif fit == "居中":
                img = Image.new("RGB", (w, h), color)
                x = max(0, (w - src.width) // 2)
                y = max(0, (h - src.height) // 2)
                img.paste(src.convert("RGB"), (x, y))
            elif fit == "适应窗口（留边）":
                img = Image.new("RGB", (w, h), color)
                thumb = ImageOps.contain(src, (w, h), RESAMPLE)
                x = (w - thumb.width) // 2
                y = (h - thumb.height) // 2
                img.paste(thumb, (x, y))
            else:
                img = ImageOps.fit(src, (w, h), RESAMPLE)
            self._bg_preview_photo = ImageTk.PhotoImage(img)
            c.create_image(0, 0, anchor="nw", image=self._bg_preview_photo)
        except Exception:
            c.create_text(w // 2, h // 2, text="预览失败", fill="#888888")

    def _row(self, parent, label, var, row, browse_file=False, browse_dir=False, width=70, filetypes=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="ew", pady=3)
        col = 2
        if browse_file:
            ttk.Button(parent, text="浏览...", command=lambda: self.browse_file(var, filetypes)).grid(
                row=row, column=col, padx=(6, 0), pady=3)
            col += 1
        if browse_dir:
            ttk.Button(parent, text="浏览...", command=lambda: self.browse_dir(var)).grid(
                row=row, column=col, padx=(6, 0), pady=3)
            col += 1
        return col

    def _row_combo(self, parent, label, var, values, row, display_labels=None, width=40):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=3)
        combo = ttk.Combobox(parent, textvariable=var, values=values, width=width, state="readonly")
        combo.grid(row=row, column=1, sticky="w", pady=3)
        return 2

    def _build_song_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="歌曲与检查")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(3, weight=1)
        self._row(tab, "MIDI 文件", self.var_midi, 0, browse_file=True,
                  filetypes=[("MIDI", "*.mid *.midi"), ("所有文件", "*.*")], width=95)
        btns = ttk.Frame(tab)
        btns.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 4))
        ttk.Button(btns, text="分析歌曲", command=self.analyze_song).pack(side="left")
        ttk.Button(btns, text="试听预览", command=self.generate_preview).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="清空输出", command=lambda: self.clear_text(self.song_text)).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="原版布局设计器", command=self.open_layout_designer).pack(side="left", padx=(8, 0))
        ttk.Label(tab, text="检查结果：").grid(row=2, column=0, sticky="w", pady=(8, 2))
        self.song_text = scrolledtext.ScrolledText(tab, width=130, height=30, wrap="word")
        self.song_text.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(0, 4))

    def _build_build_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="机器与生成")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)
        basic = ttk.LabelFrame(tab, text="基础设置")
        basic.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        basic.columnconfigure(1, weight=1)
        self._row(basic, "MIDI 文件", self.var_midi, 0, browse_file=True,
                  filetypes=[("MIDI", "*.mid *.midi"), ("所有文件", "*.*")])
        self._row(basic, "命名空间 ns", self.var_ns, 1)
        self._row_combo(basic, "Minecraft 版本", self.var_mc_version, MC_VERSIONS, 2)
        self._row_combo(basic, "机器形态", self.var_form, [x[0] for x in FORM_OPTIONS], 3)
        ttk.Label(basic, text="原点坐标（顺序 X Z Y）").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=3)
        origin = ttk.Frame(basic)
        origin.grid(row=4, column=1, sticky="w", pady=3)
        for label, var in (("X", self.var_origin_x), ("Z", self.var_origin_z), ("Y", self.var_origin_y)):
            ttk.Label(origin, text=label).pack(side="left", padx=(0, 3))
            ttk.Entry(origin, textvariable=var, width=8).pack(side="left", padx=(0, 10))
        paths = ttk.LabelFrame(tab, text="路径与依赖")
        paths.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        paths.columnconfigure(1, weight=1)
        self._row(paths, "世界 datapacks 目录", self.var_world_dir, 0, browse_dir=True)
        self._row(paths, "游戏 profile 目录", self.var_profile_dir, 1, browse_dir=True)
        self._row(paths, "输出 dist 目录", self.var_dist, 2, browse_dir=True)
        self._row(paths, "自定义 params.json", self.var_params, 3, browse_file=True,
                  filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        self._row(paths, "RedPiano mod jar", self.var_mod_jar, 4, browse_file=True,
                  filetypes=[("Jar", "*.jar"), ("所有文件", "*.*")])
        self._row(paths, "Fabric API jar", self.var_fabric_api, 5, browse_file=True,
                  filetypes=[("Jar", "*.jar"), ("所有文件", "*.*")])
        ttk.Checkbutton(paths, text="允许超过 forceload 软上限（--force-cap）", variable=self.var_force_cap).grid(
            row=6, column=1, sticky="w", pady=4)
        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, sticky="w", padx=4, pady=(2, 4))
        self.btn_detect = ttk.Button(actions, text="自动检测依赖", command=self.detect_defaults)
        self.btn_detect.pack(side="left")
        self.btn_build = ttk.Button(actions, text="生成安装包", command=self.build_machine)
        self.btn_build.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="打开输出目录", command=self.open_output_dir).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="3D 预览 / 轨道布局", command=self.open_preview3d).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="生成圆环音轨参数", command=self.generate_tube_params).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="导入设计器 JSON", command=self.import_designer_json).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="清空日志", command=lambda: self.clear_text(self.build_text)).pack(side="left", padx=(8, 0))
        logf = ttk.LabelFrame(tab, text="生成日志")
        logf.grid(row=3, column=0, sticky="nsew", padx=4, pady=4)
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        self.build_text = scrolledtext.ScrolledText(logf, width=140, height=18, wrap="word")
        self.build_text.grid(row=0, column=0, sticky="nsew")

    def _build_sound_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="音效包")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        canvas = tk.Canvas(tab, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)
        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.columnconfigure(0, weight=1)

        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfigure(window_id, width=event.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_wheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            for child in widget.winfo_children():
                _bind_wheel(child)
        mode = ttk.LabelFrame(inner, text="资源包选择")
        mode.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        mode.columnconfigure(1, weight=1)
        ttk.Radiobutton(mode, text="使用 skill 自带音效包", variable=self.var_sound_mode,
                        value="default", command=self._sync_sound_widgets).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Radiobutton(mode, text="使用自定义 qzpno_mv.zip", variable=self.var_sound_mode,
                        value="custom", command=self._sync_sound_widgets).grid(row=1, column=0, sticky="w", pady=3)
        self.ent_custom_rp = ttk.Entry(mode, textvariable=self.var_custom_rp, width=90)
        self.ent_custom_rp.grid(row=1, column=1, sticky="ew", padx=(6, 6), pady=3)
        self.btn_custom_rp = ttk.Button(mode, text="浏览...", command=lambda: self.browse_file(
            self.var_custom_rp, [("Zip", "*.zip"), ("所有文件", "*.*")]))
        self.btn_custom_rp.grid(row=1, column=2, padx=(0, 4), pady=3)
        ttk.Label(mode, text="音效包预设").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(mode, textvariable=self.var_sound_preset, state="readonly", width=24,
                     values=["默认（skill 自带）", "吉他 + 长笛（推荐）", "NeuralNote 乐器映射", "MuseScore 乐器映射", "FL Studio 乐器映射", "在线音色库（自定义）"]).grid(
            row=2, column=1, sticky="w", padx=(6, 6), pady=3)
        ttk.Button(mode, text="应用预设", command=self.apply_sound_preset).grid(row=2, column=2, padx=(0, 4), pady=3)
        opts = ttk.LabelFrame(inner, text="常用音色修正")
        opts.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        ttk.Checkbutton(opts, text="吉他音轨使用原版吉他音色（lead_* -> note_block.guitar）",
                        variable=self.var_guitar).grid(row=0, column=0, sticky="w", pady=3)
        ttk.Checkbutton(opts, text="弦乐/铺底使用原版长笛音色（pad_* -> note_block.flute）",
                        variable=self.var_pad_flute).grid(row=1, column=0, sticky="w", pady=3)
        ttk.Checkbutton(opts, text="Voice 轨改成钢琴（GM 52 -> 0）",
                        variable=self.var_voice_to_piano).grid(row=2, column=0, sticky="w", pady=3)
        vol = ttk.Frame(opts)
        vol.grid(row=3, column=0, sticky="w", pady=3)
        ttk.Label(vol, text="crash / 锣声音量：").pack(side="left")
        ttk.Scale(vol, from_=0, to=100, variable=self.var_crash_volume, orient="horizontal", length=220).pack(side="left", padx=(6, 6))
        ttk.Label(vol, textvariable=self.var_crash_volume).pack(side="left")
        sus = ttk.LabelFrame(opts, text="延音填补空档")
        sus.grid(row=4, column=0, sticky="w", pady=3)
        ttk.Checkbutton(sus, text="启用延音填补空档", variable=self.var_sustain).grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Label(sus, text="最大空档秒数").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        ttk.Spinbox(sus, from_=0.1, to=8.0, increment=0.1, textvariable=self.var_sustain_gap, width=8).grid(row=1, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(sus, text="旋律延音上限秒数").grid(row=2, column=0, sticky="w", padx=4, pady=3)
        ttk.Spinbox(sus, from_=0.5, to=12.0, increment=0.5, textvariable=self.var_melcap, width=8).grid(row=2, column=1, sticky="w", padx=4, pady=3)
        vols = ttk.LabelFrame(opts, text="各乐器音量（%）")
        vols.grid(row=5, column=0, sticky="w", pady=3)
        vol_items = [
            ("钢琴 pno", self.var_pno_vol),
            ("主音/吉他 lead", self.var_lead_vol),
            ("弦乐/铺底 pad", self.var_pad_vol),
            ("贝斯 bass", self.var_bass_vol),
            ("鼓组 drum", self.var_drum_vol),
        ]
        for i, (label, var) in enumerate(vol_items):
            ttk.Label(vols, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=2)
            ttk.Scale(vols, from_=0, to=200, variable=var, orient="horizontal", length=180).grid(row=i, column=1, sticky="w", padx=4, pady=2)
            ttk.Label(vols, textvariable=var).grid(row=i, column=2, sticky="w", padx=4, pady=2)
        act = ttk.Frame(inner)
        act.grid(row=2, column=0, sticky="w", padx=4, pady=(2, 4))
        ttk.Button(act, text="生成自定义音效包", command=self.generate_soundpack).pack(side="left")
        ttk.Button(act, text="打开 skill 音效包目录", command=lambda: self.open_path(ASSETS_DIR)).pack(side="left", padx=(8, 0))
        ttk.Button(act, text="生成 NeuralNote 音效包", command=self.generate_neuralnote_pack).pack(side="left", padx=(8, 0))
        ttk.Button(act, text="生成 MuseScore 音效包", command=self.generate_musescore_pack).pack(side="left", padx=(8, 0))
        ttk.Button(act, text="生成 FL Studio 音效包", command=self.generate_flstudio_pack).pack(side="left", padx=(8, 0))
        pv = ttk.LabelFrame(inner, text="试听预览")
        pv.grid(row=3, column=0, sticky="ew", padx=4, pady=4)
        ttk.Label(pv, text="预览秒数（0=完整）").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Spinbox(pv, from_=0, to=600, increment=10, textvariable=self.var_preview_seconds, width=8).grid(
            row=0, column=1, sticky="w", padx=4, pady=3)
        ttk.Button(pv, text="生成试听预览", command=self.generate_preview).grid(row=0, column=2, padx=(8, 4), pady=3)
        ttk.Button(pv, text="播放 / 停止", command=self.toggle_preview_play).grid(row=0, column=3, padx=4, pady=3)
        ttk.Button(pv, text="打开预览文件", command=self.open_preview_file).grid(row=0, column=4, padx=4, pady=3)
        ttk.Label(pv, textvariable=self.var_preview_status, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=5, sticky="w", padx=4, pady=(0, 4))
        note = ttk.LabelFrame(inner, text="说明")
        note.grid(row=4, column=0, sticky="nsew", padx=4, pady=4)
        msg = (
            "默认资源包来自 skill 自带的 qzpno_mv.zip。\n"
            "勾选修正项后点生成自定义音效包，会写入 output 并自动切换。\n"
            "Voice 改钢琴在生成机器前改写 MIDI，不会改原文件。"
        )
        ttk.Label(note, text=msg, justify="left").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        _bind_wheel(inner)

    # ------------------------------------------------------------- online tab
    def _build_online_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="在线音色库")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        searchf = ttk.LabelFrame(tab, text="搜索在线 SoundFont（musical-artifacts.com）")
        searchf.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        searchf.columnconfigure(1, weight=1)
        ttk.Label(searchf, text="关键词").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(searchf, textvariable=self.var_online_query).grid(row=0, column=1, sticky="ew", padx=4, pady=3)
        ttk.Button(searchf, text="搜索", command=self.online_search).grid(row=0, column=2, padx=4, pady=3)
        ttk.Label(searchf, textvariable=self.var_online_status, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 4))

        paned = ttk.PanedWindow(tab, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        resultsf = ttk.LabelFrame(paned, text="在线结果")
        resultsf.columnconfigure(0, weight=1)
        resultsf.rowconfigure(0, weight=1)
        self.online_results_list = tk.Listbox(resultsf, height=12)
        self.online_results_list.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(resultsf, orient="vertical", command=self.online_results_list.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.online_results_list.configure(yscrollcommand=sb.set)
        rb = ttk.Frame(resultsf)
        rb.grid(row=1, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Button(rb, text="下载选中", command=self.online_download_selected).pack(side="left")
        ttk.Button(rb, text="打开页面", command=self.online_open_page).pack(side="left", padx=(6, 0))
        paned.add(resultsf, weight=1)

        presetf = ttk.LabelFrame(paned, text="音色库预设")
        presetf.columnconfigure(0, weight=1)
        presetf.rowconfigure(0, weight=1)
        self.online_preset_list = tk.Listbox(presetf, height=12)
        self.online_preset_list.grid(row=0, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(presetf, orient="vertical", command=self.online_preset_list.yview)
        sb2.grid(row=0, column=1, sticky="ns")
        self.online_preset_list.configure(yscrollcommand=sb2.set)
        ttk.Button(presetf, text="预览选中预设", command=self.online_preview_note).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=3)
        paned.add(presetf, weight=1)

        localf = ttk.LabelFrame(tab, text="本地 / 已下载 SoundFont")
        localf.grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        localf.columnconfigure(1, weight=1)
        ttk.Label(localf, text="文件").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.cmb_local_sf2 = ttk.Combobox(localf, textvariable=self.var_online_sf2, values=[], width=80)
        self.cmb_local_sf2.grid(row=0, column=1, sticky="ew", padx=4, pady=3)
        ttk.Button(localf, text="刷新列表", command=self.refresh_local_soundfonts).grid(row=0, column=2, padx=4, pady=3)
        ttk.Button(localf, text="浏览...", command=self.online_browse_sf2).grid(row=0, column=3, padx=4, pady=3)
        ttk.Button(localf, text="载入预设", command=self.online_load_presets).grid(row=0, column=4, padx=4, pady=3)

        mapf = ttk.LabelFrame(tab, text="乐器族映射（pno / lead / pad / bass / drum）")
        mapf.grid(row=3, column=0, sticky="ew", padx=4, pady=4)
        mapf.columnconfigure(1, weight=1)
        self._map_combos = {}
        map_items = [
            ("钢琴 pno", self.var_map_pno),
            ("主音 lead", self.var_map_lead),
            ("铺底 pad", self.var_map_pad),
            ("贝斯 bass", self.var_map_bass),
            ("鼓组 drum", self.var_map_drum),
        ]
        for i, (label, var) in enumerate(map_items):
            ttk.Label(mapf, text=label).grid(row=i, column=0, sticky="w", padx=4, pady=2)
            cb = ttk.Combobox(mapf, textvariable=var, state="readonly", width=70)
            cb.grid(row=i, column=1, sticky="ew", padx=4, pady=2)
            self._map_combos[label] = cb

        actf = ttk.Frame(tab)
        actf.grid(row=4, column=0, sticky="w", padx=4, pady=(2, 4))
        ttk.Button(actf, text="预览选中预设", command=self.online_preview_note).pack(side="left")
        ttk.Button(actf, text="预览音阶", command=self.online_preview_scale).pack(side="left", padx=(6, 0))
        ttk.Button(actf, text="停止预览", command=preview_audio.stop_audio).pack(side="left", padx=(6, 0))
        ttk.Button(actf, text="生成资源包", command=self.online_generate_pack).pack(side="left", padx=(6, 0))
        ttk.Button(actf, text="清空日志", command=lambda: self.clear_text(self.online_log)).pack(side="left", padx=(6, 0))

        logf = ttk.LabelFrame(tab, text="日志")
        logf.grid(row=5, column=0, sticky="nsew", padx=4, pady=4)
        logf.columnconfigure(0, weight=1)
        logf.rowconfigure(0, weight=1)
        self.online_log = scrolledtext.ScrolledText(logf, width=140, height=8, wrap="word")
        self.online_log.grid(row=0, column=0, sticky="nsew")
        tab.rowconfigure(5, weight=1)
        self.after(300, self.refresh_local_soundfonts)

    def _log_online(self, text):
        try:
            self.online_log.insert("end", str(text) + "\n")
            self.online_log.see("end")
        except Exception:
            pass

    def refresh_local_soundfonts(self):
        try:
            paths = online_soundpack.list_local_soundfonts()
        except Exception as exc:
            self._log_online("扫描本地 SoundFont 失败: " + str(exc))
            paths = []
        values = [str(x) for x in paths]
        self.cmb_local_sf2.configure(values=values)
        if values and not self.var_online_sf2.get():
            self.var_online_sf2.set(values[0])
            self.online_load_presets()
        self._log_online("本地 SoundFont: %d 个" % len(values))

    def online_browse_sf2(self):
        path = filedialog.askopenfilename(filetypes=[("SoundFont", "*.sf2 *.sf3"), ("所有文件", "*.*")])
        if path:
            self.var_online_sf2.set(path)
            self.online_load_presets()

    def online_load_presets(self):
        path = self.var_online_sf2.get().strip()
        if not path or not Path(path).is_file():
            messagebox.showerror("缺少 SoundFont", "请先选择一个 .sf2 / .sf3 文件。")
            return
        try:
            sfo = SoundFont(path)
            presets = sfo.list_presets()
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        self.online_preset_list.delete(0, "end")
        self._preset_display = {}
        for i, bank, prog, name in presets:
            disp = "{}: bank={} prog={} {}".format(i, bank, prog, name)
            self.online_preset_list.insert("end", disp)
            self._preset_display[disp] = i
        values = list(self._preset_display.keys())
        for _label, cb in self._map_combos.items():
            cb.configure(values=values)
        defaults = {
            "钢琴 pno": (0, 0),
            "主音 lead": (0, 29),
            "铺底 pad": (0, 48),
            "贝斯 bass": (0, 33),
            "鼓组 drum": (128, 0),
        }
        by_index = {i: disp for disp, i in self._preset_display.items()}
        for label, (bank, prog) in defaults.items():
            idx = sfo.find_preset(bank, prog)
            if idx is not None and idx in by_index:
                self._map_combos[label].set(by_index[idx])
        self._log_online("已载入 %d 个预设：%s" % (len(presets), path))
        if presets:
            self.online_preset_list.selection_set(0)

    def _selected_preset_index(self):
        sel = self.online_preset_list.curselection()
        if not sel:
            return None
        return self._preset_display.get(self.online_preset_list.get(sel[0]))

    def _map_to_bank_prog(self, label):
        disp = self._map_combos[label].get()
        if not disp:
            return None
        m = re.search(r"bank=(\d+)\s+prog=(\d+)", disp)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None

    def online_preview_note(self):
        path = self.var_online_sf2.get().strip()
        idx = self._selected_preset_index()
        if not path or idx is None:
            messagebox.showinfo("未选择", "请先载入 SoundFont 并选择一个预设。")
            return
        try:
            y = online_soundpack.preview(path, idx, note=60, velocity=100, duration=2.0)
            wav = OUTPUT_DIR / "_online_preview.wav"
            ensure_dir(OUTPUT_DIR)
            sf.write(str(wav), y.astype("float32"), SR)
            preview_audio.play_audio(str(wav))
            self._log_online("预览预设 %s" % idx)
        except Exception as exc:
            self._log_online("预览失败: " + str(exc))

    def online_preview_scale(self):
        path = self.var_online_sf2.get().strip()
        idx = self._selected_preset_index()
        if not path or idx is None:
            return
        try:
            sfo = SoundFont(path)
            notes = [60, 62, 64, 65, 67, 69, 71, 72]
            chunks = [sfo.render_note(idx, n, 100, 0.35) for n in notes]
            y = np.concatenate(chunks) if chunks else np.zeros(1, dtype="float32")
            wav = OUTPUT_DIR / "_online_scale.wav"
            ensure_dir(OUTPUT_DIR)
            sf.write(str(wav), y.astype("float32"), SR)
            preview_audio.play_audio(str(wav))
        except Exception as exc:
            self._log_online("音阶预览失败: " + str(exc))

    def _poll_online_queue(self):
        try:
            while True:
                kind, payload = self._online_queue.get_nowait()
                try:
                    if kind == "search":
                        self._online_search_done(*payload)
                    elif kind == "download":
                        self._download_done(*payload)
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.after(150, self._poll_online_queue)

    def online_search(self):
        q = self.var_online_query.get().strip()
        if not q:
            return
        self.var_online_status.set("搜索中...")
        self._log_online("搜索: " + q)
        threading.Thread(target=self._online_search_worker, args=(q,), daemon=True).start()

    def _online_search_worker(self, q):
        try:
            results = online_soundpack.search(q)
            err = None
        except Exception as exc:
            results, err = [], str(exc)
        self._online_queue.put(("search", (results, err)))

    def _online_search_done(self, results, err):
        self._online_results = results
        self.online_results_list.delete(0, "end")
        for r in results:
            name = r.get("name") or "(无标题)"
            src = r.get("source") or ""
            self.online_results_list.insert("end", "{}  [{}]".format(name, src))
        self.var_online_status.set("找到 %d 条结果" % len(results))
        if err:
            self._log_online("搜索出错: " + err)
        else:
            self._log_online("找到 %d 条结果" % len(results))

    def online_open_page(self):
        sel = self.online_results_list.curselection()
        if not sel:
            return
        r = self._online_results[sel[0]]
        url = r.get("page") or r.get("url")
        if url:
            webbrowser.open(url)

    def online_download_selected(self):
        sel = self.online_results_list.curselection()
        if not sel:
            return
        r = self._online_results[sel[0]]
        url = r.get("url")
        if not url:
            self._log_online("该结果没有直接下载地址，已打开页面。")
            self.online_open_page()
            return
        fn = r.get("filename") or Path(urllib.parse.urlparse(url).path).name or "download.sf2"
        dest = online_soundpack.SF2_DIR / fn
        self._log_online("下载: " + url)
        threading.Thread(target=self._download_worker, args=(url, dest), daemon=True).start()

    def _download_worker(self, url, dest):
        try:
            online_soundpack.download(url, dest)
            err = None
        except Exception as exc:
            err = str(exc)
        self._online_queue.put(("download", (dest, err)))

    def _download_done(self, dest, err):
        if err:
            self._log_online("下载失败: " + err)
        else:
            self._log_online("已下载: " + str(dest))
            self.var_online_sf2.set(str(dest))
            self.refresh_local_soundfonts()
            self.online_load_presets()

    def online_generate_pack(self):
        path = self.var_online_sf2.get().strip()
        if not path or not Path(path).is_file():
            messagebox.showerror("缺少 SoundFont", "请先选择一个 .sf2 / .sf3 文件。")
            return
        out = OUTPUT_DIR / "online_instrument_pack.zip"
        args = [PYTHON, "-m", "studio.online_soundpack", "--sf2", path, "--out", str(out)]
        for label, flag in [("钢琴 pno", "--pno"), ("主音 lead", "--lead"), ("铺底 pad", "--pad"),
                            ("贝斯 bass", "--bass"), ("鼓组 drum", "--drum")]:
            bp = self._map_to_bank_prog(label)
            if bp is None:
                messagebox.showerror("映射不完整", "请为所有乐器族选择预设：" + label)
                return
            args += [flag, "{}:{}".format(bp[0], bp[1])]
        self.nb.select(1)
        self.clear_text(self.build_text)
        self._target_text = self.build_text
        self.set_busy(True, "正在生成在线音色包...")
        self._pending_online_out = out
        self.append_log("[命令] " + " ".join(args) + "\n\n")
        try:
            self.runner.run(args, cwd=str(BASE_DIR))
        except Exception as exc:
            self._pending_online_out = None
            self.set_busy(False, "就绪")
            messagebox.showerror("无法启动", str(exc))


    def _build_deploy_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="部署")
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(4, weight=1)
        self._row(tab, "dist 目录", self.var_dist, 0, browse_dir=True)
        btns = ttk.Frame(tab)
        btns.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 4))
        ttk.Button(btns, text="检查安装回执", command=self.verify_dist).pack(side="left")
        ttk.Button(btns, text="打开 dist 文件夹", command=self.open_dist).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="打开世界 datapacks", command=self.open_world).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="一键安装到游戏", command=self.install_one_click).pack(side="left", padx=(8, 0))
        instr = (
            "真正安装到游戏需要你本人双击 dist 里的 DEPLOY_TO_GAME.bat。\n"
            "AI / 沙箱不能替你双击，否则可能装到镜像目录，游戏读不到。\n\n"
            "安装后进游戏：\n"
            "  /reload\n"
            "  /function <ns>:setup\n"
            "  /tick rate 80（手动输入）\n"
            "  /function <ns>:play\n\n"
            "回执文件：dist\\DEPLOY_RECEIPT.txt"
        )
        ttk.Label(tab, text=instr, justify="left").grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=6)
        self.deploy_text = scrolledtext.ScrolledText(tab, width=130, height=22, wrap="word")
        self.deploy_text.grid(row=4, column=0, columnspan=3, sticky="nsew", padx=4, pady=4)

    # --------------------------------------------------------------- logging
    def append_log(self, text):
        widget = self._target_text or self.build_text
        widget.insert("end", text)
        widget.see("end")

    def clear_text(self, widget):
        widget.delete("1.0", "end")

    def set_busy(self, busy, text=None):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (getattr(self, "btn_build", None), getattr(self, "btn_detect", None)):
            if btn is not None:
                btn.configure(state=state)
        if hasattr(self, "progress"):
            if busy:
                self.progress.grid()
                self.progress.start(12)
            else:
                self.progress.stop()
                self.progress.grid_remove()
        if text:
            self.var_status.set(text)
        self.update_idletasks()

    # ------------------------------------------------------------- commands
    def analyze_song(self):
        midi = self.var_midi.get().strip()
        if not midi or not Path(midi).is_file():
            messagebox.showerror("缺少 MIDI", "请先选择一个存在的 MIDI 文件。")
            return
        self.nb.select(0)
        self.clear_text(self.song_text)
        self._target_text = self.song_text
        self.var_status.set("正在分析歌曲...")
        try:
            self.runner.run([PYTHON, script_path("midi_report.py"), "--midi", midi], cwd=str(BASE_DIR))
        except Exception as exc:
            messagebox.showerror("无法启动", str(exc))
            self.var_status.set("就绪")

    def detect_defaults(self, silent=False):
        p = self.collect_project()
        ver = p["mc_version"]
        changed = []
        mod_jar = BINARIES_DIR / ("redpiano-1.0.0-mc" + ver + ".jar")
        if mod_jar.exists():
            self.var_mod_jar.set(str(mod_jar))
            changed.append("RedPiano jar")
        profile = p["profile_dir"]
        if not profile:
            candidates = [
                Path(r"C:\迅雷下载\.minecraft\versions\GD656极致优化整合包"),
                Path(os.environ.get("APPDATA", "")) / ".minecraft",
                Path(r"D:\MCLDownload\Game\.minecraft"),
                Path.home() / "AppData" / "Roaming" / ".minecraft",
            ]
            for c in candidates:
                if c and c.exists() and (c / "mods").exists():
                    profile = str(c)
                    self.var_profile_dir.set(profile)
                    changed.append("profile 目录")
                    break
        if profile:
            mods = Path(profile) / "mods"
            if mods.is_dir():
                patterns = [
                    "fabric-api-*+" + ver + ".jar",
                    "fabric-api-*" + ver + "*.jar",
                    "fabric-api-*.jar",
                ]
                found = []
                for pat in patterns:
                    found = sorted(mods.glob(pat))
                    if found:
                        break
                if found:
                    self.var_fabric_api.set(str(found[0]))
                    changed.append("Fabric API")
        world = p["world_dir"]
        if not world and profile:
            saves = Path(profile) / "saves"
            if saves.is_dir():
                worlds = [d for d in saves.iterdir() if d.is_dir() and (d / "level.dat").exists()]
                if worlds:
                    preferred = [w for w in worlds if "putao" in w.name.lower() or "葡萄" in w.name]
                    w = (preferred or worlds)[0]
                    self.var_world_dir.set(str(w / "datapacks"))
                    changed.append("世界 " + w.name)
        if changed and not silent:
            messagebox.showinfo("自动检测完成", "已自动填入：\n" + "\n".join(changed))
        elif not silent:
            messagebox.showinfo("自动检测完成", "没有发现新的可自动填入项。")
        self.var_status.set("自动检测完成")

    def build_machine(self):
        if self._busy:
            messagebox.showwarning("请稍等", "已有任务正在运行。")
            return
        p = self.collect_project()
        if p["form"] == "custom":
            if not messagebox.askyesno(
                "自定义路线风险",
                "自定义路线（尤其是圆形、螺旋、多转弯）在当前生成器里不稳定，\n"
                "可能导致游戏卡死、命令死循环或严重掉帧。\n\n"
                "推荐改用 多轨并行型 (multilane)。\n\n"
                "你确定还要继续生成 custom 路线吗？",
            ):
                return
        midi = p["midi"]
        if not midi or not Path(midi).is_file():
            messagebox.showerror("缺少 MIDI", "请先选择 MIDI 文件。")
            return
        world = p["world_dir"]
        if not world:
            messagebox.showerror("缺少世界目录", "请填写存档的 datapacks 目录。")
            return
        if Path(world).name.lower() != "datapacks":
            if not messagebox.askyesno("目录可能不对",
                "当前世界目录结尾不是 datapacks：\n" + world + "\n\n是否自动加上 datapacks？"):
                return
            self.var_world_dir.set(str(Path(world) / "datapacks"))
            world = self.var_world_dir.get()
        midi_for_build = Path(midi)
        if p["voice_to_piano"]:
            try:
                out_midi = OUTPUT_DIR / "studio_voice_to_piano.mid"
                ensure_dir(OUTPUT_DIR)
                count = remap_voice_to_piano(midi, str(out_midi))
                midi_for_build = out_midi
                self.append_log("[音效] Voice -> Piano：修改了 " + str(count) + " 个 program_change\n")
            except Exception as exc:
                messagebox.showerror("Voice 转钢琴失败", str(exc))
                return
        if p["sustain"]:
            try:
                out_midi = OUTPUT_DIR / "studio_sustain.mid"
                ensure_dir(OUTPUT_DIR)
                count = extend_note_durations(str(midi_for_build), str(out_midi), float(p["sustain_max_gap"]))
                midi_for_build = out_midi
                self.append_log("[延音] 延长了 " + str(count) + " 个 note_off，最大空档 " + str(p["sustain_max_gap"]) + " 秒\n")
            except Exception as exc:
                messagebox.showerror("延音处理失败", str(exc))
                return
        rp_for_build = ""
        if p["sound_mode"] == "custom":
            rp_for_build = p["custom_rp"]
            if not rp_for_build:
                try:
                    rp_for_build = self.generate_soundpack(silent=True)
                except Exception as exc:
                    messagebox.showerror("音效包生成失败", str(exc))
                    return
        try:
            ox = int(float(p["origin_x"]))
            oz = int(float(p["origin_z"]))
            oy = int(float(p["origin_y"]))
        except ValueError:
            messagebox.showerror("坐标错误", "原点坐标必须是数字。")
            return
        args = [
            PYTHON, script_path("prepare_all.py"),
            "--midi", str(midi_for_build),
            "--ns", p["ns"],
            "--origin", str(ox), str(oz), str(oy),
            "--mc-version", p["mc_version"],
            "--form", p["form"],
            "--world-dir", world,
            "--dist", p["dist"],
        ]
        if p["params"]:
            args += ["--params", p["params"]]
        if p["prebuilt_mod_jar"]:
            args += ["--prebuilt-mod-jar", p["prebuilt_mod_jar"]]
        if p["fabric_api_jar"]:
            args += ["--fabric-api-jar", p["fabric_api_jar"]]
        if rp_for_build:
            args += ["--prebuilt-rp", rp_for_build]
        if p["force_cap"]:
            args += ["--force-cap"]
        args += ["--melcap", str(float(p["melcap"]))]
        self.nb.select(1)
        self.clear_text(self.build_text)
        self._target_text = self.build_text
        self.set_busy(True, "正在生成安装包...")
        self.append_log("[命令] " + " ".join(args) + "\n\n")
        try:
            self.runner.run(args, cwd=str(BASE_DIR))
        except Exception as exc:
            self.set_busy(False, "就绪")
            messagebox.showerror("无法启动", str(exc))

    def apply_sound_preset(self):
        preset = self.var_sound_preset.get()
        if preset == "NeuralNote 乐器映射":
            self.var_guitar.set(True)
            self.var_pad_flute.set(True)
            self.var_voice_to_piano.set(True)
            self.var_crash_volume.set(35)
            for v in (self.var_pno_vol, self.var_lead_vol, self.var_pad_vol, self.var_bass_vol, self.var_drum_vol):
                v.set(100)
            messagebox.showinfo("NeuralNote 预设",
                "已应用 NeuralNote 乐器映射：\n"
                "钢琴 -> 钢琴\n吉他/主音 -> 原版吉他\n弦乐/人声 -> 长笛/钢琴\n贝斯 -> 贝斯\n鼓 -> 鼓组\n"
                "点生成自定义音效包即可生成。")
        elif preset == "MuseScore 乐器映射":
            self.var_guitar.set(False)
            self.var_pad_flute.set(False)
            self.var_voice_to_piano.set(False)
            self.var_crash_volume.set(100)
            for v in (self.var_pno_vol, self.var_lead_vol, self.var_pad_vol, self.var_bass_vol, self.var_drum_vol):
                v.set(100)
            messagebox.showinfo("MuseScore 预设",
                "已关闭原版吉他/长笛覆盖，使用 MuseScore MS Basic 采样包。\n"
                "如果还没生成，请点击 生成 MuseScore 音效包 按钮，生成后会自动切换为自定义音效包。")
        elif preset == "FL Studio 乐器映射":
            self.var_guitar.set(False)
            self.var_pad_flute.set(False)
            self.var_voice_to_piano.set(False)
            self.var_crash_volume.set(100)
            for v in (self.var_pno_vol, self.var_lead_vol, self.var_pad_vol, self.var_bass_vol, self.var_drum_vol):
                v.set(100)
            messagebox.showinfo("FL Studio 预设",
                "已关闭原版吉他/长笛覆盖，使用 FL Studio 默认乐器采样包。\n"
                "如果还没生成，请点击 生成 FL Studio 音效包 按钮，生成后会自动切换为自定义音效包。")
        elif preset == "在线音色库（自定义）":
            self.var_guitar.set(False)
            self.var_pad_flute.set(False)
            self.var_voice_to_piano.set(False)
            self.var_crash_volume.set(100)
            for v in (self.var_pno_vol, self.var_lead_vol, self.var_pad_vol, self.var_bass_vol, self.var_drum_vol):
                v.set(100)
            messagebox.showinfo("在线音色库", "使用当前自定义资源包。")
        elif preset == "吉他 + 长笛（推荐）":
            self.var_guitar.set(True)
            self.var_pad_flute.set(True)
            self.var_voice_to_piano.set(False)
            self.var_crash_volume.set(35)
            messagebox.showinfo("预设已应用", "吉他用原版吉他，弦乐/铺底用长笛。")
        else:
            self.var_guitar.set(False)
            self.var_pad_flute.set(False)
            self.var_voice_to_piano.set(False)
            self.var_crash_volume.set(100)
            messagebox.showinfo("预设已应用", "使用 skill 自带音效包。")

    def generate_neuralnote_pack(self):
        src = ASSETS_DIR / "qzpno_mv.zip"
        out = OUTPUT_DIR / "neuralnote_instrument_pack.zip"
        ensure_dir(OUTPUT_DIR)
        make_custom_pack(
            str(src), str(out),
            guitar=True, pad_flute=True, crash_volume=0.35,
            volumes={"pno": 1.0, "lead": 1.0, "pad": 1.0, "bass": 1.0, "drum": 1.0, "crash": 0.35},
        )
        self.var_custom_rp.set(str(out))
        self.var_sound_mode.set("custom")
        self.var_sound_preset.set("NeuralNote 乐器映射")
        self._sync_sound_widgets()
        messagebox.showinfo("NeuralNote 音效包已生成", "已生成：\n" + str(out))

    def generate_musescore_pack(self):
        out = OUTPUT_DIR / "musescore_instrument_pack.zip"
        ensure_dir(OUTPUT_DIR)
        self.nb.select(1)
        self.clear_text(self.build_text)
        self._target_text = self.build_text
        self.set_busy(True, "正在生成 MuseScore 音效包...")
        self._pending_musescore_out = out
        args = [PYTHON, "-m", "studio.musescore_pack", "--out", str(out)]
        self.append_log("[命令] " + " ".join(args) + "\n\n")
        try:
            self.runner.run(args, cwd=str(BASE_DIR))
        except Exception as exc:
            self._pending_musescore_out = None
            self.set_busy(False, "就绪")
            messagebox.showerror("无法启动", str(exc))

    def generate_flstudio_pack(self):
        out = OUTPUT_DIR / "flstudio_instrument_pack.zip"
        ensure_dir(OUTPUT_DIR)
        self.nb.select(1)
        self.clear_text(self.build_text)
        self._target_text = self.build_text
        self.set_busy(True, "正在生成 FL Studio 音效包...")
        self._pending_flstudio_out = out
        args = [PYTHON, "-m", "studio.flstudio_pack", "--out", str(out)]
        self.append_log("[命令] " + " ".join(args) + "\n\n")
        try:
            self.runner.run(args, cwd=str(BASE_DIR))
        except Exception as exc:
            self._pending_flstudio_out = None
            self.set_busy(False, "就绪")
            messagebox.showerror("无法启动", str(exc))

    def generate_soundpack(self, silent=False):
        src = ASSETS_DIR / "qzpno_mv.zip"
        if not src.is_file():
            raise FileNotFoundError("找不到自带资源包：" + str(src))
        out = OUTPUT_DIR / "studio_qzpno.zip"
        ensure_dir(OUTPUT_DIR)
        make_custom_pack(
            str(src), str(out),
            guitar=bool(self.var_guitar.get()),
            pad_flute=bool(self.var_pad_flute.get()),
            crash_volume=max(0.0, min(2.0, self.var_crash_volume.get() / 100.0)),
            volumes={
                "pno": self.var_pno_vol.get() / 100.0,
                "lead": self.var_lead_vol.get() / 100.0,
                "pad": self.var_pad_vol.get() / 100.0,
                "bass": self.var_bass_vol.get() / 100.0,
                "drum": self.var_drum_vol.get() / 100.0,
                "crash": self.var_crash_volume.get() / 100.0,
            },
        )
        self.var_custom_rp.set(str(out))
        self.var_sound_mode.set("custom")
        self._sync_sound_widgets()
        if not silent:
            messagebox.showinfo("音效包已生成", "已生成：\n" + str(out))
        return str(out)

    def generate_preview(self):
        midi = self.var_midi.get().strip()
        if not midi or not Path(midi).is_file():
            messagebox.showerror("缺少 MIDI", "请先选择一个存在的 MIDI 文件。")
            return
        if getattr(self, "_preview_thread", None) is not None and self._preview_thread.is_alive():
            messagebox.showinfo("正在生成", "试听预览正在生成，请稍候。")
            return
        ensure_dir(OUTPUT_DIR)
        out = OUTPUT_DIR / ("试听预览_" + Path(midi).stem + ".wav")
        p = self.collect_project()
        opts = {
            "max_seconds": int(self.var_preview_seconds.get() or 0) or None,
            "guitar": bool(p.get("guitar", True)),
            "pad_flute": bool(p.get("pad_flute", True)),
            "voice_to_piano": bool(p.get("voice_to_piano", False)),
            "volumes": {
                "pno": p.get("pno_vol", 100),
                "lead": p.get("lead_vol", 100),
                "pad": p.get("pad_vol", 100),
                "bass": p.get("bass_vol", 100),
                "drum": p.get("drum_vol", 100),
            },
            "crash_volume": max(0.0, min(2.0, float(p.get("crash_volume", 35)) / 100.0)),
        }
        if self.var_sound_mode.get() == "custom":
            custom = self.var_custom_rp.get().strip()
            if custom and Path(custom).is_file():
                opts["sample_zip"] = custom
        self._preview_wav = out
        self.var_preview_status.set("正在生成试听预览...")
        self.set_busy(True, "正在生成试听预览...")
        while not self._preview_queue.empty():
            try:
                self._preview_queue.get_nowait()
            except queue.Empty:
                break
        self._preview_thread = threading.Thread(
            target=self._preview_worker, args=(midi, str(out), opts), daemon=True)
        self._preview_thread.start()
        self._poll_preview()

    def _preview_worker(self, midi, out, opts):
        try:
            preview_audio.render_midi_to_wav(midi, out, **opts)
            self._preview_queue.put((out, None))
        except Exception as exc:
            self._preview_queue.put((out, exc))

    def _poll_preview(self):
        try:
            out, exc = self._preview_queue.get_nowait()
        except queue.Empty:
            self.after(120, self._poll_preview)
            return
        self._preview_done(out, exc)

    def _preview_done(self, out, exc):
        self.set_busy(False)
        if exc is not None:
            self.var_preview_status.set("试听预览生成失败")
            messagebox.showerror("试听预览失败", str(exc))
            return
        self._preview_wav = Path(out)
        self.var_preview_status.set("预览已生成：" + str(self._preview_wav))
        self.append_log("[试听预览] " + str(self._preview_wav) + "\n")
        self.play_preview()

    def play_preview(self):
        if not getattr(self, "_preview_wav", None) or not Path(self._preview_wav).is_file():
            messagebox.showinfo("没有预览", "请先生成试听预览。")
            return
        preview_audio.stop_audio()
        if preview_audio.play_audio(self._preview_wav):
            self._preview_playing = True
            self.var_preview_status.set("正在播放：" + str(self._preview_wav))
        else:
            self._preview_playing = False
            self.var_preview_status.set("无法播放，请打开预览文件。")

    def stop_preview(self):
        preview_audio.stop_audio()
        self._preview_playing = False
        self.var_preview_status.set("已停止播放")

    def toggle_preview_play(self):
        if getattr(self, "_preview_playing", False):
            self.stop_preview()
        else:
            self.play_preview()

    def open_preview_file(self):
        if getattr(self, "_preview_wav", None) and Path(self._preview_wav).is_file():
            self.open_path(self._preview_wav)
        else:
            messagebox.showinfo("没有预览", "请先生成试听预览。")

    def verify_dist(self):
        p = self.collect_project()
        dist = p["dist"]
        if not Path(dist).exists():
            messagebox.showerror("目录不存在", "找不到 dist 目录：\n" + dist)
            return
        self.nb.select(3)
        self.clear_text(self.deploy_text)
        self._target_text = self.deploy_text
        self.var_status.set("正在检查安装回执...")
        try:
            self.runner.run([PYTHON, script_path("deploy_bundle.py"), "--verify", dist], cwd=str(BASE_DIR))
        except Exception as exc:
            messagebox.showerror("无法启动", str(exc))

    def on_process_done(self, rc):
        self.set_busy(False, "完成" if rc == 0 else "失败（退出码 " + str(rc) + "）")
        self._target_text = None
        if rc == 0:
            self.var_status.set("完成")
        else:
            self.var_status.set("任务失败，请查看日志")
        pending_ms = getattr(self, "_pending_musescore_out", None)
        if pending_ms is not None:
            self._pending_musescore_out = None
            if rc == 0 and Path(pending_ms).is_file():
                self.var_custom_rp.set(str(pending_ms))
                self.var_sound_mode.set("custom")
                self._sync_sound_widgets()
                self.var_sound_preset.set("MuseScore 乐器映射")
                messagebox.showinfo("MuseScore 音效包已生成",
                    "已生成：\n" + str(pending_ms) + "\n\n已自动切换为自定义音效包。")
        pending_fl = getattr(self, "_pending_flstudio_out", None)
        if pending_fl is not None:
            self._pending_flstudio_out = None
            if rc == 0 and Path(pending_fl).is_file():
                self.var_custom_rp.set(str(pending_fl))
                self.var_sound_mode.set("custom")
                self._sync_sound_widgets()
                self.var_sound_preset.set("FL Studio 乐器映射")
                messagebox.showinfo("FL Studio 音效包已生成",
                    "已生成：\n" + str(pending_fl) + "\n\n已自动切换为自定义音效包。")
        pending_on = getattr(self, "_pending_online_out", None)
        if pending_on is not None:
            self._pending_online_out = None
            if rc == 0 and Path(pending_on).is_file():
                self.var_custom_rp.set(str(pending_on))
                self.var_sound_mode.set("custom")
                self.var_sound_preset.set("在线音色库（自定义）")
                self._sync_sound_widgets()
                messagebox.showinfo("在线音色包已生成",
                    "已生成：\n" + str(pending_on) + "\n\n已自动切换为自定义音效包。")
        if getattr(self, "_pending_verify", False):
            self._pending_verify = False
            self.after(800, self.verify_dist)

    # ------------------------------------------------------------- utilities
    def _sync_sound_widgets(self):
        custom = self.var_sound_mode.get() == "custom"
        state = "normal" if custom else "disabled"
        if hasattr(self, "ent_custom_rp"):
            self.ent_custom_rp.configure(state=state)
            self.btn_custom_rp.configure(state=state)

    def browse_file(self, var, filetypes=None):
        path = filedialog.askopenfilename(filetypes=filetypes or [("所有文件", "*.*")])
        if path:
            var.set(path)

    def browse_dir(self, var):
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    def open_path(self, path):
        path = str(path)
        if not os.path.exists(path):
            messagebox.showerror("不存在", path)
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            else:
                webbrowser.open("file://" + path)
        except Exception as exc:
            messagebox.showerror("无法打开", str(exc))

    def generate_tube_params(self):
        import math, random
        r = simpledialog.askinteger("圆环音轨", "圆环半径（格）", initialvalue=50, minvalue=10, maxvalue=200)
        if not r:
            return
        n = simpledialog.askinteger("圆环音轨", "轨道数量", initialvalue=24, minvalue=4, maxvalue=128)
        if not n:
            return
        rng = random.Random(20261011)
        lanes = []
        for i in range(n):
            th = 2.0 * math.pi * i / n
            lanes.append({
                "x": rng.randint(0, 12),
                "y": int(round(r * math.cos(th))),
                "z": int(round(r * math.sin(th))),
            })
        params = {
            "form": "multilane",
            "chord_mode": "multilane",
            "max_poly": n,
            "lane_offsets": lanes,
            "base_block": "minecraft:quartz_block",
            "pace": "compressed",
        }
        out = OUTPUT_DIR / "tube_params.json"
        ensure_dir(OUTPUT_DIR)
        out.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        self.var_params.set(str(out))
        self.var_form.set(FORM_VALUE_TO_LABEL.get("multilane", "multilane"))
        self.var_origin_y.set("225")
        self.var_status.set("已生成圆环音轨参数：" + str(out))
        messagebox.showinfo("圆环音轨参数已生成",
            "已生成：" + str(out) + "\n\n"
            "布局：24 条直轨围绕中心通道形成圆环。\n"
            "记得把原点 Y 设为 225 左右，并用 multilane 生成。")

    def open_preview3d(self):
        p = self.collect_project()
        if p["form"] != "multilane":
            messagebox.showinfo("提示", "当前轨道布局编辑器主要面向 multilane（多轨）形态。\n仍然可以打开预览和编辑。")
        params = p["params"] or None
        win = TrackPreviewWindow(self, params_path=params, on_save=self._on_preview_saved)
        win.grab_set()

    def _on_preview_saved(self, path):
        self.var_params.set(path)
        self.var_status.set("轨道布局已保存并设为 params.json")

    def install_one_click(self):
        p = self.collect_project()
        dist = Path(p["dist"])
        if not dist.is_absolute():
            dist = BASE_DIR / dist
        bat = dist / "DEPLOY_TO_GAME.bat"
        if not bat.exists():
            messagebox.showerror("找不到安装器", "请先生成安装包。\n" + str(bat))
            return
        if not messagebox.askyesno(
            "一键安装确认",
            "这会直接运行 DEPLOY_TO_GAME.bat 安装到游戏。\n\n"
            "请确认：\n"
            "1. Minecraft 已经完全退出\n"
            "2. 你是本机原生运行本软件（不是沙箱环境）\n\n"
            "继续吗？",
        ):
            return
        self.nb.select(3)
        self.clear_text(self.deploy_text)
        self._target_text = self.deploy_text
        self._pending_verify = True
        self.set_busy(True, "正在安装到游戏...")
        self.append_log("[一键安装] " + str(bat) + "\n\n")
        try:
            self.runner.run(["cmd", "/c", str(bat)], cwd=str(dist))
        except Exception as exc:
            self._pending_verify = False
            self.set_busy(False, "就绪")
            messagebox.showerror("无法启动", str(exc))

    def open_output_dir(self):
        p = self.collect_project()
        path = Path(p["dist"])
        if not path.is_absolute():
            path = BASE_DIR / path
        ensure_dir(path)
        self.open_path(path)

    def open_dist(self):
        self.open_output_dir()

    def open_world(self):
        p = self.collect_project()
        if p["world_dir"]:
            self.open_path(Path(p["world_dir"]))
        else:
            messagebox.showinfo("提示", "请先填写世界 datapacks 目录。")

    def open_layout_designer(self):
        # 原来的 skill HTML 布局设计器，按用户要求恢复为默认入口。
        self.open_path(SKILL_DIR / "designer" / "layout_designer.html")

    def import_designer_json(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            params = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return
        self.var_params.set(path)
        form = params.get("form", "custom")
        if form:
            self.var_form.set(FORM_VALUE_TO_LABEL.get(form, form))
        if params.get("base_block"):
            pass
        self.var_status.set("已导入设计器 JSON：" + Path(path).name)

    def open_particle_editor(self):
        self.open_path(SKILL_DIR / "designer" / "particle_editor.html")

    def show_about(self):
        messagebox.showinfo("关于",
            "红石音乐工作室 0.1.0\n\n基于 minecraft-redstone-music skill 的 GUI 封装。\n"
            "底层仍然调用原有 Python 脚本生成 datapack、资源包和 mod 安装包。")

    # --------------------------------------------------------------- project
    def new_project(self):
        self.project = self.default_project()
        self.apply_project(self.project)
        self.var_status.set("已新建项目")

    def load_project_dialog(self):
        path = filedialog.askopenfilename(
            filetypes=[("红石音乐项目", "*.rms.json"), ("JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.project = json.load(f)
            self.apply_project(self.project)
            self.var_status.set("已打开项目：" + Path(path).name)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def save_project(self):
        self.project = self.collect_project()
        path = getattr(self, "_project_path", "")
        if not path:
            return self.save_project_as()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.project, f, ensure_ascii=False, indent=2)
            self.var_status.set("已保存：" + Path(path).name)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def save_project_as(self):
        self.project = self.collect_project()
        path = filedialog.asksaveasfilename(
            defaultextension=".rms.json",
            filetypes=[("红石音乐项目", "*.rms.json"), ("JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        self._project_path = path
        self.save_project()


def main():
    app = StudioApp()
    app.mainloop()
