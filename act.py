# -*- coding: utf-8 -*-
"""输入注入：按住向上拖动。

微信小程序的短剧页是"上滑"手势翻下一集，鼠标滚轮不触发（实测），
所以必须用 SendInput 合成一次真实的按下→移动→抬起。
要点：
  * Chromium 只认真实输入事件，PostMessage(WM_MOUSEWHEEL) 会被丢掉；
  * 必须在按下和抬起之间插入足够多的中间移动点，一次性跳跃不会被识别成手势；
  * 用绝对坐标 + VIRTUALDESK，多屏/负坐标都能落到正确位置。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as wt

user32 = ctypes.windll.user32

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def _send(*flags_and_pos):
    """flags_and_pos: (flags, x, y) 三元组列表。"""
    n = len(flags_and_pos)
    arr = (INPUT * n)()
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), 2)
    vh = max(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN), 2)
    for i, (flags, x, y) in enumerate(flags_and_pos):
        arr[i].type = 0  # INPUT_MOUSE
        arr[i].mi.dx = int(round((x - vx) * 65535.0 / (vw - 1)))
        arr[i].mi.dy = int(round((y - vy) * 65535.0 / (vh - 1)))
        arr[i].mi.dwFlags = flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    sent = user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))
    return sent == n


def cursor_pos():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def move_to(x, y) -> bool:
    return _send((MOUSEEVENTF_MOVE, int(x), int(y)))


def drag_up(box, start_rel=(0.5, 0.72), end_rel=(0.5, 0.26),
            steps: int = 18, duration_ms: int = 320, restore_cursor: bool = True) -> bool:
    """在客户区 box 内从 start_rel 拖到 end_rel（相对比例坐标）。

    steps 越多越像真人手势；duration_ms 是整个拖动时长。
    返回是否成功注入。
    """
    bx, by, bw, bh = box
    x0 = bx + int(bw * start_rel[0])
    y0 = by + int(bh * start_rel[1])
    x1 = bx + int(bw * end_rel[0])
    y1 = by + int(bh * end_rel[1])
    old = cursor_pos() if restore_cursor else None
    step_dt = max(duration_ms, 60) / 1000.0 / max(steps, 2)

    ok = move_to(x0, y0)
    time.sleep(0.06)
    ok &= _send((MOUSEEVENTF_LEFTDOWN, x0, y0))
    time.sleep(0.04)
    # 先走 3px 破除 Chromium 的手势/点击判定阈值
    ok &= move_to(x0, y0 - 3)
    time.sleep(0.012)

    for i in range(1, steps + 1):
        t = i / steps
        ease = t * t * (3 - 2 * t)            # smoothstep，起手快收尾柔
        ok &= move_to(x0 + (x1 - x0) * ease, y0 + (y1 - y0) * ease)
        time.sleep(step_dt)

    time.sleep(0.02)
    ok &= _send((MOUSEEVENTF_LEFTUP, x1, y1))
    if restore_cursor and old:
        time.sleep(0.03)
        move_to(*old)
    return bool(ok)
