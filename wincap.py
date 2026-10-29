# -*- coding: utf-8 -*-
"""窗口定位 / 遮挡检测 / 客户区抓帧。

只依赖 ctypes，不需要 pywin32。关键点：
  1. 微信 4.x 的小程序跑在 WeChatAppEx.exe 里，窗口类是 Chrome_WidgetWin_0，
     同一个进程会有一堆 top-level 窗口，必须按"类名 + 标题 + 面积"筛。
  2. 这种 Chromium 窗口 PrintWindow 抓出来是全黑的（实测），所以走屏幕 BitBlt。
  3. 屏幕 BitBlt 只能拿到"看得见"的像素，窗口被遮挡时必须先激活，否则会把
     别的窗口画面当成小程序页面（这是最坑的误判来源）。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as wt

import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
GA_ROOT = 2
SW_RESTORE = 9
WS_EX_TOOLWINDOW = 0x00000080


def set_dpi_aware() -> None:
    """必须在任何窗口操作之前调用，否则 414x780 会被 DPI 缩放成别的数。"""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


# ---------------------------------------------------------------- 查询
def _title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _cls(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def root_of(hwnd) -> int:
    return user32.GetAncestor(hwnd, GA_ROOT) or hwnd


def client_box(hwnd):
    """客户区在屏幕上的 (x, y, w, h)，物理像素。"""
    r = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right, r.bottom


def list_windows(class_name: str = "Chrome_WidgetWin_0"):
    """列出所有候选小程序窗口，调试 / 选标题时用。"""
    out = []
    CB = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if class_name and _cls(hwnd) != class_name:
            return True
        t = _title(hwnd)
        if not t:
            return True
        box = client_box(hwnd)
        if not box or box[2] < 200 or box[3] < 300:
            return True
        out.append((hwnd, t, box))
        return True

    user32.EnumWindows(CB(cb), 0)
    out.sort(key=lambda x: -x[2][2] * x[2][3])
    return out


def find_window(keyword: str = "", class_name: str = "Chrome_WidgetWin_0"):
    for hwnd, title, box in list_windows(class_name):
        if keyword and keyword not in title:
            continue
        if user32.IsIconic(hwnd):
            continue
        ex = user32.GetWindowLongW(hwnd, -20)
        if ex & WS_EX_TOOLWINDOW:
            continue
        return hwnd, title
    return None, ""


def is_foreground(hwnd) -> bool:
    fg = user32.GetForegroundWindow()
    return bool(fg) and root_of(fg) == root_of(hwnd)


def is_fully_visible(hwnd) -> bool:
    """9 点采样，判断本窗口是否被别的窗口盖住。"""
    box = client_box(hwnd)
    if not box:
        return False
    x, y, w, h = box
    pts = ((0.5, 0.15), (0.5, 0.50), (0.5, 0.85), (0.15, 0.50), (0.85, 0.50),
           (0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8))
    for fx, fy in pts:
        hh = user32.WindowFromPoint(wt.POINT(x + int(w * fx), y + int(h * fy)))
        if not hh or root_of(hh) != root_of(hwnd):
            return False
    return True


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def user_idle_ms() -> int:
    """距离上一次键鼠输入过了多久（毫秒）。用来判断"人是不是走开了"。"""
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0
    tick = kernel32.GetTickCount64() & 0xFFFFFFFF
    return int((tick - lii.dwTime) & 0xFFFFFFFF)


def activate(hwnd, timeout: float = 1.0) -> bool:
    """把窗口拉到前台。返回是否成功。"""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    cur_tid = kernel32.GetCurrentThreadId()
    t0 = time.time()
    while time.time() - t0 < timeout:
        if is_foreground(hwnd) and is_fully_visible(hwnd):
            return True
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = False
        try:
            if fg_tid and fg_tid != cur_tid:
                attached = bool(user32.AttachThreadInput(fg_tid, cur_tid, True))
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(fg_tid, cur_tid, False)
        time.sleep(0.05)
    return is_foreground(hwnd)


# ---------------------------------------------------------------- 抓帧
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def grab(hwnd):
    """抓客户区，返回 BGR ndarray；失败返回 None。"""
    box = client_box(hwnd)
    if not box:
        return None
    x, y, w, h = box
    if w <= 0 or h <= 0 or w > 8000 or h > 8000:
        return None
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    if not hdc_mem or not hbmp:
        return None
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY | CAPTUREBLT)
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h          # 负数 = 自上而下
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bi), 0):
            return None
        arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
        return np.ascontiguousarray(arr[:, :, :3])
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)
