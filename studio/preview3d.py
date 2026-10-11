"""Simple isometric 3D-ish track layout preview / editor for multilane machines."""
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


DEFAULT_PARAMS = {
    "form": "multilane",
    "chord_mode": "multilane",
    "max_poly": 8,
    "lane_offsets": [],
    "base_block": "minecraft:quartz_block",
    "pace": "compressed",
}


class TrackPreviewWindow(tk.Toplevel):
    def __init__(self, master, params_path=None, on_save=None):
        super().__init__(master)
        self.title("3D 轨道布局预览 - 可拖动调整 X / Y / Z")
        self.geometry("1120x720")
        self.minsize(900, 620)
        self.on_save = on_save
        self.params = dict(DEFAULT_PARAMS)
        self.lane_offsets = []
        self.selected = -1
        self._drag_start = None
        self._drag_mode = None
        self.scale_x = 22.0
        self.scale_y = 18.0
        self.scale_zx = 10.0
        self.scale_zy = 7.0
        self.origin_x = 320
        self.origin_y = 420
        self._build_ui()
        self._load_params(params_path)
        self._refresh_lane_list()
        self._redraw()
        self.bind("<Configure>", lambda e: self._redraw())

    # ------------------------------------------------------------------ ui
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        main = ttk.Frame(self)
        main.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(main, background="#101820", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        side = ttk.Frame(main, width=330)
        side.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        side.columnconfigure(0, weight=1)
        side.rowconfigure(1, weight=1)

        ttk.Label(side, text="轨道列表（点选后可拖动预览）").grid(row=0, column=0, sticky="w")
        self.lane_list = tk.Listbox(side, height=18, exportselection=False)
        self.lane_list.grid(row=1, column=0, sticky="nsew", pady=(4, 6))
        self.lane_list.bind("<<ListboxSelect>>", self._on_select_lane)

        ctl = ttk.LabelFrame(side, text="选中轨道")
        ctl.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        ctl.columnconfigure(1, weight=1)
        self.var_x = tk.IntVar(value=0)
        self.var_y = tk.IntVar(value=0)
        self.var_z = tk.IntVar(value=0)
        for i, (label, var) in enumerate((("X 偏移", self.var_x), ("Y 高度", self.var_y), ("Z 偏移", self.var_z))):
            ttk.Label(ctl, text=label).grid(row=i, column=0, sticky="w", padx=(4, 6), pady=2)
            sp = ttk.Spinbox(ctl, from_=-999, to=999, textvariable=var, width=8, command=self._apply_spin)
            sp.grid(row=i, column=1, sticky="w", pady=2)
            sp.bind("<KeyRelease>", lambda e: self._apply_spin())
        ttk.Button(ctl, text="添加轨道", command=self._add_lane).grid(row=3, column=0, sticky="w", padx=4, pady=4)
        ttk.Button(ctl, text="删除轨道", command=self._delete_lane).grid(row=3, column=1, sticky="w", padx=4, pady=4)

        opt = ttk.LabelFrame(side, text="机器参数")
        opt.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        opt.columnconfigure(1, weight=1)
        ttk.Label(opt, text="底板方块").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.var_base = tk.StringVar(value="minecraft:quartz_block")
        ttk.Entry(opt, textvariable=self.var_base, width=28).grid(row=0, column=1, sticky="ew", padx=4, pady=3)

        btn = ttk.Frame(side)
        btn.grid(row=4, column=0, sticky="ew")
        ttk.Button(btn, text="保存为 params.json", command=self._save).pack(side="left")
        ttk.Button(btn, text="关闭", command=self.destroy).pack(side="right")

        hint = ttk.Label(
            side,
            text="拖动：直接改 Z / Y\nShift + 拖动：改 X",
            justify="left",
            foreground="#666666",
        )
        hint.grid(row=5, column=0, sticky="w", pady=(6, 0))

    # ------------------------------------------------------------------ io
    def _load_params(self, path):
        if path and Path(path).is_file():
            try:
                self.params = json.loads(Path(path).read_text(encoding="utf-8"))
            except Exception as exc:
                messagebox.showwarning("读取失败", "无法读取 params JSON：\n" + str(exc))
                self.params = dict(DEFAULT_PARAMS)
        self.lane_offsets = [dict(x) for x in self.params.get("lane_offsets", [])]
        self.var_base.set(self.params.get("base_block", "minecraft:quartz_block"))
        if not self.lane_offsets:
            # A friendly default: two walls around a central corridor.
            for i in range(8):
                self.lane_offsets.append({"z": -2 - i * 2, "y": i * 4, "x": i % 3})
            for i in range(8):
                self.lane_offsets.append({"z": 2 + i * 2, "y": 2 + i * 4, "x": (i + 1) % 4})
        self._select_lane(0)

    def _save(self):
        self._sync_params()
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("所有文件", "*.*")],
            initialfile="lane_layout.json",
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(self.params, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        if self.on_save:
            self.on_save(path)
        messagebox.showinfo("已保存", "轨道布局已保存到：\n" + path)

    def _sync_params(self):
        self.params["form"] = "multilane"
        self.params["chord_mode"] = "multilane"
        self.params["max_poly"] = len(self.lane_offsets)
        self.params["lane_offsets"] = [dict(x) for x in self.lane_offsets]
        self.params["base_block"] = self.var_base.get().strip() or "minecraft:quartz_block"
        self.params.setdefault("pace", "compressed")

    # -------------------------------------------------------------- controls
    def _refresh_lane_list(self):
        self.lane_list.delete(0, "end")
        for i, lane in enumerate(self.lane_offsets):
            self.lane_list.insert(
                "end",
                "轨 {0:02d}  X={1:>4}  Y={2:>4}  Z={3:>4}".format(
                    i, lane.get("x", 0), lane.get("y", 0), lane.get("z", 0)
                ),
            )
        if 0 <= self.selected < len(self.lane_offsets):
            self.lane_list.selection_set(self.selected)
        self._redraw()

    def _on_select_lane(self, _event=None):
        sel = self.lane_list.curselection()
        if sel:
            self._select_lane(sel[0])

    def _select_lane(self, idx):
        if not self.lane_offsets:
            return
        self.selected = max(0, min(idx, len(self.lane_offsets) - 1))
        lane = self.lane_offsets[self.selected]
        self.var_x.set(int(lane.get("x", 0)))
        self.var_y.set(int(lane.get("y", 0)))
        self.var_z.set(int(lane.get("z", 0)))
        self.lane_list.selection_clear(0, "end")
        self.lane_list.selection_set(self.selected)
        self._redraw()

    def _apply_spin(self):
        if not (0 <= self.selected < len(self.lane_offsets)):
            return
        lane = self.lane_offsets[self.selected]
        try:
            lane["x"] = int(self.var_x.get())
            lane["y"] = int(self.var_y.get())
            lane["z"] = int(self.var_z.get())
        except Exception:
            return
        self._refresh_lane_list()

    def _add_lane(self):
        lane = dict(self.lane_offsets[self.selected]) if self.lane_offsets else {"x": 0, "y": 0, "z": 0}
        lane["z"] = int(lane.get("z", 0)) + 2
        self.lane_offsets.append(lane)
        self.selected = len(self.lane_offsets) - 1
        self._refresh_lane_list()

    def _delete_lane(self):
        if len(self.lane_offsets) <= 1 or not (0 <= self.selected < len(self.lane_offsets)):
            return
        self.lane_offsets.pop(self.selected)
        self.selected = min(self.selected, len(self.lane_offsets) - 1)
        self._refresh_lane_list()

    # ---------------------------------------------------------------- drag
    def _project(self, x, y, z):
        sx = self.origin_x + x * self.scale_x + z * self.scale_zx
        sy = self.origin_y - y * self.scale_y + z * self.scale_zy
        return sx, sy

    def _find_lane_at(self, sx, sy):
        best = -1
        best_d = 1e9
        for i, lane in enumerate(self.lane_offsets):
            px, py = self._project(0, lane.get("y", 0), lane.get("z", 0))
            d = (px - sx) ** 2 + (py - sy) ** 2
            if d < best_d:
                best_d = d
                best = i
        return best if best_d < 50 ** 2 else -1

    def _on_press(self, event):
        idx = self._find_lane_at(event.x, event.y)
        if idx >= 0:
            self._select_lane(idx)
            self._drag_start = (event.x, event.y)
            self._drag_mode = "x" if (event.state & 0x0001) else "zy"
        else:
            self._drag_start = None
            self._drag_mode = None

    def _on_drag(self, event):
        if self._drag_start is None or not (0 <= self.selected < len(self.lane_offsets)):
            return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        lane = self.lane_offsets[self.selected]
        if self._drag_mode == "x":
            lane["x"] = int(lane.get("x", 0) + dx / self.scale_x)
        else:
            lane["z"] = int(lane.get("z", 0) + dx / self.scale_zx)
            lane["y"] = int(lane.get("y", 0) - dy / self.scale_y)
        self._drag_start = (event.x, event.y)
        self.var_x.set(int(lane.get("x", 0)))
        self.var_y.set(int(lane.get("y", 0)))
        self.var_z.set(int(lane.get("z", 0)))
        self._refresh_lane_list()

    def _on_release(self, _event):
        self._drag_start = None
        self._drag_mode = None

    # --------------------------------------------------------------- render
    def _redraw(self):
        if not hasattr(self, "canvas"):
            return
        c = self.canvas
        c.delete("all")
        w = max(c.winfo_width(), 600)
        h = max(c.winfo_height(), 400)
        self.origin_x = w * 0.28
        self.origin_y = h * 0.72
        # axes
        ox, oy = self._project(0, 0, 0)
        for label, (x, y, z), color in (
            ("X", (14, 0, 0), "#ff6b6b"),
            ("Y", (0, 12, 0), "#6bff95"),
            ("Z", (0, 0, 14), "#6bb8ff"),
        ):
            px, py = self._project(x, y, z)
            c.create_line(ox, oy, px, py, fill=color, width=2)
            c.create_text(px, py, text=label, fill=color)
        # lanes
        for i, lane in enumerate(self.lane_offsets):
            selected = i == self.selected
            color = "#ffd166" if selected else "#7bdff2"
            y0 = lane.get("y", 0)
            z0 = lane.get("z", 0)
            x0 = lane.get("x", 0)
            pts = []
            for k in range(16):
                pts.append(self._project(x0 + k, y0, z0))
            c.create_line(*[v for p in pts for v in p], fill=color, width=3 if selected else 1)
            for k, (px, py) in enumerate(pts):
                s = 4 if selected else 3
                c.create_rectangle(px - s, py - s, px + s, py + s, fill=color, outline="")
            lx, ly = pts[0]
            c.create_text(lx, ly - 12, text=str(i), fill=color)
        c.create_text(
            12, 12, anchor="nw", fill="#aaaaaa",
            text="拖动轨道：改 Z / Y    Shift+拖动：改 X\n选中的轨道为黄色",
        )
