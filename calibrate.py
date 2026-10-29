# -*- coding: utf-8 -*-
"""标定工具：重新抓取提示条模板（微信改版 / 换小程序后重跑一次）。

    python calibrate.py            # 只检测并画框，看看能不能认出来
    python calibrate.py --save     # 认出来后把提示条文字行写入 assets/hint_template.png
"""
from __future__ import annotations

import argparse
import os

import cv2
import numpy as np

import wincap
from detect import HintDetector, text_lines

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(APP_DIR, "debug")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="", help="窗口标题关键字")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--image", help="用现成截图代替实时抓屏")
    ap.add_argument("--roi", type=float, default=0.75)
    args = ap.parse_args()

    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            raise SystemExit(f"读不到图片: {args.image}")
    else:
        wincap.set_dpi_aware()
        hwnd, title = wincap.find_window(args.title)
        if not hwnd:
            raise SystemExit("没找到小程序窗口，先用 --list 看看标题")
        wincap.activate(hwnd)
        frame = wincap.grab(hwnd)
        print(f"窗口「{title}」 {frame.shape[1]}x{frame.shape[0]}")

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    det = HintDetector(0.0, args.roi, template_path="__none__")
    lines = text_lines(gray, args.roi)
    print(f"找到 {len(lines)} 条文字行")

    vis = frame.copy()
    best = None
    for i, (y0, y1, ink) in enumerate(lines):
        xs = np.where(ink.sum(0) > 0)[0]
        if len(xs) == 0:
            continue
        x0, x1 = int(xs.min()), int(xs.max())
        frac, mean, hit = det.score_line(ink)
        print(f"  [{i}] y={y0}-{y1} x={x0}-{x1} 高={y1-y0+1} "
              f"逐字命中={frac:.2f} 均值={mean:.2f}")
        cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 255, 0), 1)
        cv2.putText(vis, f"{i}", (x0, max(12, y0 - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        score = (frac, mean, y1 - y0)
        if best is None or score > best[0]:
            best = (score, (x0, y0, x1, y1))

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "calibrate.png")
    cv2.imwrite(out, vis)
    print(f"标注图: {out}")

    if best and args.save:
        x0, y0, x1, y1 = best[1]
        crop = frame[y0:y1 + 1, x0:x1 + 1]
        dst = os.path.join(APP_DIR, "assets", "hint_template.png")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        cv2.imwrite(dst, crop)
        print(f"模板已更新: {dst} ({crop.shape[1]}x{crop.shape[0]})，"
              f"逐字={best[0][0]:.2f}")
    elif not best:
        print("没找到可用文字行——先让提示条出现在画面上再跑一次")


if __name__ == "__main__":
    main()
