# -*- coding: utf-8 -*-
"""
眼保健强制休息提醒（EyeGuard）—— 单文件桌面小程序
==================================================

纯 Python 标准库实现（tkinter + Windows 下的 ctypes），完全离线、不联网。

功能
----
1.  半透明常驻浮窗：mm:ss 显示距下次提醒的剩余时间，置顶、可拖动、尽量不进任务栏。
2.  提前预警：提醒前 30 秒 / 5 秒（可配置）浮窗变色闪烁 + 一行小字，不打断操作。
3.  定时全屏提醒：到点弹出全屏窗口，25 秒环形倒计时；期间屏蔽关闭按钮 / Esc / Alt+F4，
    Windows 下用低级键盘钩子屏蔽 Alt+Tab、Win 键、Ctrl+Esc 等任务切换快捷键；
    窗口周期性重新置顶 + 抢焦点，倒计时结束自动消失并重置计时。
4.  config.json 与 main.py 同目录，不存在则自动生成默认配置；外部修改后热重载。

运行：
    python main.py            # 正常启动
    python main.py --demo     # 启动后立刻弹一次全屏提醒（测试用）
    python main.py --allow-multi   # 允许同时开多个实例（默认单实例）

依赖：无。只用标准库，不需要 pip install 任何东西（见 requirements.txt）。

快捷键 / 鼠标：
    左键拖动浮窗      移动位置（自动写回 config.json）
    右键浮窗          打开菜单（立即休息 / 重新加载配置 / 打开配置文件夹 / 退出）
"""

import argparse
import datetime
import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import OrderedDict

# =============================================================================
# 0. 基础常量与工具函数
# =============================================================================

_IS_WIN = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"
_IS_LINUX = sys.platform.startswith("linux")

FROZEN = bool(getattr(sys, "frozen", False))          # 是否由 PyInstaller 打包成 exe


def _app_dir():
    """config.json / 日志放在哪。

    - 直接跑 main.py：脚本所在目录（方便查看和修改）
    - 打包成 exe（onefile 模式）：exe 所在目录（_MEIPASS 是每次启动新建的临时目录，
      放在那里配置会丢），这样 exe 复制到任何路径都能正常保存设置。
    """
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
LOG_PATH = os.path.join(APP_DIR, "eyeguard.log")
DEFAULT_CONFIG_PATH = os.path.join(APP_DIR, "config.json")



def log(msg):
    """写一行带时间戳的日志：控制台 + eyeguard.log（便于排查问题）。"""
    line = "[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fmt_mmss(seconds):
    """秒数 -> "mm:ss"（向上取整，负数按 0 处理）。"""
    seconds = max(0, int(math.ceil(seconds)))
    return "%02d:%02d" % (seconds // 60, seconds % 60)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def num_of(value, default, lo, hi, as_int=False):
    """容错取数：非法值回退默认值，并夹在 [lo, hi] 内。"""
    try:
        v = int(round(float(value))) if as_int else float(value)
    except Exception:
        v = int(default) if as_int else float(default)
    return int(clamp(v, lo, hi)) if as_int else clamp(float(v), float(lo), float(hi))


def bool_of(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "是")
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(default)


def hex_to_rgb(value, default=(20, 24, 33)):
    """'#RRGGBB' / '#RGB' -> (r, g, b)。"""
    try:
        v = str(value).strip().lstrip("#")
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        if len(v) == 6:
            return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return default


# =============================================================================
# 1. Windows 原生能力（懒加载 + 全程 try/except，非 Windows 自动降级）
# =============================================================================

class Win32(object):
    """封装 Windows 上 tkinter 做不到的几件事。

    * 不进任务栏 / 不出现在 Alt+Tab：WS_EX_TOOLWINDOW（+ WS_EX_NOACTIVATE 不抢焦点）
    * 周期性重新置顶：SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE)
    * 强制抢焦点：AttachThreadInput + BringWindowToTop + SetForegroundWindow
    * 屏蔽系统“任务切换弹窗”：SystemParametersInfo(SPI_SETSCREENSAVERRUNNING)
    * 隐藏鼠标指针：SetCursor(None)
    """

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_APPWINDOW = 0x00040000
    HWND_TOPMOST = -1
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SPI_SETSCREENSAVERRUNNING = 97
    SPIF_SENDCHANGE = 0x02

    def __init__(self):
        self.ok = False
        if not _IS_WIN:
            return
        try:
            import ctypes
            from ctypes import wintypes

            self.ctypes = ctypes
            self.wintypes = wintypes
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            u = self.user32
            # 只有 64 位系统需要把返回句柄的函数声明成指针宽度
            if platform.architecture()[0] == "64bit":
                u.GetWindowLongPtrW.restype = ctypes.c_void_p
                u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
                u.SetWindowLongPtrW.restype = ctypes.c_void_p
                u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            u.GetWindowLongW.restype = ctypes.c_long
            u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            u.SetWindowPos.restype = wintypes.BOOL
            u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u.GetWindowThreadProcessId.restype = wintypes.DWORD
            u.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                   ctypes.POINTER(wintypes.DWORD)]
            u.GetForegroundWindow.restype = wintypes.HWND
            u.SetForegroundWindow.restype = wintypes.BOOL
            u.SetForegroundWindow.argtypes = [wintypes.HWND]
            u.BringWindowToTop.restype = wintypes.BOOL
            u.BringWindowToTop.argtypes = [wintypes.HWND]
            u.AttachThreadInput.restype = wintypes.BOOL
            u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
            u.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint,
                                                ctypes.c_void_p, ctypes.c_uint]
            self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            self.ok = True
        except Exception as exc:
            log("Win32 初始化失败，将以纯 tkinter 降级模式运行：%s" % exc)
            self.ok = False

    # ---- 句柄 / 样式 -------------------------------------------------------

    def get_hwnd(self, tk_window):
        """tkinter 顶层窗口的 HWND（Windows 上 winfo_id() 返回的就是 HWND）。"""
        if not self.ok:
            return 0
        try:
            tk_window.update_idletasks()
            return int(tk_window.winfo_id())
        except Exception:
            return 0

    def _get_ex_style(self, hwnd):
        try:
            v = self.user32.GetWindowLongPtrW(hwnd, self.GWL_EXSTYLE)
            if v:
                return int(v) & 0xFFFFFFFF
        except Exception:
            pass
        try:
            return int(self.user32.GetWindowLongW(hwnd, self.GWL_EXSTYLE)) & 0xFFFFFFFF
        except Exception:
            return 0

    def make_tool_window(self, hwnd):
        """不出现在任务栏 / Alt+Tab，且不抢焦点（浮窗用）。"""
        if not self.ok or not hwnd:
            return False
        try:
            style = self._get_ex_style(hwnd)
            style = (style | self.WS_EX_TOOLWINDOW | self.WS_EX_NOACTIVATE) & ~self.WS_EX_APPWINDOW
            self.user32.SetWindowLongPtrW(hwnd, self.GWL_EXSTYLE, style)
            self.user32.SetWindowLongW(hwnd, self.GWL_EXSTYLE, style & 0xFFFFFFFF)
            return True
        except Exception as exc:
            log("设置工具窗口样式失败：%s" % exc)
            return False

    # ---- 置顶 / 抢焦点 -----------------------------------------------------

    def set_topmost(self, hwnd):
        """把窗口重新压到最顶层，但不激活（不抢焦点）。"""
        if not self.ok or not hwnd:
            return False
        try:
            self.user32.SetWindowPos(hwnd, self.HWND_TOPMOST, 0, 0, 0, 0,
                                     self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE)
            return True
        except Exception:
            return False

    def force_foreground(self, hwnd):
        """强行把窗口抢到前台。

        单独的 SetForegroundWindow 会被系统前台锁拦住（别的进程正当前台时），
        所以先 AttachThreadInput 到当前前台线程，再 BringWindowToTop + SetForegroundWindow，
        最后再置顶一次。
        """
        if not self.ok or not hwnd:
            return False
        u = self.user32
        ok = False
        try:
            self.set_topmost(hwnd)
            fg = u.GetForegroundWindow()
            fg_tid = u.GetWindowThreadProcessId(fg, None) if fg else 0
            cur_tid = self.kernel32.GetCurrentThreadId()
            attached = False
            if fg_tid and fg_tid != cur_tid:
                attached = bool(u.AttachThreadInput(fg_tid, cur_tid, True))
            try:
                u.BringWindowToTop(hwnd)
                u.ShowWindow(hwnd, 9)   # SW_RESTORE
                ok = bool(u.SetForegroundWindow(hwnd))
            finally:
                if attached:
                    u.AttachThreadInput(fg_tid, cur_tid, False)
            self.set_topmost(hwnd)
        except Exception as exc:
            log("抢焦点失败（已降级为仅置顶）：%s" % exc)
        return ok

    def disable_system_tab_popup(self, enable):
        """开启后系统不再把该组合键当“任务切换”处理（关闭时系统任务切换也被禁用）。"""
        if not self.ok:
            return False
        try:
            val = self.ctypes.c_int(1 if enable else 0)
            self.user32.SystemParametersInfoW(self.SPI_SETSCREENSAVERRUNNING, 0,
                                              self.ctypes.byref(val), self.SPIF_SENDCHANGE)
            return True
        except Exception:
            return False

    # ---- 鼠标拖动（子类化窗口过程） ----------------------------------------

    def subclass_mouse(self, hwnd, handler):
        """给窗口装一个鼠标钩子（子类化窗口过程），用来拖动浮窗。

        为什么不用 tkinter 的 <B1-Motion>：无边框 + 色键透明窗口在部分系统/输入法下
        收不到 Tk 的鼠标事件，而 WM_NCHITTEST 返回 HTCAPTION 又会让系统接管拖动、
        导致窗口跟着鼠标乱跳。这里用 SetWindowLongPtrW(GWLP_WNDPROC) 截获
        WM_LBUTTONDOWN / WM_MOUSEMOVE / WM_LBUTTONUP / WM_RBUTTONUP 自己算偏移。
        色键透明窗口“看着透明、实际仍能点击”，所以把点击限制在浮窗矩形内即可。
        """
        if not self.ok or not hwnd:
            return False
        try:
            ctypes = self.ctypes
            wintypes = self.wintypes
            GWLP_WNDPROC = -4
            WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONUP = 0x0200, 0x0201, 0x0202, 0x0205

            self.user32.CallWindowProcW.restype = ctypes.c_ssize_t
            self.user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                                    ctypes.c_uint, wintypes.WPARAM,
                                                    wintypes.LPARAM]
            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint,
                                         wintypes.WPARAM, wintypes.LPARAM)
            old = int(self.user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC) or 0)
            state = {"off": None}

            class CURSORPOS(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            def wnd_proc(h, msg, wp, lp):
                try:
                    if msg == WM_LBUTTONDOWN:
                        pt = CURSORPOS()
                        self.user32.GetCursorPos(ctypes.byref(pt))
                        state["off"] = handler("drag_start", pt.x, pt.y)
                        return 0
                    if msg == WM_MOUSEMOVE and state["off"] is not None:
                        pt = CURSORPOS()
                        self.user32.GetCursorPos(ctypes.byref(pt))
                        handler("drag_move", pt.x, pt.y, state["off"])
                        return 0
                    if msg == WM_LBUTTONUP:
                        if state["off"] is not None:
                            handler("drag_end", 0, 0, state["off"])
                        state["off"] = None
                        return 0
                    if msg == WM_RBUTTONUP:
                        pt = CURSORPOS()
                        self.user32.GetCursorPos(ctypes.byref(pt))
                        handler("menu", pt.x, pt.y)
                        return 0
                except Exception:
                    pass
                return self.user32.CallWindowProcW(ctypes.c_void_p(old), h, msg, wp, lp)

            self._wndproc = WNDPROC(wnd_proc)      # 必须保住引用，否则被 GC 后直接崩溃
            self._wndproc_old = old
            self.user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC,
                                          ctypes.cast(self._wndproc, ctypes.c_void_p))
            return True
        except Exception as exc:
            log("安装鼠标拖动钩子失败（将退化为不可拖动）：%s" % exc)
            return False

    # ---- 鼠标光标 ----------------------------------------------------------

    def hide_cursor(self, enable):
        """全屏提醒时隐藏鼠标指针，避免指针在动画上晃来晃去。"""
        if not self.ok:
            return False
        try:
            self.user32.SetCursor(None if enable else 0)
            return True
        except Exception:
            return False


