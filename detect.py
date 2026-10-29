# -*- coding: utf-8 -*-
"""逐字识别底部提示条「上滑继续播放剧集」。

为什么不用整行模板：整行相关对"旁边多一个图标"零容忍——实测同一句提示，
广告态多一个左侧图标后，文字框从 126px 变 145px，相关度从 1.000 掉到 0.174，
直接失效。所以改成逐字：

  1) 定位：窗口下方找"整行中位灰度低"的深色带（提示条就在这儿）；
  2) 分行：带内按亮像素的横向游程切成文字行，广告条和提示条各自成行；
  3) 切字：行内按列投影切成单个字形；
  4) 认字：每个字形归一化到 24x20 后与模板逐字比对，按从左到右顺序计票。

只有命中足够多的字才算数（默认 8 个字里中 6 个且平均分够高）。
旁边多图标、多文字、字号略变都不影响——认的是字，不是那一条像素。
"""
from __future__ import annotations

import base64
import os
import sys

import cv2
import numpy as np

GLYPH_W, GLYPH_H = 24, 20

# 提示条文字行的灰度截图（126x12），calibrate.py 可覆盖
DEFAULT_TEMPLATE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAH4AAAAMCAIAAAArq54VAAAHpElEQVRYCY3BrW4jSxoG4DfQUiylgb0KKNJkNYbuRWnggR1pQfUl1AVUg4UlfeiTiixzXUBdgou5YQy60bRhIi1oUiCSDc5ItmS6HudnnL9zzvNcJEmCc6XmKTpyAV/JlZnhzvoWgNScjfHOpiMXcC5Xprh+rK1vcK7ULCLNA97LlSmuH2vrG7wqNX/b19Y3+EhqFpFcwDtSczbG0aYjF3Cm1PxtX1vf4FmuTDG8p3nAB7LibIR3Dn1tfYNfpGYRyQWcy5Uprh9r6xuUmqfDfml9i3MXSZLgXKl5io5cwFfyXE2LdNgvrW+l5sl+aX2LF1KziOQCztwo8x0r6xtAVixih6mI5EKpWUT6kZjby3tyAS9ulPmOlfUNkCtTpAO8t+nIBbySmkUkF26UuU0HOLfp1shEpHnAW7Liya62vsGJrHiyq61v8IGseLKrrW/wQlY82dUrzGZYWT/SLCK5gDOl5ukYX9us6SJJEpwrNU/RkQv4U6VmEWkOzdkYzzZrcgupWURyAa9yZWa4s//7pymG9x0yEWl9ZWZY2Z9TFrHeTWZYWd/gWa7MDHfW/0Pzt31tfYOTUvO3fW19gzdkxdkITw59bX9OeYqOXCg1i0hR8Ld9bX2DD27yvG0anNwoc3v9uLS+xUey4myEdw59vcJshpX1I80ikgt4caPMbbpbk1vgRGoWkVzAGxdJkuBcqXmKjlzA3yE1T/ZL61vIikUkt5CaRSQX8KLU5mpt/UjzZL+0f/yLRSS3kJpFXCMT2IwQyQW8KLW5WlsPZYrLhw7TbIzPbDuaBzyTmkUkt1WmSAf41KGvrW8AWXE2wlubzXY8HuGNbUfzgBNZ8WRXW9/ghax4sqtXmM2wsn6kWURyAU+k5snwMBgM8KVtR/NwkSQJzpWap2O8s+1oHnAiKxaR3AK4UeY2HeBTh35pfYsjWXE2wtGhr61vZMUiklvgl1KziDQPOCMrzkb4ZdvRPAC5MsX1Y219g2e5MsXlA7kFXkjNIpILeCI1i7hGJrAZjYd9bX2DN6RmEckFnNwoc5sOth3NA4BcmRlW1jd4ISue7GrrG0BqnuyX1rc4ypWZYWX9SLOI5AJ+kZVJfqzwvbh8ILfAidQsIrmANy6SJMG5UvMUHbmAr0jNGdbkFgCkZhHJBbySmkUkF3BOapOsrW8AWbHAZjwa461DX1vf4JnUJllb3+CZrHiyq++HhYi0vjLF9WNtfYNXUrPY98PLn3Z9ZYp015ELpWYRaR5yZYp0gENfW9/gidQsIrmAX2TFYtcPr7GyvgFkxSKSW+CVrDgb4YNN3w+vsbJ+pFlEcgGvcmWKdIAvbTuah4skSXCu1DxFRy7gazfKfMfK+gZSczbGO5uOXMBvsjLJD+tbHMmKRSS3ACA1Z+NtR/OAt2Rlkh/WtziSFU92tfUNAFmxiOQWeCtXpkgHOPT9Lk3H+NShX1rf4oXUnI3x5NAvrW9zZWa4s76Vmif7pfUtXsmKRSS3ACA1T/ZL61sc5crMsLJ+pFlEcgGvcmWKywdyC5xIzSKSC3jjIkkSnCs1T9GRC/g7pGYRyQW8kppFJBfwLFemSAc4OfT1/bAQkdwCsjLJbpemY+DQL61v8SRXpkgHODn0tfWNrDhDR/OtMjPcWd/inKxYxA5TEckF5MrMcGd9C5SaRaR5AHJlZrizvsWzG2VuL+/JBeTKzHBnfYtcmWJ4X+8mxfCe5gFnZMVi1w/TdIDfNmtaX5kZVtaPNItILuBVrkyRDvAnNmu6SJIE50rNU3TkAr5Wav62r61vIDWLSC7gldQsIrmAz8mKRaT1lZlhZX9OWUSaQ/Nkv7S+xQdSczbGZ7YdzQOeSc0ikgvIlSnSAT449EvrWzwrNX/b19Y3kJpFJBdwJDVnYxz6pfUtzuTKzPDweD29vCcXcJQrU1w+0PrKzLCyfqRZRHIBn8uVmWFlfYO3LpIkwblS8xQduYAvyYonu9r6BpCaszHe2XTkAj4nKxa7fjj8w84DSs0i0jzgvVyZIh0A247mASey4snlYYDH2voG70jNIpILyJWZ4c76Fig1i0jzAOTKzHBnfYsnuTIzrKxvAKlZRHIBwI0yt+kAm45cwDmpWcTlfnJ7eU8u4ChXprh8ILfAidQsIrmAk1LzdIy/cujriyRJcK7UPEVHLuArUvNkv7S+BSA1i0gu4JXULCK5gHO5MkU6ALZdh0xEcgt8JVemSNEvrW/xrNQ8HW/W5BbAjTK3Kfra+ga/Sc0ikgvIlSnSAT449EvrW/xyo8zt9ePS+ha4Ueb28p4cKs5G2KxpfWWKdLBZk1vgWalZRPqRmNt0gN82a3ILnEjNIpILeEdqzsbY9P3wGveP11k62HTkAp5d/Ps//y3SAf7StqN5AJArU1w/1tY3OJKaRSQXAJSap2McbTuaB7zIlSlS9EvrWxzJirMRPrHtaB7wTql5Osa2o3nAGVlxho7mAYCsOBsBh762vkGuzAx31rc4kyszw531LY5kxSKSg+bpGMCh73dpOj70tfUNnkjN2Xjb0TwAkJVJflgPZW4v78kFHOXKFJcPtL4yRTrA0aGvrW/wi6w4G+Fk05ELQK7MDCvrG0BqzsY4OfT/Bya7GJ0I3X9eAAAAAElFTkSuQmCC"


