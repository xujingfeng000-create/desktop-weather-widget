# -*- coding: utf-8 -*-
"""桌面小组件：时间 · 天气 · 日出日落（常驻屏幕右上角）

使用说明：
- 左键按住可拖动，位置自动记忆（写入 config.json）
- 右键打开菜单：刷新天气 / 隐藏小组件 / 开机自启动 / 退出小组件
- 「开机自启动」为勾选项：打勾=登录自动启动，取消打勾=不再自动启动
- 右下角「🙈 隐藏」按钮手动隐藏；隐藏后屏幕右上角出现「👁 显示」小按钮，点击恢复
- 检测到全屏程序（游戏 / 全屏视频）时自动隐藏，退出全屏后自动恢复
- 天气与日出日落数据来自 Open-Meteo 免费开放接口
- 调试：python widget.py <快照路径.png> 启动 8 秒后自拍窗口截图
- 控制通道：向 127.0.0.1:39217 发送 hide / show / quit / autostart 可控制小组件
"""
import ctypes
from ctypes import wintypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

import tkinter as tk
from tkinter import font as tkfont

USER32 = ctypes.windll.user32

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "city": "湛江",
    "lat": 21.2339,
    "lon": 110.3875,
    "alpha": 0.93,
    "margin_x": 16,
    "margin_y": 16,
    "refresh_minutes": 10,
    "topmost": True,
    "position": None,
}

# WMO 天气代码 -> (图标, 中文描述)
WMO = {
    0: ("☀️", "晴"), 1: ("🌤️", "基本晴朗"), 2: ("⛅", "多云"), 3: ("☁️", "阴"),
    45: ("🌫️", "雾"), 48: ("🌫️", "雾凇"),
    51: ("🌦️", "小毛毛雨"), 53: ("🌦️", "毛毛雨"), 55: ("🌦️", "大毛毛雨"),
    56: ("🌧️", "冻毛毛雨"), 57: ("🌧️", "强冻毛毛雨"),
    61: ("🌧️", "小雨"), 63: ("🌧️", "中雨"), 65: ("🌧️", "大雨"),
    66: ("🌧️", "冻雨"), 67: ("🌧️", "强冻雨"),
    71: ("🌨️", "小雪"), 73: ("🌨️", "中雪"), 75: ("❄️", "大雪"), 77: ("❄️", "雪粒"),
    80: ("🌦️", "小阵雨"), 81: ("🌧️", "阵雨"), 82: ("⛈️", "强阵雨"),
    85: ("🌨️", "小阵雪"), 86: ("🌨️", "大阵雪"),
    95: ("⛈️", "雷阵雨"), 96: ("⛈️", "雷暴伴冰雹"), 99: ("⛈️", "强雷暴伴冰雹"),
}

CARD = "#171a26"
CARD_EDGE = "#2b3048"
TEXT = "#e8eaf6"
SUB = "#8b93b8"
ACCENT = "#f5a97f"
HINT = "#565d78"
KEY = "#ff00ff"  # 透明色


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    else:
        save_config(cfg)  # 首次运行：自动生成默认配置文件
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def http_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (desktop-widget)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_weather(cfg):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
        "&daily=sunrise,sunset&timezone=auto&forecast_days=2"
    ).format(lat=cfg["lat"], lon=cfg["lon"])
    d = http_json(url)
    cur, day = d["current"], d["daily"]
    return {
        "temp": cur["temperature_2m"],
        "apparent": cur["apparent_temperature"],
        "humidity": cur["relative_humidity_2m"],
        "wind": cur["wind_speed_10m"],
        "code": cur["weather_code"],
        "sunrise0": day["sunrise"][0],
        "sunset0": day["sunset"][0],
        "sunrise1": day["sunrise"][1],
        "sunset1": day["sunset"][1],
        "ts": time.time(),
    }


def parse_hhmm(s):
    return datetime.strptime(s[:16], "%Y-%m-%dT%H:%M")