# =============================================================================
# 2. 低级键盘钩子（仅 Windows）：阻塞会离开提醒窗口的按键
# =============================================================================

class KeyboardBlocker(object):
    """Windows 低级键盘钩子 WH_KEYBOARD_LL。

    拦截规则（在钩子回调里返回 1 = 吞掉该按键，系统再也收不到）：
      * Win 键（左/右）、菜单键：全部吞掉 —— Solitaire 等游戏的开始菜单会被彻底锁住。
      * Esc、Ctrl+Esc：吞掉。
      * Alt 组合键（Alt+F4 / Alt+Tab / Alt+Esc / Alt+Space…）：只放行 Alt 本身的
        按下/抬起消息，其他键一律吞掉。这样“抬起 Alt”不会丢，游戏里 Alt 状态不会错乱，
        同时 Alt+Tab 也不会切走。
      * Tab 键：按住 Alt 时吞掉（窗口级兜底见 FullscreenReminder）。
    物理上拦不住的：Ctrl+Alt+Del（SAS，由内核直接处理，任何用户态程序都拦不住）、
    部分系统游戏栏/输入法抢占的 Win+ 组合，这也是“降级方案”必须存在的原因。
    """

    VK_LWIN, VK_RWIN, VK_TAB, VK_ESCAPE, VK_APPS = 0x5B, 0x5C, 0x09, 0x1B, 0x5D
    VK_ALTS = (0x12, 0xA4, 0xA5)   # Alt / LAlt / RAlt
    WH_KEYBOARD_LL = 13

    def __init__(self, win32):
        self.w32 = win32
        self.active = False          # 仅在“全屏提醒”期间为 True
        self._hook = None
        self._cb = None
        self._thread = None
        self._ready = threading.Event()
        self._error = None

    # ---------------- 安装 / 卸载（在 UI 线程调用） ----------------

    def install(self):
        if not self.w32.ok:
            return False
        if self._hook is not None:
            return True
        self._error = None
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="EyeGuardHook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)
        if self._hook is None:
            log("键盘钩子安装失败：%s（降级：仅全屏置顶 + 抢焦点 + 窗口级屏蔽）" % self._error)
            return False
        log("低级键盘钩子已安装：屏蔽 Win 键 / Alt+Tab / Alt+F4 / Alt+Esc / Ctrl+Esc")
        return True

    def uninstall(self):
        if self._hook is None or not self.w32.ok:
            return
        try:
            self.w32.user32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass
        self._hook = None
        log("键盘钩子已卸载")

    def alt_down(self):
        """Alt 是否被按住（即使 Alt 消息被吞掉，GetAsyncKeyState 依然能查到）。"""
        if not self.w32.ok:
            return False
        try:
            return bool(self.w32.user32.GetAsyncKeyState(0x12) & 0x8000)
        except Exception:
            return False

    # ---------------- 钩子线程 ----------------

    def _run(self):
        try:
            ctypes = self.w32.ctypes
            wintypes = self.w32.wintypes
            u, k = self.w32.user32, self.w32.kernel32
            LRESULT = ctypes.c_ssize_t
            HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

            class KBDLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [("vkCode", wintypes.DWORD),
                            ("scanCode", wintypes.DWORD),
                            ("flags", wintypes.DWORD),
                            ("time", wintypes.DWORD),
                            ("dwExtraInfo", ctypes.c_size_t)]

            k.GetModuleHandleW.restype = ctypes.c_void_p
            k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            u.SetWindowsHookExW.restype = ctypes.c_void_p
            u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
            u.CallNextHookEx.restype = LRESULT
            u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                         wintypes.WPARAM, wintypes.LPARAM]
            u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            u.GetMessageW.restype = ctypes.c_int
            u.GetAsyncKeyState.restype = ctypes.c_short
            u.GetAsyncKeyState.argtypes = [ctypes.c_int]

            def handler(n_code, w_param, l_param):
                try:
                    if n_code == 0 and self.active:
                        kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                        if self._should_block(int(kb.vkCode)):
                            return 1          # 已处理 → 事件不再传递
                except Exception:
                    pass
                return u.CallNextHookEx(None, n_code, w_param, l_param)

            self._cb = HOOKPROC(handler)
            hook = u.SetWindowsHookExW(self.WH_KEYBOARD_LL, self._cb, k.GetModuleHandleW(None), 0)
            if not hook:
                self._error = "SetWindowsHookExW 失败，错误码 %s" % ctypes.get_last_error()
                self._ready.set()
                return
            self._hook = hook
            self._ready.set()

            # 安装钩子的线程必须跑消息循环，钩子回调才会被调用
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self._error = exc
            self._ready.set()
            log("键盘钩子线程异常退出：%s" % exc)

    def _should_block(self, vk):
        if not self.active:
            return False
        if vk in (self.VK_LWIN, self.VK_RWIN, self.VK_APPS):
            return True                                  # Win / 菜单键
        alt_or_alt_pressed = self.alt_down() or vk in self.VK_ALTS
        if alt_or_alt_pressed:
            return vk not in self.VK_ALTS                # Alt+X 吞 X，Alt 本身放行
        if vk in (self.VK_TAB, self.VK_ESCAPE):
            return True
        return False