def _asset_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


# ------------------------------------------------------------------ 基础
def _row_runs(mask: np.ndarray, gap: int = 2):
    rr = mask.sum(1) > 0
    out, s = [], None
    for i, v in enumerate(rr):
        if v and s is None:
            s = i
        if not v and s is not None:
            out.append((s, i - 1))
            s = None
    if s is not None:
        out.append((s, len(rr) - 1))
    return out


def _cells(mask: np.ndarray, gap: int = 2, min_w: int = 3):
    """行内按列投影切字形，返回 [(字形掩码, x0, x1)]。"""
    idx = np.where(mask.sum(0) > 0)[0]
    if len(idx) == 0:
        return []
    runs, s, p = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - p > gap:
            runs.append((s, p))
            s = i
        p = i
    runs.append((s, p))
    out = []
    for a, b in runs:
        if b - a + 1 < min_w:
            continue
        sub = mask[:, a:b + 1]
        rows = np.where(sub.sum(1) > 0)[0]
        if len(rows) == 0:
            continue
        out.append((sub[rows.min():rows.max() + 1, :], a, b))
    return out


def _norm(mask: np.ndarray):
    """字形归一化：按高度缩放、水平居中到固定画布，再做零均值单位化。"""
    h, w = mask.shape
    if h < 3 or w < 2:
        return None
    w2 = max(2, min(GLYPH_W, int(round(w * GLYPH_H / float(h)))))
    r = cv2.resize(mask.astype(np.uint8) * 255, (w2, GLYPH_H),
                   interpolation=cv2.INTER_AREA).astype(np.float32)
    canvas = np.zeros((GLYPH_H, GLYPH_W), np.float32)
    x0 = (GLYPH_W - w2) // 2
    canvas[:, x0:x0 + w2] = r
    canvas -= canvas.mean()
    n = float(np.linalg.norm(canvas))
    return canvas / n if n > 1e-6 else None


def _ink_of_line(gray_line: np.ndarray) -> np.ndarray:
    """单行文字图 → 墨迹掩码（比背景亮的部分）。"""
    g = gray_line.astype(np.float32)
    thr = float(g.mean() + 0.6 * (g.max() - g.mean()))
    return (g > thr).astype(np.uint8)