class Widget:
    def __init__(self, control_sock=None):
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        if self.cfg.get("topmost", True):
            self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", float(self.cfg.get("alpha", 0.93)))
        except Exception:
            pass
        try:
            self.root.attributes("-transparentcolor", KEY)
        except Exception:
            pass

        self._make_fonts()
        self.L = self._compute_layout()
        self.W, self.H = self.L["W"], self.L["H"]

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                bg=KEY, highlightthickness=0)
        self.canvas.pack()
        self._build_ui()
        self._place()
        self._bind()
        self.root.deiconify()

        self._weather = None
        self._applied = None
        self._last_ts = ""
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._auto_hidden = False
        self._manual_hidden = False
        self._pill = None
        self._last_fs_check = 0.0
        self._autostart_on = False
        self._autostart_var = tk.BooleanVar(master=self.root, value=False)
        if control_sock is not None:
            threading.Thread(target=self._control_thread, args=(control_sock,), daemon=True).start()
        threading.Thread(target=self._weather_loop, daemon=True).start()
        threading.Thread(target=self._query_autostart, daemon=True).start()
        self.root.after(200, self._tick)

        # 调试用：python widget.py <快照路径> 时，8 秒后自拍窗口保存 PNG
        if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".png"):
            self._snap_path = os.path.abspath(sys.argv[1])
            self.root.after(8000, self._snapshot)

    # ---------- 字体与布局（按实际渲染尺寸测量，适配任意缩放） ----------
    def _make_fonts(self):
        r = self.root
        self.f = {
            "city": tkfont.Font(root=r, family="Microsoft YaHei UI", size=12, weight="bold"),
            "temp": tkfont.Font(root=r, family="Segoe UI", size=28, weight="bold"),
            "cond": tkfont.Font(root=r, family="Microsoft YaHei UI", size=11),
            "meta": tkfont.Font(root=r, family="Microsoft YaHei UI", size=10),
            "clock": tkfont.Font(root=r, family="Segoe UI", size=30, weight="bold"),
            "date": tkfont.Font(root=r, family="Microsoft YaHei UI", size=10),
            "sun": tkfont.Font(root=r, family="Microsoft YaHei UI", size=11),
            "status": tkfont.Font(root=r, family="Microsoft YaHei UI", size=10, weight="bold"),
            "hint": tkfont.Font(root=r, family="Microsoft YaHei UI", size=8),
        }

    def _compute_layout(self):
        f = self.f
        ls = lambda k: f[k].metrics("linespace")

        # 宽度：取各内容行所需的最大值
        w_clock = f["clock"].measure("00:00:00")
        w_meta = f["meta"].measure("体感 25° · 湿度 100% · 风 12.3m/s")
        w_sun = f["sun"].measure("🌅 日出 00:00") + f["sun"].measure("🌇 日落 00:00")
        w_top = f["city"].measure(self.cfg["city"] + "市市") + f["temp"].measure("88.8°")
        W = int(max(w_clock + 64, w_meta + 48, w_sun + 72, w_top + 72, 300))
        W = min(W, 430)

        # 高度：逐行累加，每行用该字体真实行高
        y = 14.0
        y += max(ls("city"), ls("temp")) + 8          # 城市 + 温度
        y += ls("cond") + 12                          # 天气状况
        y += 1 + 13                                   # 分隔线
        y += ls("meta") + 13                          # 体感/湿度/风
        y += 1 + 13                                   # 分隔线
        y += ls("clock") + 4                          # 时钟
        y += ls("date") + 13                          # 日期
        y += 1 + 13                                   # 分隔线
        y += max(ls("sun"), 30) + 8                   # 日出/日落
        y += ls("status") + 10                        # 倒计时
        y += 6 + 14                                   # 进度条
        y += ls("hint") + 16                          # 提示
        return {"W": W, "H": int(y)}

    # ---------- 界面 ----------
    def _rrect(self, x1, y1, x2, y2, r, **kw):
        return self.canvas.create_polygon(
            [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
             x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
             x1, y2, x1, y2 - r, x1, y1 + r, x1, y1],
            smooth=True, **kw)

    def _build_ui(self):
        c = self.canvas
        f = self.f
        pad = 16
        self._rrect(0, 0, self.W, self.H, 20, fill=CARD, outline=CARD_EDGE, width=1)

        y = 14.0
        self.id_city = c.create_text(pad, y, text=self.cfg["city"], anchor="nw",
                                     font=f["city"], fill="#c9cfe8")
        self.id_temp = c.create_text(self.W - pad, y, text="—", anchor="ne",
                                     font=f["temp"], fill=TEXT)
        y += max(f["city"].metrics("linespace"), f["temp"].metrics("linespace")) + 8

        self.id_cond = c.create_text(self.W - pad, y, text="天气加载中…", anchor="ne",
                                     font=f["cond"], fill=SUB)
        y += f["cond"].metrics("linespace") + 12

        c.create_line(pad, y, self.W - pad, y, fill=CARD_EDGE)
        y += 1 + 13

        self.id_meta = c.create_text(self.W / 2, y, text="体感 — · 湿度 — · 风 —",
                                     font=f["meta"], fill=SUB)
        y += f["meta"].metrics("linespace") + 13

        c.create_line(pad, y, self.W - pad, y, fill=CARD_EDGE)
        y += 1 + 13

        self.id_clock = c.create_text(self.W / 2, y, text="00:00:00",
                                      font=f["clock"], fill=TEXT)
        y += f["clock"].metrics("linespace") + 4

        self.id_date = c.create_text(self.W / 2, y, text="",
                                     font=f["date"], fill=SUB)
        y += f["date"].metrics("linespace") + 13

        c.create_line(pad, y, self.W - pad, y, fill=CARD_EDGE)
        y += 1 + 13

        self.id_sr = c.create_text(self.W / 2 - 16, y, text="🌅 日出 --:--", anchor="e",
                                   font=f["sun"], fill="#ffd9a0")
        self.id_ss = c.create_text(self.W / 2 + 16, y, text="🌇 日落 --:--", anchor="w",
                                   font=f["sun"], fill=ACCENT)
        y += max(f["sun"].metrics("linespace"), 30) + 8

        self.id_status = c.create_text(self.W / 2, y, text="",
                                       font=f["status"], fill=ACCENT)
        y += f["status"].metrics("linespace") + 10

        bm = 56
        self.bar_rect = [bm, int(y), self.W - bm, int(y) + 6]
        self._rrect(*self.bar_rect, 3, fill="#232838", outline="")
        self.id_prog = c.create_rectangle(bm + 1, self.bar_rect[1] + 1,
                                          bm + 1, self.bar_rect[3] - 1,
                                          fill=ACCENT, outline="")
        y += 6 + 14

        self.id_hint = c.create_text(pad, y, text="左键拖动 · 右键菜单",
                                     anchor="w", font=f["hint"], fill=HINT)
        bx1, by1, bx2, by2 = self.W - 72, int(y) - 11, self.W - 12, int(y) + 11
        self.btn_rect = (bx1, by1, bx2, by2)
        self.id_btn = self._rrect(bx1, by1, bx2, by2, 8, fill="#232838", outline=CARD_EDGE)
        self.id_btn_txt = c.create_text((bx1 + bx2) / 2, y, text="🙈 隐藏",
                                        font=f["hint"], fill="#c9cfe8")
        for item in (self.id_btn, self.id_btn_txt):
            c.tag_bind(item, "<Button-1>", lambda e: self._manual_hide())
            c.tag_bind(item, "<Enter>", lambda e: c.configure(cursor="hand2"))
            c.tag_bind(item, "<Leave>", lambda e: c.configure(cursor=""))

    def _place(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        pos = self.cfg.get("position")
        x = pos[0] if pos else sw - self.W - self.cfg["margin_x"]
        y = pos[1] if pos else self.cfg["margin_y"]
        x = max(0, min(int(x), sw - self.W))
        y = max(0, min(int(y), sh - self.H - 40))
        self.root.geometry("{}x{}+{}+{}".format(self.W, self.H, x, y))

    def _bind(self):
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Button-3>", self._menu)

    # ---------- 拖动 ----------
    def _on_press(self, e):
        bx1, by1, bx2, by2 = self.btn_rect
        if bx1 <= e.x <= bx2 and by1 <= e.y <= by2:
            self._btn_click = True
            return
        self._btn_click = False
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()

    def _on_drag(self, e):
        if self._btn_click:
            return
        self.root.geometry("+{}+{}".format(e.x_root - self._dx, e.y_root - self._dy))

    def _on_release(self, e):
        if self._btn_click:
            self._btn_click = False
            return
        self._save_position()

    def _save_position(self):
        # 从磁盘合并最新配置，避免内存中的旧值覆盖用户手动修改
        disk = load_config()
        disk["position"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_config(disk)
        self.cfg = disk

    # ---------- 右键菜单 ----------
    def _menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="刷新天气", command=self._refresh_now)
        m.add_command(label="隐藏小组件", command=self._manual_hide)
        m.add_checkbutton(label="开机自启动", variable=self._autostart_var,
                          command=self._toggle_autostart)
        m.add_separator()
        m.add_command(label="退出小组件", command=self._quit)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _refresh_now(self):
        self._wake.set()

    # ---------- 开机自启动 ----------
    def _query_autostart(self):
        self._autostart_on = self._task_enabled()
        self.root.after(0, lambda: self._autostart_var.set(self._autostart_on))

    def _task_enabled(self):
        try:
            out = subprocess.run(
                ["schtasks", "/query", "/tn", "DesktopWidget", "/fo", "csv", "/nh"],
                capture_output=True, stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            text = out.stdout.decode("gbk", errors="ignore")
            if out.returncode != 0 or "DesktopWidget" not in text:
                return False
            low = text.lower()
            return not ("disabled" in low or "禁用" in text)
        except Exception:
            return False

    def _toggle_autostart(self):
        self._apply_autostart(not self._autostart_on)

    def _cmd_toggle_autostart(self):
        self._apply_autostart(not self._autostart_on)

    def _apply_autostart(self, enable):
        def work():
            try:
                out = subprocess.run(
                    ["schtasks", "/change", "/tn", "DesktopWidget",
                     "/enable" if enable else "/disable"],
                    capture_output=True, stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
                try:
                    with open(os.path.join(BASE_DIR, "autostart.log"), "a", encoding="utf-8") as f:
                        f.write("{} want={} rc={} out={!r} err={!r}\n".format(
                            time.strftime("%H:%M:%S"), enable, out.returncode,
                            out.stdout.decode("gbk", errors="ignore"),
                            out.stderr.decode("gbk", errors="ignore")))
                except Exception:
                    pass
            except Exception as e:
                try:
                    with open(os.path.join(BASE_DIR, "autostart.log"), "a", encoding="utf-8") as f:
                        f.write("{} want={} EXC {}\n".format(time.strftime("%H:%M:%S"), enable, e))
                except Exception:
                    pass
            self._autostart_on = self._task_enabled()
            self.root.after(0, lambda: self._autostart_var.set(self._autostart_on))

        threading.Thread(target=work, daemon=True).start()

    # ---------- 隐藏 / 显示 ----------
    def _manual_hide(self):
        self._manual_hidden = True
        self._apply_visibility()

    def _cmd_hide(self):
        self._manual_hidden = True
        self._apply_visibility()

    def _cmd_show(self):
        self._manual_hidden = False
        self._apply_visibility()

    def _cmd_fs(self):
        # 调试用：手动翻转“全屏”状态并保持
        self._fs_hold = not getattr(self, "_fs_hold", False)
        self._auto_hidden = self._fs_hold
        self._apply_visibility()

    def _apply_visibility(self):
        hidden = self._auto_hidden or self._manual_hidden
        try:
            if hidden and self.root.winfo_viewable():
                self.root.withdraw()
            elif not hidden and not self.root.winfo_viewable():
                self.root.deiconify()
        except Exception:
            pass
        # 仅手动隐藏时显示恢复小按钮；自动隐藏时不打扰
        if self._manual_hidden and not self._auto_hidden:
            self._show_pill()
        else:
            self._hide_pill()

    def _show_pill(self):
        if self._pill is not None:
            return
        p = tk.Toplevel(self.root)
        p.overrideredirect(True)
        p.attributes("-topmost", True)
        try:
            p.attributes("-alpha", 0.92)
        except Exception:
            pass
        try:
            p.attributes("-transparentcolor", KEY)
        except Exception:
            pass
        pw, ph = 118, 26
        x = self.root.winfo_screenwidth() - pw - 16
        p.geometry("{}x{}+{}+{}".format(pw, ph, x, 16))
        c = tk.Canvas(p, width=pw, height=ph, bg=KEY, highlightthickness=0)
        c.pack()
        c.create_polygon(
            [6, 0, pw - 6, 0, pw, 0, pw, 6, pw, ph - 6, pw, ph,
             pw - 6, ph, 6, ph, 0, ph, 0, ph - 6, 0, 6, 0, 0],
            smooth=True, fill=CARD, outline=CARD_EDGE)
        c.create_text(pw / 2, ph / 2, text="👁 显示小组件",
                      font=("Microsoft YaHei UI", 9), fill="#c9cfe8")
        c.bind("<Button-1>", self._pill_click)
        c.configure(cursor="hand2")
        self._pill = p

    def _hide_pill(self):
        if self._pill is not None:
            try:
                self._pill.destroy()
            except Exception:
                pass
            self._pill = None

    def _pill_click(self, e):
        self._manual_hidden = False
        self._apply_visibility()

    # ---------- 全屏检测 ----------
    def _auto_check(self):
        now = time.time()
        if now - self._last_fs_check < 1.0:
            return
        self._last_fs_check = now
        if getattr(self, "_fs_hold", False):
            return
        fs = self._foreground_is_fullscreen()
        if fs != self._auto_hidden:
            self._auto_hidden = fs
            self._apply_visibility()

    def _foreground_is_fullscreen(self):
        try:
            hwnd = USER32.GetForegroundWindow()
            if not hwnd or hwnd == self.root.winfo_id():
                return False
            r = wintypes.RECT()
            if not USER32.GetWindowRect(hwnd, ctypes.byref(r)):
                return False
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            if r.left <= 1 and r.top <= 1 and r.right >= sw - 1 and r.bottom >= sh - 1:
                cls = ctypes.create_unicode_buffer(64)
                USER32.GetClassNameW(hwnd, cls, 64)
                if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
                    return False
                return True
        except Exception:
            pass
        return False

    # ---------- 控制通道 ----------
    def _control_thread(self, sock):
        try:
            while not self._stop.is_set():
                sock.settimeout(1.0)
                try:
                    conn, _ = sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    data = conn.recv(64).decode("utf-8", "ignore").strip().lower()
                except Exception:
                    data = ""
                if data == "state":
                    try:
                        conn.sendall("manual={} auto={} hold={} autostart={}".format(
                            self._manual_hidden, self._auto_hidden,
                            getattr(self, "_fs_hold", False), self._autostart_on).encode())
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue
                try:
                    conn.close()
                except Exception:
                    pass
                if data == "hide":
                    self.root.after(0, self._cmd_hide)
                elif data == "show":
                    self.root.after(0, self._cmd_show)
                elif data == "fs":
                    self.root.after(0, self._cmd_fs)
                elif data == "autostart":
                    self.root.after(0, self._cmd_toggle_autostart)
                elif data == "quit":
                    self.root.after(0, self._quit)
        except Exception:
            pass

    def _quit(self):
        self._save_position()
        self._stop.set()
        self.root.destroy()

    # ---------- 数据线程 ----------
    def _weather_loop(self):
        while not self._stop.is_set():
            try:
                self._weather = fetch_weather(self.cfg)
            except Exception:
                if self._weather is None:
                    self._weather = {"failed": True, "ts": time.time()}
            self._wake.wait(self.cfg["refresh_minutes"] * 60)
            self._wake.clear()

    # ---------- 刷新循环 ----------
    def _tick(self):
        now = datetime.now()
        ts = now.strftime("%H:%M:%S")
        if ts != self._last_ts:
            self._last_ts = ts
            self.canvas.itemconfig(self.id_clock, text=ts)
            self.canvas.itemconfig(
                self.id_date,
                text="{}年{}月{}日 · 星期{}".format(
                    now.year, now.month, now.day, "一二三四五六日"[now.weekday()]))
        if self._weather is not None and self._weather is not self._applied:
            self._applied = self._weather
            self._apply(self._weather)
        if isinstance(self._weather, dict) and "sunrise0" in self._weather:
            self._update_sun(self._weather)
        self._auto_check()
        self.root.after(250, self._tick)

    def _apply(self, w):
        if w.get("failed"):
            self.canvas.itemconfig(self.id_temp, text="—")
            self.canvas.itemconfig(self.id_cond, text="🌐 天气加载失败")
            self.canvas.itemconfig(self.id_meta, text="检查网络，稍后自动重试")
            return
        emoji, desc = WMO.get(w["code"], ("🌡️", "未知"))
        self.canvas.itemconfig(self.id_city, text=self.cfg["city"])
        self.canvas.itemconfig(self.id_temp, text="{:.1f}°".format(w["temp"]))
        self.canvas.itemconfig(self.id_cond, text="{} {}".format(emoji, desc))
        self.canvas.itemconfig(
            self.id_meta,
            text="体感 {:.0f}° · 湿度 {}% · 风 {:.1f}m/s".format(
                w["apparent"], w["humidity"], w["wind"]))

    def _update_sun(self, w):
        now = datetime.now()
        sr0 = parse_hhmm(w["sunrise0"])
        ss0 = parse_hhmm(w["sunset0"])
        sr1 = parse_hhmm(w["sunrise1"])
        self.canvas.itemconfig(self.id_sr, text="🌅 日出 " + sr0.strftime("%H:%M"))
        self.canvas.itemconfig(self.id_ss, text="🌇 日落 " + ss0.strftime("%H:%M"))
        if now < sr0:
            label, nxt = "日出", sr0
        elif now < ss0:
            label, nxt = "日落", ss0
        else:
            label, nxt = "日出", sr1
        secs = int((nxt - now).total_seconds())
        hh, mm = divmod(max(secs, 0), 3600)
        mm //= 60
        self.canvas.itemconfig(self.id_status, text="距{}还有 {}小时{:02d}分".format(label, hh, mm))
        total = (ss0 - sr0).total_seconds()
        p = 0.0 if total <= 0 else (now - sr0).total_seconds() / total
        p = max(0.0, min(1.0, p))
        bx1, by, bx2, by2 = self.bar_rect
        span = (bx2 - bx1 - 2)
        self.canvas.coords(self.id_prog, bx1 + 1, by + 1, bx1 + 1 + span * p, by2 - 1)

    # ---------- 调试自拍 ----------
    def _snapshot(self):
        try:
            from PIL import ImageGrab
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            img = ImageGrab.grab(bbox=(x, y, x + self.W, y + self.H))
            img.save(self._snap_path)
            print("SNAP OK", self._snap_path, flush=True)
        except Exception as e:
            print("SNAP FAIL", e, flush=True)


_instance_sock = None


def main():
    global _instance_sock
    # 单实例保护
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 39217))
    except OSError:
        return
    s.listen(1)
    _instance_sock = s

    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    w = Widget(control_sock=s)
    w.root.mainloop()


if __name__ == "__main__":
    main()