# =============================================================================
# 3. 配置管理（读取 / 自动生成 / 校验 / 热重载）
# =============================================================================

DEFAULT_CONFIG = OrderedDict([
    ("interval_minutes", 20),
    ("fullscreen_countdown_seconds", 25),
    ("warn_seconds", [30, 5]),
    ("reminder_messages", [
        "你已经玩了 {minutes} 分钟，为了眼睛，去看看外面吧！",
        "叮！{minutes} 分钟到啦，窗外有风景，屏幕有蓝光，你选哪个？",
        "你的眼睛向你提交了第 {minutes} 分钟的加班申请，请立刻驳回。",
        "游戏角色不会累，你的眼睛会。已经 {minutes} 分钟了，起来看看远处吧。",
        "休息 25 秒，回来继续肝 —— {minutes} 分钟的马不停蹄，眼睛需要喘口气。",
        "别眨眼，眨眼你也躲不过：你已经玩了 {minutes} 分钟，该看窗外了。",
        "前方高能：连续 {minutes} 分钟盯屏幕，眼球表示压力很大，请望向远方。",
        "这 {minutes} 分钟，你的世界只有这一块屏幕；接下来二十几秒，请还给世界。",
    ]),
    ("fullscreen", OrderedDict([
        ("title", "该休息啦"),
        ("bg_color", "#0b0e14"),
        ("track_color", "#242a38"),
        ("track_width", 14),
        ("fg_color", "#ffffff"),
        ("sub_color", "#8b93a7"),
        ("circle_color", "#33d17a"),
        ("circle_width", 14),
        ("circle_radius", 120),
        ("dot_radius", 12),
        ("dot_color", ""),
        ("fps", 50),
        ("message_font_size", 26),
        ("sub_font_size", 14),
        ("countdown_number_inside", False),
        ("hide_cursor", True),
        ("allow_skip", True),
        ("topmost_refresh_ms", 300),
        ("block_task_switch_keys", True),
    ])),
    ("floating", OrderedDict([
        ("enabled", True),
        ("width", 220),
        ("height", 96),
        ("x", 60),
        ("y", 60),
        ("alpha", 0.82),
        ("font_size", 34),
        ("label_font_size", 11),
        ("bg_color", "#141821"),
        ("key_color", "#010203"),
        ("fg_color", "#ffffff"),
        ("label_color", "#8b93a7"),
        ("normal_border", "#3a4256"),
        ("warn_border", "#ffb000"),
        ("warn_bg", "#3a2a05"),
        ("warn_text_color", "#ffb000"),
        ("blink_interval_ms", 400),
    ])),
    ("prewarn", OrderedDict([
        ("enabled", True),
        ("text_template", "{seconds} 秒后该看外面啦"),
        ("urgent_text_template", "还有 {seconds} 秒！"),
    ])),
])


def deep_copy(obj):
    return json.loads(json.dumps(obj))


def deep_update(base, extra):
    """把 extra 递归合并进 base（base 必须是副本）。"""
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = deep_copy(v)


def fill_missing(target, defaults):
    """把 defaults 中 target 缺失的键补上，返回是否补过。"""
    changed = False
    for k, v in defaults.items():
        if k not in target:
            target[k] = deep_copy(v)
            changed = True
        elif isinstance(v, dict) and isinstance(target[k], dict):
            changed = fill_missing(target[k], v) or changed
    return changed


class Config(object):
    def __init__(self, path):
        self.path = path
        self.data = deep_copy(DEFAULT_CONFIG)
        self._mtime = None
        self.load_or_create()

    # ---------- 文件 IO ----------

    def load_or_create(self, first_load=False):
        created = False
        if not os.path.exists(self.path):
            self.data = deep_copy(DEFAULT_CONFIG)
            self.save(self.data)
            created = True
            log("未找到配置文件，已生成默认配置：%s" % self.path)
        raw = None
        try:
            with open(self.path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f, object_pairs_hook=OrderedDict)
        except Exception as exc:
            if not first_load:
                log("配置文件解析失败（%s），继续使用当前配置" % exc)
                return False
        data = deep_copy(DEFAULT_CONFIG)
        if isinstance(raw, dict):
            deep_update(data, raw)
            if fill_missing(raw, DEFAULT_CONFIG) or created:
                # 用户缺项时把补全后的完整配置写回，方便对照修改
                try:
                    self.save(row_order(raw))
                    log("配置文件已补全新增的默认配置项")
                except Exception:
                    pass
        for key in ("fullscreen", "floating", "prewarn"):
            if not isinstance(data.get(key), dict):
                data[key] = deep_copy(DEFAULT_CONFIG[key])
        self.data = data
        self.validate()
        try:
            self._mtime = os.path.getmtime(self.path)
        except Exception:
            self._mtime = None
        return True

    def save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def maybe_reload(self):
        """外部改动 config.json 后自动生效。"""
        try:
            mtime = os.path.getmtime(self.path)
        except Exception:
            return False
        if self._mtime is not None and abs(mtime - self._mtime) < 1e-6:
            return False
        old = self._mtime
        ok = self.load_or_create()
        if ok and self._mtime is not None and old is not None and self._mtime < old:
            return False                      # 文件被“写回旧版本”时忽略
        log("检测到 config.json 变化，配置已重新加载")
        return ok

    # ---------- 校验 ----------

    def validate(self):
        d = self.data
        d["interval_minutes"] = num_of(d.get("interval_minutes"), 20, 0.05, 24 * 60)
        d["fullscreen_countdown_seconds"] = num_of(d.get("fullscreen_countdown_seconds"),
                                                   25, 3, 600, True)
        warn = d.get("warn_seconds")
        if not isinstance(warn, list):
            warn = [30, 5]
        cleaned = set()
        for w in warn:
            try:
                w = int(float(w))
            except Exception:
                continue
            if w > 0:
                cleaned.add(w)
        d["warn_seconds"] = sorted(cleaned, reverse=True) if cleaned else [30, 5]

        msgs = [m for m in (d.get("reminder_messages") or [])
                if isinstance(m, str) and m.strip()]
        d["reminder_messages"] = msgs or list(DEFAULT_CONFIG["reminder_messages"])

        fs = d["fullscreen"]
        fs["fps"] = num_of(fs.get("fps"), 50, 10, 120, True)
        fs["circle_width"] = num_of(fs.get("circle_width"), 14, 1, 200, True)
        fs["track_width"] = num_of(fs.get("track_width"), 14, 1, 200, True)
        fs["circle_radius"] = num_of(fs.get("circle_radius"), 120, 40, 2000, True)
        fs["dot_radius"] = num_of(fs.get("dot_radius"), 12, 0, 400, True)
        fs["message_font_size"] = num_of(fs.get("message_font_size"), 26, 8, 200, True)
        fs["sub_font_size"] = num_of(fs.get("sub_font_size"), 14, 6, 200, True)
        fs["topmost_refresh_ms"] = num_of(fs.get("topmost_refresh_ms"), 300, 50, 5000, True)
        for k in ("block_task_switch_keys", "countdown_number_inside", "hide_cursor"):
            fs[k] = bool_of(fs.get(k), DEFAULT_CONFIG["fullscreen"][k])

        fl = d["floating"]
        fl["enabled"] = bool_of(fl.get("enabled"), True)
        fl["width"] = num_of(fl.get("width"), 220, 90, 4000, True)
        fl["height"] = num_of(fl.get("height"), 96, 40, 4000, True)
        fl["x"] = num_of(fl.get("x"), 60, -20000, 20000, True)
        fl["y"] = num_of(fl.get("y"), 60, -20000, 20000, True)
        fl["alpha"] = num_of(fl.get("alpha"), 0.82, 0.1, 1.0)
        fl["font_size"] = num_of(fl.get("font_size"), 34, 8, 400, True)
        fl["label_font_size"] = num_of(fl.get("label_font_size"), 11, 6, 200, True)
        fl["blink_interval_ms"] = num_of(fl.get("blink_interval_ms"), 400, 50, 5000, True)

        pw = d["prewarn"]
        pw["enabled"] = bool_of(pw.get("enabled"), True)