def bands(gray: np.ndarray, roi_top: float = 0.75):
    """窗口下方找深色带（提示条所在的底色）。"""
    h, w = gray.shape
    y0 = int(h * roi_top)
    if h - y0 < 20:
        return []
    dark = np.median(gray[y0:], axis=1) < 40
    out, s = [], None
    for i, v in enumerate(dark):
        if v and s is None:
            s = i
        if not v and s is not None:
            out.append((s + y0, i - 1 + y0))
            s = None
    if s is not None:
        out.append((s + y0, h - 1))
    return [b for b in out if 20 <= b[1] - b[0] + 1 <= 0.30 * h]


def text_lines(gray: np.ndarray, roi_top: float = 0.75):
    """返回 [(y0, y1, ink_mask)]：带内的每一条文字行（全局坐标）。"""
    out = []
    for a, b in bands(gray, roi_top):
        strip = gray[a:b + 1, :].astype(np.float32)
        bg = float(np.median(strip))
        p = float(np.percentile(strip, 99.5))
        thr = bg + max(45.0, 0.55 * (p - bg))
        m = (strip > thr).astype(np.uint8)
        for r0, r1 in _row_runs(m):
            if r1 - r0 + 1 < 6:
                continue
            out.append((r0 + a, r1 + a, m[r0:r1 + 1, :]))
    return out


# ------------------------------------------------------------------ 弹窗
def find_dialog(frame):
    """识别"当前小程序不支持拖入文件"这类弹窗的绿色确定按钮。"""
    if frame is None:
        return None
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (35, 110, 110), (85, 255, 255))
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < 2500:
            continue
        cx, cy = cent[i]
        bw_, bh_ = int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT])
        if not (0.30 * h < cy < 0.70 * h and 0.20 * w < cx < 0.80 * w):
            continue
        if not (0.20 * w < bw_ < 0.75 * w and 0.03 * h < bh_ < 0.12 * h):
            continue
        x0, y0 = max(0, int(cx) - 4 * bw_), max(0, int(cy) - 3 * bh_)
        x1, y1 = min(w, int(cx) + 4 * bw_), min(h, int(cy) + 3 * bh_)
        if frame[y0:y1, x0:x1].mean() < 120:
            continue
        if best is None or area > best[0]:
            best = (area, int(cx), int(cy))
    return (best[1], best[2]) if best else None


# ------------------------------------------------------------------ 检测器
class HintDetector:
    def __init__(self, threshold: float = 0.7, roi_top: float = 0.75,
                 template_path=None, glyph_thr: float = 0.5, min_mean: float = 0.55):
        self.threshold = threshold      # 命中字数占比下限
        self.roi_top = roi_top
        self.glyph_thr = glyph_thr      # 单个字的相似度下限
        self.min_mean = min_mean        # 命中字的平均相似度下限
        self.glyphs = []
        self.template_source = "none"
        self.load_template(template_path)

    def load_template(self, path=None) -> bool:
        raw = None
        cand = path or _asset_path("hint_template.png")
        if cand and os.path.exists(cand):
            raw = cv2.imread(cand, cv2.IMREAD_GRAYSCALE)
            self.template_source = cand
        if raw is None and DEFAULT_TEMPLATE_B64.startswith("iVBOR"):
            buf = np.frombuffer(base64.b64decode(DEFAULT_TEMPLATE_B64), np.uint8)
            raw = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
            self.template_source = "embedded"
        if raw is None:
            return False
        self.glyphs = [g for g in (_norm(c[0]) for c in _cells(_ink_of_line(raw))) if g is not None]
        return len(self.glyphs) > 0

    def score_line(self, ink_mask: np.ndarray):
        """一行墨迹 → (命中率, 平均分, 命中字数)。"""
        cells = [g for g in (_norm(c[0]) for c in _cells(ink_mask)) if g is not None]
        if len(cells) < 2 or not self.glyphs:
            return 0.0, 0.0, 0
        prev, hit, scores = -1, 0, []
        for tpl in self.glyphs:
            best = (-1.0, None)
            for j, c in enumerate(cells):
                if j <= prev:
                    continue
                v = float((tpl * c).sum())
                if v > best[0]:
                    best = (v, j)
            if best[0] >= self.glyph_thr:
                prev = best[1]
                hit += 1
                scores.append(best[0])
        mean = float(np.mean(scores)) if scores else 0.0
        return hit / len(self.glyphs), mean, hit

    def detect(self, frame_bgr):
        """返回 (是否命中, 命中率, 文字行框或 None)。"""
        if frame_bgr is None:
            return False, 0.0, None
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) \
            if frame_bgr.ndim == 3 else frame_bgr
        best = (0.0, 0.0, None)
        for y0, y1, ink in text_lines(gray, self.roi_top):
            frac, mean, _hit = self.score_line(ink)
            if (frac, mean) > (best[0], best[1]):
                best = (frac, mean, (0, y0, gray.shape[1], y1))
        frac, mean, box = best
        ok = frac >= self.threshold and mean >= self.min_mean
        return ok, frac, box
