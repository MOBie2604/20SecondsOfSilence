# -*- coding: utf-8 -*-
"""开发期冒烟测试：配置生成/校验、键盘屏蔽规则、真实 tk 窗口全流程（无需第三方库）。

用法：
    python _smoke_test.py

会自动开浮窗 → 预警 → 全屏提醒 → 自动关闭，全程约 15 秒，最后一个窗口关掉后自动退出。
截图（需要 Pillow，装了才会存）放在 _smoke_tmp/ 下，跑完可以自己删。
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SANDBOX = os.path.join(HERE, "_smoke_tmp")
if os.path.isdir(SANDBOX):
    shutil.rmtree(SANDBOX, ignore_errors=True)
os.makedirs(SANDBOX, exist_ok=True)
CFG = os.path.join(SANDBOX, "config.json")

import main as M  # noqa: E402

M.LOG_PATH = os.path.join(SANDBOX, "20SecondsOfSilence.log")

ok = True


def check(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (("  -> " + str(extra)) if extra else ""))
    ok = ok and bool(cond)


# ---- 1. 配置：不存在时自动生成 ----
cfg = M.Config(CFG)
check("config auto-created", os.path.exists(CFG))
raw = json.load(open(CFG, encoding="utf-8"))
check("default interval_minutes=20", raw["interval_minutes"] == 20)
check("default fullscreen_countdown_seconds=25", raw["fullscreen_countdown_seconds"] == 25)
check("default warn_seconds=[30,5]", raw["warn_seconds"] == [30, 5])
check("block_task_switch_keys default True", raw["fullscreen"]["block_task_switch_keys"] is True)

# ---- 2. 配置：小数间隔 + 缺项补全 + 非法值 ----
json.dump({"interval_minutes": 0.5, "floating": {"alpha": 7, "width": "abc"},
           "fullscreen": {"circle_color": "#ff0000"}}, open(CFG, "w", encoding="utf-8"),
          ensure_ascii=False)
cfg2 = M.Config(CFG)
check("fractional interval kept", cfg2.data["interval_minutes"] == 0.5, cfg2.data["interval_minutes"])
check("alpha clamped to 1.0", cfg2.data["floating"]["alpha"] == 1.0, cfg2.data["floating"]["alpha"])
check("bad width falls back to 220", cfg2.data["floating"]["width"] == 220)
check("missing key restored", cfg2.data["fullscreen"]["circle_width"] == 14)
check("user color kept", cfg2.data["fullscreen"]["circle_color"] == "#ff0000")
raw2 = json.load(open(CFG, encoding="utf-8"))
check("missing keys written back", "reminder_messages" in raw2 and "prewarn" in raw2)

# ---- 3. fmt_mmss ----
check("fmt 1259 -> 20:59", M.fmt_mmss(1259) == "20:59", M.fmt_mmss(1259))
check("fmt -3 -> 00:00", M.fmt_mmss(-3) == "00:00")
check("fmt 0.2 -> 00:01", M.fmt_mmss(0.2) == "00:01", M.fmt_mmss(0.2))

# ---- 4. 键盘屏蔽规则（不依赖真实钩子，直接调 _should_block） ----
w32 = M.Win32()
check("Win32 available on Windows", w32.ok or not sys.platform.startswith("win"))
kb = M.KeyboardBlocker(w32)
kb.active = True
check("Win key blocked", kb._should_block(0x5B))
check("RWin key blocked", kb._should_block(0x5C))
check("Esc is swallowed (no Alt held => Tab/Esc rule)", kb._should_block(0x1B))
kb.active = False
check("inactive => nothing blocked", not kb._should_block(0x5B))

# ---- 5. tk 真实窗口：浮窗 + 全屏提醒全流程 ----
M.enable_dpi_awareness()
root = M.tk.Tk()
root.withdraw()
app = M.SecondsOfSilenceApp(CFG)
app.root.destroy()
app.root = root
app._build_menu()
app.ui_font = app._pick_font()
cfg3 = app.cfg.data
cfg3["fullscreen_countdown_seconds"] = 6
cfg3["floating"]["x"] = 80
cfg3["floating"]["y"] = 80

try:
    from PIL import ImageGrab
    HAS_PIL = True
except Exception:
    HAS_PIL = False


def shot(widget, name):
    """截取窗口实际像素（Pillow 可选，没有就跳过）。"""
    if not HAS_PIL:
        return
    try:
        widget.update_idletasks()
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        w, h = widget.winfo_width(), widget.winfo_height()
        ImageGrab.grab(bbox=(x - 6, y - 6, x + w + 6, y + h + 6),
                       all_screens=True).save(os.path.join(SANDBOX, name))
        print("shot:", name)
    except Exception as exc:
        print("shot failed:", exc)


def step1():
    app._start_floating()
    app.floating.set_time("20:00")
    root.update()
    print("float:", app.floating.win.winfo_width(), "x", app.floating.win.winfo_height())
    shot(app.floating.win, "float_normal.png")
    app.floating.set_warn(True, "30 秒后该看外面啦")
    app.floating.blink(True)
    root.update()
    root.after(400, step2)


def step2():
    shot(app.floating.win, "float_warn.png")
    app.trigger_reminder()
    root.after(1500, step3)


def step3():
    win = getattr(app.reminder, "win", None)
    if win is not None:
        shot(win, "fullscreen.png")
    root.after(6500, step4)


def step4():
    check("fullscreen auto-closed", app.reminder is None)
    check("timer reset after close", app.next_due - time.monotonic() > 10)
    app.quit()


root.after(400, step1)
root.after(20000, lambda: (print("TIMEOUT"), root.destroy()))
root.mainloop()
print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