def row_order(raw):
    """补全缺失键后按默认配置的键顺序整理一下写回（保持嵌套 OrderedDict）。"""
    out = OrderedDict()
    for k in DEFAULT_CONFIG:
        if k in raw:
            v = raw[k]
            if isinstance(v, dict) and isinstance(DEFAULT_CONFIG[k], dict):
                sub = OrderedDict()
                for kk in DEFAULT_CONFIG[k]:
                    if kk in v:
                        sub[kk] = v[kk]
                for kk, vv in v.items():
                    if kk not in sub:
                        sub[kk] = vv
                out[k] = sub
            else:
                out[k] = v
    for k, v in raw.items():
        if k not in out:
            out[k] = v
    return out


# =============================================================================
# 4. 圆形倒计时组件（create_arc 绘制）
# =============================================================================

class CircleCountdown(tk.Canvas):
    """一个圆 + 一条顺时针增长的进度弧 + 末端小圆点。

    tkinter arc 以 3 点钟方向为 0°、逆时针为正；这里 extent 取负数，弧线就从 12 点钟
    开始顺时针生长，正好对应“倒计时走完一圈”。
    """

    START = 90.0   # 12 点钟方向

    def __init__(self, master, radius, width, color, track_width, track_color,
                 dot_radius, dot_color, bg, number_font=None, fg="#ffffff", show_number=False):
        pad = max(width, track_width, dot_radius) // 2 + 8
        self.size = (radius + pad) * 2
        super(CircleCountdown, self).__init__(master, width=self.size, height=self.size, bg=bg,
                                              highlightthickness=0, bd=0)
        # 关闭窗口时先撤销自己 pending 的 after 回调，避免 Tcl 报 invalid command name
        self.bind("<Destroy>", self._cancel_pending, add="+")
        self._pending = None
        self.cx = self.cy = self.size / 2.0
        self.r = float(radius)
        self.box = (self.cx - self.r, self.cy - self.r, self.cx + self.r, self.cy + self.r)
        self.dot_r = int(dot_radius)
        if track_width > 0:
            self.create_oval(*self.box, outline=track_color, width=track_width)
        self._arc = self.create_arc(*self.box, start=self.START, extent=-0.01, style=tk.ARC,
                                    outline=color, width=width)
        self._dot = self.create_oval(-9, -9, -9, -9, fill=dot_color or color, outline="")
        self._num = None
        if show_number and number_font:
            self._num = self.create_text(self.cx, self.cy, text="", font=number_font,
                                         fill=fg)
        self.set_progress(0.0)

    def _cancel_pending(self, event=None):
        job = getattr(self, "_pending", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
            self._pending = None

    def set_progress(self, fraction, seconds_text=None):
        """fraction ∈ [0,1]：已走过整圈的比例（从顶部顺时针）。"""
        fraction = clamp(float(fraction), 0.0, 1.0)
        if fraction <= 0.0005:
            self.itemconfigure(self._arc, state="hidden")
            self.itemconfigure(self._dot, state="hidden")
        else:
            self.itemconfigure(self._arc, state="normal", extent=-360.0 * fraction)
            theta = math.radians(self.START - 360.0 * fraction)
            px = self.cx + self.r * math.cos(theta)
            py = self.cy - self.r * math.sin(theta)
            r = self.dot_r
            self.itemconfigure(self._dot, state="normal")
            self.coords(self._dot, px - r, py - r, px + r, py + r)
        if self._num is not None and seconds_text is not None:
            self.itemconfigure(self._num, text=seconds_text)


# =============================================================================
# 5. 全屏强制打断窗口
# =============================================================================

class FullscreenReminder(object):
    """全屏提醒窗口。生命周期：进入全屏 → 25 秒环 → 自动销毁并回调。"""

    def __init__(self, app, text, seconds):
        self.app = app
        self.fs = app.cfg.data["fullscreen"]
        self.total = float(seconds)
        self.done = False
        self._jobs = []

        bg = self.fs["bg_color"]
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)          # 无边框：没有标题栏，也就没有关闭按钮
        self.win.title(self.fs["title"])
        self.win.configure(bg=bg)
        try:
            self.win.attributes("-topmost", True)
        except Exception:
            pass

        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self.win.geometry("%dx%d+%d+%d" % (sw, sh, 0, 0))   # 覆盖主屏

        self.circle = CircleCountdown(
            self.win, self.fs["circle_radius"], self.fs["circle_width"],
            self.fs["circle_color"], self.fs["track_width"], self.fs["track_color"],
            self.fs["dot_radius"], self.fs.get("dot_color", ""), bg,
            number_font=(app.ui_font, max(18, self.fs["circle_radius"] // 3), "bold"),
            fg=self.fs["fg_color"],
            show_number=self.fs["countdown_number_inside"])

        self.msg = tk.Label(self.win, text=text, wraplength=int(sw * 0.8), justify=tk.CENTER,
                            font=(app.ui_font, self.fs["message_font_size"], "bold"),
                            fg=self.fs["fg_color"], bg=bg)
        self.sub = tk.Label(self.win, text="", font=(app.ui_font, self.fs["sub_font_size"]),
                            fg=self.fs["sub_color"], bg=bg)
        self.tip = tk.Label(self.win, text="这 %d 秒是给眼睛的，休息完自动返回游戏"
                            % int(self.total),
                            font=(app.ui_font, max(9, self.fs["sub_font_size"] - 3)),
                            fg=self.fs["sub_color"], bg=bg)

        self.msg.place(relx=0.5, rely=0.5, anchor="s",
                       y=-(self.fs["circle_radius"] + self.fs["circle_width"] + 50))
        self.circle.place(relx=0.5, rely=0.5, anchor="center")
        self.sub.place(relx=0.5, rely=0.5, anchor="n",
                       y=self.fs["circle_radius"] + self.fs["circle_width"] + 24)
        self.tip.place(relx=0.5, rely=1.0, anchor="s", y=-36)

        # ---- 屏蔽关闭：关窗回调置空 + 吞掉 Esc / Alt+F4 / Ctrl+W 等 ----
        self.win.protocol("WM_DELETE_WINDOW", self._ignore_close)
        for seq in ("<F4>", "<Alt-F4>", "<Control-w>", "<Control-q>",
                    "<Control-Alt-q>", "<Alt-F4>"):
            self.win.bind_all(seq, self._swallow, add="+")
        self.win.bind("<Alt-Tab>", self._swallow)
        self.win.bind("<Alt-Key-ISO_Left_Tab>", self._swallow)   # Linux/mac 的 Shift+Tab
        # 允许提前结束时：Esc 或单击任意处立即关闭
        if self.fs.get("allow_skip", True):
            self.win.bind_all("<Escape>", self._skip, add="+")
            self.win.bind("<Button-1>", self._skip)
        else:
            self.win.bind_all("<Escape>", self._swallow, add="+")
        self.win.bind("<Destroy>", self._on_destroy, add="+")

        self.app.notify("fullscreen_open", self)
        self.win.after_idle(self._show)
        self.start = time.monotonic()
        self._tick()

    # ---------------------------------------------------------------- 显示

    def _show(self):
        if self.done:
            return
        hwnd = self.app.w32.get_hwnd(self.win)
        self.win.deiconify()
        self.win.update_idletasks()
        self.win.lift()
        try:
            self.win.attributes("-topmost", True)
            self.win.focus_force()
        except Exception:
            pass
        self.app.w32.force_foreground(hwnd)
        if self.fs.get("block_task_switch_keys", True) and self.app.blocker:
            if self.app.blocker.install():
                self.app.blocker.active = True
        self.app.w32.hide_cursor(True)
        self.app.notify("fullscreen_shown", self)
        delay = int(self.fs["topmost_refresh_ms"])
        self._schedule(delay, self._keep_on_top)

    def _keep_on_top(self):
        """周期性重新置顶 + 抢焦点：防止游戏窗口（尤其无边框全屏的游戏）盖住提醒。"""
        if self.done:
            return
        hwnd = self.app.w32.get_hwnd(self.win)
        self.app.w32.force_foreground(hwnd)
        self._schedule(int(self.fs["topmost_refresh_ms"]), self._keep_on_top)

    # ---------------------------------------------------------------- 动画

    def _schedule(self, ms, fn):
        self._jobs.append(self.win.after(max(1, int(ms)), fn))

    def _tick(self):
        if self.done:
            return
        elapsed = time.monotonic() - self.start
        left = self.total - elapsed
        if left <= 0:
            self.close()
            return
        self.circle.set_progress(elapsed / self.total, str(int(math.ceil(left))))
        self.sub.config(text="%d 秒后自动返回 · 请抬头看看 6 米以外" % int(math.ceil(left)))
        # 用 after 续约实现 ~50FPS，不阻塞主线程
        self._jobs.append(self.win.after(max(1, int(1000 / float(self.fs["fps"]))), self._tick))

    # ---------------------------------------------------------------- 收尾

    def _ignore_close(self):
        """点击“窗口关闭”时什么都不做（全屏窗口本就没有标题栏，这里双保险）。"""
        return None

    def _swallow(self, event=None):
        return "break"

    def _skip(self, event=None):
        """用户提前结束提醒（Esc / 单击）。"""
        self.close()
        return "break"

    def _on_destroy(self, event):
        if event.widget is self.win and not self.done:
            self.close(destroyed=True)

    def close(self, destroyed=False):
        if self.done:
            return
        self.done = True
        for job in self._jobs:
            try:
                self.win.after_cancel(job)
            except Exception:
                pass
        self._jobs = []
        if self.app.blocker:
            self.app.blocker.active = False
        self.app.w32.hide_cursor(False)
        if not destroyed:
            try:
                self.win.destroy()
            except Exception:
                pass
        self.app.notify("fullscreen_closed", self)


# =============================================================================
# 6. 半透明常驻浮窗
# =============================================================================

class FloatingWindow(object):
    """置顶半透明浮窗：显示剩余时间、预警时闪烁高亮、可拖动。

    不抢焦点：Windows 下窗口加 WS_EX_NOACTIVATE，创建时也不调用 focus_force。
    不在任务栏显示：Windows 下加 WS_EX_TOOLWINDOW；Linux 下 overrideredirect。
    拖动：记录鼠标相对窗口左上角的偏移，拖动时重设 geometry。

    底部一条细进度条表示距离下一次休息还剩多少（越短越近）。
    """

    BAR_H = 3.0

    def __init__(self, app):
        self.app = app
        self.fl = app.cfg.data["floating"]
        self.warn_visible = False
        self.blink_on = False
        self._blink_job = None
        self._label_text = None
        self._time_text = None

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)          # 无边框（各平台都支持）
        self.win.title("EyeGuard")
        try:
            self.win.attributes("-topmost", True)
        except Exception:
            pass
        try:
            self.win.attributes("-alpha", self.fl["alpha"])
        except Exception as exc:
            log("设置浮窗透明度失败（平台可能不支持，已降级为不透明）：%s" % exc)
        try:
            self.win.resizable(False, False)
        except Exception:
            pass

        w, h = self.fl["width"], self.fl["height"]
        self.bg = self.fl["bg_color"]
        self.key = self._key_color()
        self.border = self.fl["normal_border"]
        self.border_w = 2
        self.corner = 14                          # 圆角半径
        self.transparent = False
        self.canvas = tk.Canvas(self.win, width=w, height=h, bg=self.key,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        # 圆角矩形：用一整块多边形近似圆角（避免圆弧拼矩形留下黑角）；
        # Windows 下再用色键透明把画布底色抠掉，就只剩一块圆角底板。
        self.shape = self.canvas.create_polygon(
            self._round_rect_points(w - 1, h - 1, self.corner, 0.5),
            fill=self.bg, outline=self.border, width=self.border_w)
        self.bar_bg = self.canvas.create_line(0, 0, 0, 0, fill=self.key)
        self.bar = self.canvas.create_line(0, 0, 0, 0, fill=self.key)
        self.time_item = self.canvas.create_text(
            w / 2.0, h * 0.57, text="00:00", fill=self.fl["fg_color"],
            font=(app.ui_font, self.fl["font_size"], "bold"))
        self.label_item = self.canvas.create_text(
            w / 2.0, h * 0.19, text="距下次休息", fill=self.fl["label_color"],
            font=(app.ui_font, self.fl["label_font_size"]))

        self._place(self.fl["x"], self.fl["y"])
        self._apply_window_chrome()
        # 窗口被销毁（程序退出）时撤销自己挂的 after 回调
        self.win.bind("<Destroy>", self._on_destroy, add="+")
        # 鼠标事件双保险：
        #  - Windows 上主要靠原生 HWND 钩子（见 show() -> subclass_mouse）拖动；
        #  - 但色键透明 + WS_EX_NOACTIVATE 的窗口在某些系统上会把 WM_RBUTTONUP
        #    吞掉，导致右键菜单弹不出来。所以 Tk 事件也一并绑上，谁先到谁处理。
        #  只绑 canvas：canvas 铺满整个窗口，事件会冒泡到 win，再绑 win 会重复触发。
        for seq in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>",
                    "<Button-3>", "<Button-2>"):
            self.canvas.bind(seq, self._tk_mouse)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)
        self._drag_off = None
        self._bar_frac = None

    def _key_color(self):
        """色键色：绝不能和底板色相同，否则画布上会漏出该颜色的小洞。"""
        key = str(self.fl.get("key_color") or "#010203")
        clash = {str(self.fl["bg_color"]).lower(), str(self.fl["warn_bg"]).lower()}
        return "#f0f1f2" if key.lower() in clash else key

    def _tk_mouse(self, event):
        """Tk 鼠标事件：拖动浮窗 + 右键菜单。

        Windows 上原生钩子和 Tk 事件两条路都会到，但不会重复动作：
        - 右键：走这里（原生钩子在色键窗口上不一定能收到 WM_RBUTTONUP）；
        - 左键拖动：如果原生钩子已经在拖（self.app._native_dragging 为真），
          这里就完全不管，避免两边各算一套偏移把窗口拽飞。
        """
        if event.type == tk.EventType.ButtonPress:
            if event.num in (2, 3):
                self.app.show_menu(event.x_root, event.y_root)
                return
            if getattr(self.app, "_native_dragging", False):
                return
            self._drag_off = (event.x_root - self.pos_x, event.y_root - self.pos_y)
        elif event.type == tk.EventType.Motion:
            if getattr(self.app, "_native_dragging", False):
                return
            if self._drag_off:
                self.drag_to(event.x_root - self._drag_off[0],
                             event.y_root - self._drag_off[1])
        elif event.type == tk.EventType.ButtonRelease:
            if getattr(self.app, "_native_dragging", False):
                return
            if self._drag_off:
                self._drag_off = None
                self.app.remember_position(self.pos_x, self.pos_y)

    def _on_destroy(self, event):
        if event.widget is not self.win:
            return
        if self._blink_job is not None:
            try:
                self.win.after_cancel(self._blink_job)
            except Exception:
                pass
            self._blink_job = None
        try:
            self.app.floating = None
        except Exception:
            pass

    # ---------------------------------------------------------------- 几何

    def _place(self, x, y):
        self.pos_x, self.pos_y = int(x), int(y)
        w, h = self.fl["width"], self.fl["height"]
        self.win.geometry("%dx%d+%d+%d" % (w, h, self.pos_x, self.pos_y))

    @staticmethod
    def _round_rect_points(w, h, r, inset=0, steps=10):
        """返回圆角矩形的多边形顶点表（四个圆角各取 steps 个点近似）。

        用一整块多边形当底板，避免“弧线拼矩形”留下的黑角问题。
        """
        r = max(1.0, min(r, w / 2.0, h / 2.0))
        x0, y0, x1, y1 = inset, inset, w - inset, h - inset
        pts = []
        for cx, cy, a0 in ((x1 - r, y0 + r, 270.0), (x1 - r, y1 - r, 0.0),
                           (x0 + r, y1 - r, 90.0), (x0 + r, y0 + r, 180.0)):
            for i in range(steps + 1):
                ang = math.radians(a0 + 90.0 * i / steps)
                pts.extend((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        return pts

    def _apply_window_chrome(self):
        """平台相关的“透明 + 圆角”。

        Windows：-transparentcolor 把画布底色抠成完全透明 —— 浮窗四角（圆角外）透出桌面，
                 文字在 _restyle() 里换成正常颜色，于是只剩一块真正的圆角半透明底板。
                 需要桌面窗口管理器合成（Win7 起默认开启；Win8 后用户不能关）。
        其他平台：不支持色键透明，退化为“矩形窗口 + -alpha 整体半透明”。
        """
        if self.app.w32.ok:
            try:
                self.win.attributes("-transparentcolor", self.key)
                self.transparent = True
            except Exception as exc:
                self.transparent = False
                log("浮窗圆角透明不可用，降级为方形半透明窗口：%s" % exc)
        else:
            self.transparent = False
        self.canvas.configure(bg=self.key)
        self.win.configure(bg=self.key)

    def show(self):
        if not self.fl.get("enabled", True):
            return
        self.win.deiconify()
        self.win.update_idletasks()
        self._restyle(False)
        hwnd = self.app.w32.get_hwnd(self.win)
        if hwnd:
            self.app.w32.make_tool_window(hwnd)   # 不进任务栏 / Alt+Tab，不抢焦点
            self.app.w32.set_topmost(hwnd)
            # 用原生 HWND 挂钩子接管鼠标拖动：比 Tk 事件更稳，色键透明窗口也能收到
            self.app.w32.subclass_mouse(hwnd, self.app.on_floating_mouse)
        self.win.lift()
        if self.app.blocker is None or not self.app.blocker.active:
            try:
                self.win.attributes("-topmost", True)
            except Exception:
                pass

    # ---------------------------------------------------------------- 绘制

    def _restyle(self, warn):
        """按普通 / 预警两种状态重画底板、文字颜色和底部进度条。"""
        w, h = self.fl["width"], self.fl["height"]
        bg = self.fl["warn_bg"] if warn else self.fl["bg_color"]
        border = self.fl["warn_border"] if warn else self.fl["normal_border"]
        self.canvas.itemconfigure(self.shape,
                                  fill=bg, outline=border, width=self.border_w)
        self.canvas.coords(self.shape, *self._round_rect_points(w - 1, h - 1, self.corner, 0.5))
        self.canvas.tag_raise(self.bar_bg)
        self.canvas.tag_raise(self.bar)
        self.canvas.tag_raise(self.time_item)
        self.canvas.tag_raise(self.label_item)
        self.canvas.itemconfigure(self.time_item,
                                  fill=(self.fl["warn_text_color"] if warn
                                        else self.fl["fg_color"]))
        self.canvas.itemconfigure(self.label_item,
                                  fill=(self.fl["warn_text_color"] if warn
                                        else self.fl["label_color"]))
        self._draw_bar()

    def _draw_bar(self):
        """底部进度条：有效宽度比例 + 剩余比例（越短越接近休息）。"""
        w, h = self.fl["width"], self.fl["height"]
        frac = 0.0 if self._bar_frac is None else clamp(self._bar_frac, 0.0, 1.0)
        x0, x1 = 16.0, w - 16.0
        y = h - 9.0
        self.canvas.coords(self.bar_bg, x0, y, x1, y)
        self.canvas.coords(self.bar, x0, y, x0 + (x1 - x0) * frac, y)
        track = self.fl["warn_border"] if self.warn_visible else self.fl["normal_border"]
        fill = self.fl["warn_text_color"] if self.warn_visible else self.fl["fg_color"]
        self.canvas.itemconfigure(self.bar_bg, fill=track, width=3, capstyle="round")
        self.canvas.itemconfigure(self.bar, fill=fill, width=3, capstyle="round")

    def set_progress(self, frac):
        """0..1：距离下一次休息还剩多少（用于底部进度条）。"""
        frac = round(clamp(float(frac), 0.0, 1.0), 3)
        if frac != self._bar_frac:
            self._bar_frac = frac
            self._draw_bar()

    def set_time(self, remaining_text):
        if remaining_text != self._time_text:
            self._time_text = remaining_text
            self.canvas.itemconfigure(self.time_item, text=remaining_text)

    def set_warn(self, visible, text=None):
        """进入 / 退出预警态：高亮底板 + 改小字。"""
        visible = bool(visible)
        if visible != self.warn_visible:
            self.warn_visible = visible
            self.blink_on = False
            self._restyle(visible)
        if text is not None and text != self._label_text:
            self._label_text = text
            self.canvas.itemconfigure(self.label_item, text=text)
        elif not visible and self._label_text != "距下次休息":
            self._label_text = "距下次休息"
            self.canvas.itemconfigure(self.label_item, text="距下次休息")
        self._restyle(visible)

    def blink(self, on):
        """闪烁：预警期间在“高亮底板”和“普通底板”之间来回切换。"""
        if not self.warn_visible:
            return
        self.blink_on = bool(on)
        self._restyle(bool(on))

    # ---------------------------------------------------------------- 交互

    def drag_to(self, x, y):
        """把浮窗移动到屏幕坐标 (x, y)，并限制在可见范围内。"""
        w, h = self.fl["width"], self.fl["height"]
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = clamp(int(x), -w + 40, sw - 40)
        y = clamp(int(y), 0, sh - 40)
        if (x, y) != (self.pos_x, self.pos_y):
            self._place(x, y)
            if self.app.w32.ok:
                self.app.w32.set_topmost(self.app.w32.get_hwnd(self.win))



# =============================================================================
# 7. 主程序：调度循环 / 状态机
# =============================================================================

class EyeGuardApp(object):
    TICK_MS = 100            # 浮窗刷新周期（毫秒）
    CONFIG_CHECK_MS = 2000   # 配置文件热重载检查周期
    MENU_POLL_MS = 150       # 右键菜单“是否已关闭”的轮询周期

    def __init__(self, config_path, demo=False):
        self.cfg = Config(config_path)
        self.w32 = Win32()
        self.blocker = KeyboardBlocker(self.w32) if _IS_WIN else None
        self.demo = demo

        self.root = tk.Tk()
        self.root.withdraw()                 # 主窗口不显示，程序靠浮窗常驻
        self.root.title("EyeGuard · 护眼提醒")
        self.ui_font = self._pick_font()

        self.floating = None
        self.reminder = None                 # 当前打开的全屏提醒
        # 原生窗口钩子是否正在处理左键拖动（用来让 Tk 的 <B1-Motion> 让路）
        self._native_dragging = False
        self.next_due = time.monotonic() + self.cfg.data["interval_minutes"] * 60.0
        self.cycle_total = self.cfg.data["interval_minutes"] * 60.0
        self.fired_warns = set()             # 本周期已经触发过的预警点
        self.last_label = "距下次休息"
        self._blink_job = None
        self._blink_state = False
        self._menu_unpost_job = None
        self.running = True
        self._last_dir_mtime = None
        self._saved_pos = (self.cfg.data["floating"]["x"], self.cfg.data["floating"]["y"])

        self._build_menu()
        self.root.after(120, self._start_floating)
        self.root.after(self.TICK_MS, self._tick)
        self.root.after(self.CONFIG_CHECK_MS, self._config_watch)

    # ---------------------------------------------------------------- 启动

    def _pick_font(self):
        """挑一个系统中存在的字体，保证中文能正常显示。"""
        try:
            fams = set(tkfont.families(self.root))
        except Exception:
            fams = set()
        for name in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                     "Hiragino Sans GB", "Noto Sans CJK SC", "Source Han Sans SC",
                     "WenQuanYi Micro Hei", "Droid Sans Fallback", "SimHei",
                     "Arial Unicode MS"):
            if name in fams:
                return name
        return "TkDefaultFont"

    def _start_floating(self):
        fl = self.cfg.data["floating"]
        if fl.get("enabled", True):
            self.floating = FloatingWindow(self)
            self.floating.show()
            # 浮窗建好之后，把右键菜单重新挂到这个可见的窗口上
            # （菜单不能挂在被 withdraw() 的 root 上，那样弹不出来）
            self._rebuild_menu_on_floating()
        self._apply_schedule(silent=True)

    def _rebuild_menu_on_floating(self):
        """把右键菜单改挂到浮窗上。浮窗没启用就保持挂在 root（无浮窗时也点不到）。"""
        fw = self.floating
        if fw is None:
            return
        old_var = getattr(self, "autostart_var", None)
        old_state = None
        if old_var is not None:
            try:
                old_state = bool(old_var.get())
            except Exception:
                old_state = None
        self._build_menu()
        if old_state is not None and getattr(self, "autostart_var", None) is not None:
            try:
                self.autostart_var.set(old_state)
            except Exception:
                pass

    def _build_menu(self):
        # 坑：菜单的父窗口如果是被 withdraw() 隐藏的 root，tk_popup()/post()
        # 会静默失效（菜单压根不显示，也没有任何异常）。所以这里把菜单挂到
        # 真正可见的浮窗上；浮窗还没建好时先挂 root，等浮窗建好后再重建。
        parent = self.floating.win if self.floating is not None else self.root
        self.menu = tk.Menu(parent, tearoff=0)
        self.menu.add_command(label="立即休息（测试全屏提醒）", command=self.trigger_reminder)
        self.menu.add_command(label="从 5 秒后开始提醒（测试预警）",
                              command=lambda: self._force_warn_test())
        self.menu.add_separator()
        self.menu.add_command(label="重置计时", command=self._reset_cycle)
        self.menu.add_command(label="重新加载 config.json", command=self.reload_config)
        self.menu.add_command(label="打开配置文件夹", command=self.open_config_dir)
        if _IS_WIN:
            self.autostart_var = tk.BooleanVar(value=autostart_enabled())
            self.menu.add_checkbutton(label="开机自动启动（Windows）",
                                      variable=self.autostart_var,
                                      command=self.toggle_autostart)
        self.menu.add_separator()
        self.menu.add_command(label="退出 EyeGuard", command=self.quit)

    def toggle_autostart(self):
        want = bool(self.autostart_var.get())
        if set_autostart(want):
            log("开机自启动：%s" % ("已开启" if want else "已关闭"))
        else:
            self.autostart_var.set(not want)
            log("设置开机自启动失败")

    def popup_menu(self, event):
        self.show_menu(event.x_root, event.y_root)

    def show_menu(self, x, y):
        """弹出右键菜单（必须在 Tk 主线程执行）。

        坑：tk_popup() 内部会跑一个嵌套事件循环（等菜单关闭才返回）。
        早先版本把这段丢到工作线程里跑，结果 Tk 不是线程安全的，菜单
        根本弹不出来、线程还会挂死在那里。所以这里一律调度回主线程执行：

        - 原生窗口过程（WM_RBUTTONUP 回调）里不能直接调用，用 after(0) 排队；
        - Tk 自己的回调里已经在主线程，直接调用也没问题，统一走 after(0)
          可以保证两者行为一致，并且能把“上一次还没关的菜单”先收起来。
        """
        try:
            self.root.after(0, lambda: self._popup_now(int(x), int(y)))
        except Exception as exc:
            log("右键菜单调度失败：%s" % exc)

    def _popup_now(self, x, y):
        """真正弹菜单，一定跑在主线程。"""
        if not self.running:
            return
        try:
            # 先收掉可能还挂着的旧菜单，避免叠出两个
            try:
                self.menu.unpost()
            except Exception:
                pass
            if self._menu_unpost_job is not None:
                try:
                    self.root.after_cancel(self._menu_unpost_job)
                except Exception:
                    pass
                self._menu_unpost_job = None
            # 用 post() 而不是 tk_popup()：post() 只把菜单贴上去就立刻返回，
            # 不会开嵌套事件循环，主循环（倒计时动画）继续正常走。
            # 菜单的关闭由下面的轮询负责（点到别处 / 选了某项 / 按 Esc）。
            self.menu.post(x, y)
            self._menu_unpost_job = self.root.after(
                self.MENU_POLL_MS, self._menu_poll)
        except Exception as exc:
            log("右键菜单弹出失败：%s" % exc)

    def _menu_poll(self):
        """轮询菜单是否还开着，关了就停掉轮询。

        注意：原生弹出菜单的 winfo_ismapped() 在 Windows 上不可靠（实测菜单明明
        显示着，它却一直返回 False），所以不能用它判断菜单是否已关闭——那样会在
        菜单刚弹出时就被误判为“已关闭”，于是立刻 unpost 把菜单收掉。
        这里只定期复查：只要菜单还在，就继续保持轮询；用户点选/点外面时 Tk 会自己
        隐藏菜单，此时再把轮询任务撤掉即可。
        """
        self._menu_unpost_job = None
        if not self.running:
            return
        try:
            self._menu_unpost_job = self.root.after(
                self.MENU_POLL_MS, self._menu_poll)
        except Exception:
            self._menu_unpost_job = None

    def _menu_prepare(self):
        try:
            self.menu.unpost()
        except Exception:
            pass

    def _force_warn_test(self):
        """把下一次提醒改到 5 秒后，用来快速验证预警和全屏效果。"""
        self.next_due = time.monotonic() + 5.0
        self.fired_warns.clear()
        log("测试：5 秒后触发全屏提醒")

    # ---------------------------------------------------------------- 主循环

    def _tick(self):
        try:
            self._update()
        except Exception as exc:
            log("主循环异常：%s" % exc)
        self.root.after(self.TICK_MS, self._tick)

    def _update(self):
        now = time.monotonic()
        if self.reminder is not None:
            # 全屏提醒进行中：暂停计时显示（全屏窗口自己负责倒计时）
            return
        remaining = self.next_due - now
        if remaining <= 0:
            self.trigger_reminder()
            return
        self._update_floating(remaining)

    def _update_floating(self, remaining):
        fw = self.floating
        if fw is None:
            return
        fw.set_time(fmt_mmss(remaining))
        total = self.cycle_total or 1.0
        fw.set_progress(remaining / total)
        # ---- 提前预警：每个周期内每个预警点只触发一次 ----
        warns = self.cfg.data["warn_seconds"] if self.cfg.data["prewarn"]["enabled"] else []
        due = None
        for w in warns:                       # warns 从大到小排序
            if remaining <= w and w not in self.fired_warns:
                due = w
                break
        if due is not None:
            self.fired_warns.add(due)
            fw.set_warn(True, self._warn_text(due))
            self._start_blink()
            log("预警：%.0f 秒后触发全屏提醒（%d 秒提示）" % (remaining, due))
        elif self.fired_warns and warns and remaining > warns[0]:
            # 计时被重置或预警点被调大后，退出预警态
            fw.set_warn(False)
            self._stop_blink()

    def _warn_text(self, seconds):
        pw = self.cfg.data["prewarn"]
        tmpl = pw["urgent_text_template"] if seconds <= 5 else pw["text_template"]
        try:
            return tmpl.format(seconds=seconds)
        except Exception:
            return "%d 秒后该看外面啦" % seconds

    def _start_blink(self):
        if self._blink_job is not None:
            return
        self._blink_state = True
        self._blink_loop()

    def _stop_blink(self):
        """停止闪烁，并让浮窗定格在“高亮”态（退出预警时由 set_warn(False) 复原）。"""
        if self._blink_job is not None:
            try:
                self.root.after_cancel(self._blink_job)
            except Exception:
                pass
            self._blink_job = None
        if self.floating:
            self.floating.blink(True)

    def _blink_loop(self):
        fw = self.floating
        if fw is None or not fw.warn_visible:
            self._blink_job = None
            return
        self._blink_state = not self._blink_state
        fw.blink(self._blink_state)
        self._blink_job = self.root.after(int(self.cfg.data["floating"]["blink_interval_ms"]),
                                          self._blink_loop)

    # ---------------------------------------------------------------- 触发提醒

    def trigger_reminder(self):
        if self.reminder is not None:
            return
        cfg = self.cfg.data
        minutes = cfg["interval_minutes"]
        tmpl = random.choice(cfg["reminder_messages"])
        try:
            text = tmpl.format(minutes=("%g" % minutes), seconds=int(minutes * 60))
        except Exception:
            text = tmpl
        seconds = cfg["fullscreen_countdown_seconds"]
        log("触发全屏提醒：玩了 %g 分钟，倒计时 %d 秒" % (minutes, seconds))
        if self.floating:
            self.floating.set_warn(False)
        self._stop_blink()
        self.reminder = FullscreenReminder(self, text, seconds)

    # ---------------------------------------------------------------- 事件回调

    def notify(self, event, payload=None):
        if event == "fullscreen_open":
            self._stop_blink()
        elif event == "fullscreen_closed":
            self.reminder = None
            self._reset_cycle()
            log("提醒结束，重新开始计时")

    def _reset_cycle(self):
        cfg = self.cfg.data
        self.cycle_total = cfg["interval_minutes"] * 60.0
        self.next_due = time.monotonic() + self.cycle_total
        self.fired_warns.clear()
        self._stop_blink()
        if self.floating:
            self.floating.set_warn(False)
            self.floating.set_time(fmt_mmss(self.cycle_total))
            self.floating.set_progress(1.0)

    def _apply_schedule(self, silent=False):
        """配置变了：按新间隔重排下一次提醒（保留已用掉的比例感更麻烦，直接重置）。"""
        self._reset_cycle()
        if not silent:
            log("已按新配置重置计时：%g 分钟" % self.cfg.data["interval_minutes"])

    # ---------------------------------------------------------------- 配置热重载

    def _config_watch(self):
        try:
            if self.cfg.maybe_reload():
                self._apply_schedule()
                if self.floating:
                    self.floating.fl = self.cfg.data["floating"]
                    try:
                        self.floating.win.attributes("-alpha", self.cfg.data["floating"]["alpha"])
                    except Exception:
                        pass
                    if self.floating.warn_visible:
                        self.floating._restyle(True)
                    else:
                        self.floating._restyle(False)
        except Exception as exc:
            log("配置热重载失败：%s" % exc)
        self.root.after(self.CONFIG_CHECK_MS, self._config_watch)

    def reload_config(self):
        try:
            self.cfg.load_or_create()
            self._apply_schedule()
            log("手动重新加载配置完成")
        except Exception as exc:
            log("重新加载失败：%s" % exc)

    def open_config_dir(self):
        try:
            if _IS_WIN:
                os.startfile(APP_DIR)  # type: ignore[attr-defined]
            elif _IS_MAC:
                os.system('open "%s"' % APP_DIR)
            else:
                os.system('xdg-open "%s" >/dev/null 2>&1 &' % APP_DIR)
        except Exception as exc:
            log("打开目录失败：%s" % exc)

    # ---------------------------------------------------------------- 浮窗拖动回调

    def on_floating_mouse(self, action, x, y, offset=None):
        """来自 Win32.subclass_mouse 的鼠标消息（在 UI 线程）。"""
        fw = self.floating
        if fw is None:
            return None
        if action == "drag_start":
            # 标记“原生钩子正在拖”，让 Tk 的 <B1-Motion> 别再插一脚
            self._native_dragging = True
            return (x - fw.pos_x, y - fw.pos_y)
        if action == "drag_move" and offset:
            fw.drag_to(x - offset[0], y - offset[1])
        elif action == "drag_end":
            self._native_dragging = False
            self.remember_position(fw.pos_x, fw.pos_y)
        elif action == "menu":
            self.show_menu(x, y)
        return None

    def remember_position(self, x, y):
        """浮窗被拖动后把位置写回 config.json，下次启动从原地开始。"""
        x, y = int(x), int(y)
        if self._saved_pos == (x, y):
            return
        self._saved_pos = (x, y)
        fl = self.cfg.data["floating"]
        raw = self._read_raw_config()
        if isinstance(raw, dict) and isinstance(raw.get("floating"), dict):
            # 只改文件里的 x / y，保留用户在文件里写的其他字段和注释式排版
            raw["floating"]["x"], raw["floating"]["y"] = x, y
        else:
            raw = self.cfg.data
            raw["floating"]["x"], raw["floating"]["y"] = x, y
        try:
            self.cfg.save(raw)
            self.cfg._mtime = os.path.getmtime(self.cfg.path)
        except Exception as exc:
            log("保存浮窗位置失败：%s" % exc)

    def _read_raw_config(self):
        try:
            with open(self.cfg.path, "r", encoding="utf-8-sig") as f:
                return json.load(f, object_pairs_hook=OrderedDict)
        except Exception:
            return None


    # ---------------------------------------------------------------- 退出

    def quit(self, *_):
        self.running = False
        if self._menu_unpost_job is not None:
            try:
                self.root.after_cancel(self._menu_unpost_job)
            except Exception:
                pass
            self._menu_unpost_job = None
        try:
            if self.blocker:
                self.blocker.active = False
                self.blocker.uninstall()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# =============================================================================
# 8. 入口
# =============================================================================

def enable_dpi_awareness():
    """Windows 高分屏：按物理像素渲染 + 全屏窗口才能真正贴边。"""
    if not _IS_WIN:
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)    # 每显示器 DPI 感知
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception as exc:
        log("DPI 感知设置失败（界面可能略微模糊）：%s" % exc)


def single_instance_lock():
    """Windows 下禁止开多个实例（多个实例会弹多个全屏窗）。

    返回 (True, handle) 表示拿到锁；返回 (False, handle) 表示已有实例在跑。
    """
    if not _IS_WIN:
        return True, None
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        h = k.CreateMutexW(None, False, "Global\\EyeGuard_SingleInstance_Mutex")
        if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
            return False, h
        return True, h
    except Exception:
        return True, None


def _windows_message_box(text, title="EyeGuard"):
    """最朴素的消息框（Windows API 直接弹，不依赖 tk）。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, str(text), str(title), 0x40)  # MB_ICONINFORMATION
        return True
    except Exception:
        return False


# ---- 开机自启动（只写当前用户，不碰注册表，安全可控） ----------------------

def _autostart_cmd():
    """自启动项里要执行的命令行（打包版用 exe 路径，源码版用 pythonw + main.py）。"""
    if FROZEN:
        exe = os.path.abspath(sys.executable)
        return '"%s"' % exe
    script = os.path.abspath(__file__)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pyw):
        pyw = sys.executable
    return '"%s" "%s"' % (pyw, script)


def _startup_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def _startup_lnk():
    return os.path.join(_startup_dir(), "EyeGuard.lnk")


def autostart_enabled():
    if not _IS_WIN:
        return False
    lnk = _startup_lnk()
    if os.path.exists(lnk):
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, "EyeGuard")
            return True
    except Exception:
        return False


def set_autostart(enable):
    """把/移除快捷方式放进“启动”文件夹。返回是否成功。"""
    if not _IS_WIN:
        return False
    lnk = _startup_lnk()
    try:
        if not enable:
            if os.path.exists(lnk):
                os.remove(lnk)
            try:                      # 连带清掉可能存在的注册表 Run 项
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                    winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, "EyeGuard")
            except Exception:
                pass
            return True

        os.makedirs(_startup_dir(), exist_ok=True)
        exe = os.path.abspath(sys.executable)
        target = exe
        arguments = ""
        icon = exe
        if not FROZEN:
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            target = pyw if os.path.isfile(pyw) else exe
            arguments = '"%s"' % os.path.abspath(__file__)
            icon = target
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
            "$s.TargetPath = '%s';"
            "$s.Arguments = '%s';"
            "$s.WorkingDirectory = '%s';"
            "$s.IconLocation = '%s,0';"
            "$s.Description = 'EyeGuard 护眼提醒';"
            "$s.Save()"
        ) % (lnk.replace("'", "''"), target.replace("'", "''"),
             arguments.replace("'", "''"), APP_DIR.replace("'", "''"),
             icon.replace("'", "''"))
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", script],
                       check=False, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if os.path.exists(lnk):
            return True
        # PowerShell 不可用时退回注册表 Run 项
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "EyeGuard", 0, winreg.REG_SZ, _autostart_cmd())
        return True
    except Exception as exc:
        log("设置开机自启动失败：%s" % exc)
        return False


def frozen_gui_error(text):
    """打包成无控制台的 exe 时，错误必须弹窗，否则用户什么都看不到。"""
    if not FROZEN:
        return False
    return _windows_message_box(text, "EyeGuard 出错了")


def main(argv=None):
    parser = argparse.ArgumentParser(description="EyeGuard —— 强制休息护眼提醒")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                        help="配置文件路径（默认：与程序同目录的 config.json）")
    parser.add_argument("--demo", action="store_true",
                        help="启动后立刻弹一次全屏提醒，便于测试")
    parser.add_argument("--allow-multi", action="store_true", help="允许运行多个实例")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 8):
        msg = "需要 Python 3.8 或更高版本，当前为 %s" % platform.python_version()
        if not frozen_gui_error(msg):
            sys.stderr.write(msg + "\n")
        return 1

    enable_dpi_awareness()
    if _IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EyeGuard.RestReminder")
        except Exception:
            pass
        if not args.allow_multi:
            ok, _handle = single_instance_lock()
            if not ok:
                log("已经有了一个 EyeGuard 在运行")
                if FROZEN:
                    # 双击 exe 再开一次：提示一下，别让人以为程序没启动
                    _windows_message_box(
                        "EyeGuard 已经在运行了。\n\n"
                        "它就在屏幕角落的那个小浮窗里（右键可以退出）。\n"
                        "如果你想再开一个，请用命令行加 --allow-multi。",
                        "EyeGuard 已在运行")
                return 0

    log("EyeGuard 启动：%s / %s" % (
        "打包版" if FROZEN else "Python %s" % platform.python_version(),
        platform.platform()))
    if _IS_MAC:
        log("macOS：只能在本程序窗口内吞掉关闭/快捷键；系统级 Cmd+Tab、Mission Control 无法拦截。")
    elif _IS_LINUX:
        log("Linux：全屏置顶与抢焦点可用；系统快捷键取决于窗口管理器，可能无法拦截。")

    try:
        app = EyeGuardApp(args.config, demo=args.demo)
    except Exception as exc:
        import traceback
        log("启动失败：%s\n%s" % (exc, traceback.format_exc()))
        if frozen_gui_error("EyeGuard 启动失败：\n\n%s" % exc):
            return 1
        raise

    if args.demo:
        app.root.after(600, app.trigger_reminder)

    def _signal(signum, frame):
        app.quit()

    try:
        import signal
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, _signal)
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, _signal)
    except Exception:
        pass

    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
