# -*- coding: utf-8 -*-
"""微信小程序短剧自动上滑。

检测到页面底部出现"上滑继续播放剧集"→ 按住向上拖动 → 校验提示消失。

用法:
    python main.py                 # 自动找"绿泡泡短剧"窗口，开始看护
    python main.py --once          # 只触发一次后退出（用于验证）
    python main.py --dry-run       # 只检测不操作，打印命中分数
    python main.py --list          # 列出候选窗口标题
    python main.py --title 某剧    # 指定标题关键字
热键: F8 暂停/继续, F9 退出
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import cv2

import act
import wincap
from detect import HintDetector, find_dialog

APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "wx_autoscroll.log")

DEFAULTS = {
    "title_keyword": "绿泡泡短剧",
    "class_name": "Chrome_WidgetWin_0",
    "poll_ms": 100,
    "confirm_frames": 3,
    "score_threshold": 0.6,
    "roi_top": 0.75,
    # 起手点/终点（相对客户区比例）。顺序即重试顺序：
    # 左侧空白列最稳（不会命中广告 <img> 触发 HTML5 拖放），中间作为兜底。
    "gestures": [
        [0.12, 0.80, 0.12, 0.26],
        [0.50, 0.72, 0.50, 0.16],
        [0.88, 0.78, 0.88, 0.26],
    ],
    "drag_steps": 20,
    "drag_ms": 300,
    "quiet_ms": 10000,        # 划完之后的静默观察期：这期间绝不再划第二刀
    "cooldown_ms": 3000,      # 两次动作之间的最小间隔
    "max_retries": 1,         # 观察期满仍没划掉，才补一次
    "backoff_ms": 60000,
    "max_actions": 300,
    "activate": True,
    "restore_cursor": True,
    "dismiss_dialog": True,
}


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log(f"配置读取失败，用默认值: {e}")
    return cfg


class App:
    def __init__(self, cfg: dict, args):
        self.cfg = cfg
        self.args = args
        self.det = HintDetector(cfg["score_threshold"], cfg["roi_top"])
        self.hwnd = None
        self.title = ""
        self.state = "ARMED"
        self.hits = 0
        self.actions = 0
        self.attempt = 0
        self.last_action = 0.0
        self.last_find = 0.0
        self.backoff_until = 0.0
        self.paused = False
        self.running = True
        self.verify_hit = 0
        self.verify_miss = 0
        self.cleared_at = None
        self.quiet_until = 0.0
        self.last_cursor = None
        self.idle_since = 0.0
        self.latch_until = time.time() + 3.0
        self.debug_dir = os.path.join(APP_DIR, "debug")

    # ------------------------------------------------------------ 窗口
    def refresh_window(self, force=False):
        now = time.time()
        if not force and self.hwnd and now - self.last_find < 2.0:
            if wincap.user32.IsWindow(self.hwnd) and \
               self.cfg["title_keyword"] in wincap._title(self.hwnd):
                return True
        self.last_find = now
        hwnd, title = wincap.find_window(self.cfg["title_keyword"], self.cfg["class_name"])
        if not hwnd:
            if self.hwnd:
                log("窗口不见了，等待重新打开…")
            self.hwnd = None
            return False
        if hwnd != self.hwnd:
            log(f"锁定窗口 0x{hwnd:X} 「{title}」 {wincap.client_box(hwnd)}")
        self.hwnd, self.title = hwnd, title
        return True

    def ensure_front(self) -> bool:
        if wincap.is_foreground(self.hwnd) and wincap.is_fully_visible(self.hwnd):
            return True
        if not self.cfg["activate"]:
            return False
        # 抢焦点要克制：只有"刚看到过提示"或"人已经离开键鼠 5 秒"才把窗口拉回前台。
        # 否则用户一边打字一边被抢窗口，没法用。
        if time.time() > self.latch_until and wincap.user_idle_ms() < 5000:
            return False
        wincap.activate(self.hwnd, timeout=0.8)
        return wincap.is_foreground(self.hwnd) and wincap.is_fully_visible(self.hwnd)

    # ------------------------------------------------------------ 动作
    def click(self, x, y):
        act.move_to(x, y)
        time.sleep(0.08)
        act._send((act.MOUSEEVENTF_LEFTDOWN, x, y))
        time.sleep(0.05)
        act._send((act.MOUSEEVENTF_LEFTUP, x, y))

    def dismiss_if_dialog(self, frame) -> bool:
        """误拖到 <img> 上会弹"不支持拖入文件"，点掉它。"""
        if not self.cfg["dismiss_dialog"]:
            return False
        pos = find_dialog(frame)
        if not pos:
            return False
        box = wincap.client_box(self.hwnd)
        if not box:
            return False
        log("检测到弹窗，点“确定”关闭")
        self.click(box[0] + pos[0], box[1] + pos[1])
        time.sleep(0.6)
        return True

    def do_drag(self) -> bool:
        box = wincap.client_box(self.hwnd)
        if not box:
            return False
        gs = self.cfg["gestures"]
        g = gs[self.attempt % len(gs)]
        t0 = time.time()
        ok = act.drag_up(box, (g[0], g[1]), (g[2], g[3]),
                         steps=self.cfg["drag_steps"], duration_ms=self.cfg["drag_ms"],
                         restore_cursor=self.cfg["restore_cursor"])
        log(f"上滑 起手=({g[0]:.2f},{g[1]:.2f})→({g[2]:.2f},{g[3]:.2f}) "
            f"{'已注入' if ok else '注入失败'} {int((time.time() - t0) * 1000)}ms")
        return ok

    def save_debug(self, frame, tag: str):
        if not self.args.debug:
            return
        os.makedirs(self.debug_dir, exist_ok=True)
        path = os.path.join(self.debug_dir, time.strftime("%H%M%S") + f"_{tag}.png")
        cv2.imwrite(path, frame)
        log(f"调试帧: {path}")

    # ------------------------------------------------------------ 热键
    def poll_hotkeys(self):
        u = wincap.user32
        if u.GetAsyncKeyState(0x77) & 0x8000:      # F8
            self.paused = not self.paused
            log("已暂停" if self.paused else "继续")
            time.sleep(0.35)
        if u.GetAsyncKeyState(0x78) & 0x8000:      # F9
            log("退出")
            self.running = False

    # ------------------------------------------------------------ 主循环
    def run(self):
        log("启动。F8 暂停/继续，F9 退出。")
        log(f"模板: {self.det.template_source}（{len(self.det.glyphs)} 个字形）")
        if not self.det.glyphs:
            log("警告：没有字形模板，什么都认不出来，先跑 calibrate.py --save")
        poll = max(self.cfg["poll_ms"], 30) / 1000.0
        last_status = 0.0

        while self.running:
            self.poll_hotkeys()
            if not self.running:
                break
            if self.paused:
                time.sleep(poll)
                continue
            if not self.refresh_window():
                time.sleep(0.5)
                continue
            if time.time() < self.backoff_until:
                time.sleep(poll)
                continue
            if not self.ensure_front():
                if time.time() - last_status > 30:
                    log("窗口不在前台，等人离开键鼠后再接管…")
                    last_status = time.time()
                time.sleep(0.3)
                continue

            frame = wincap.grab(self.hwnd)
            if frame is None:
                time.sleep(poll)
                continue
            hit, score, box = self.det.detect(frame)
            if hit:
                self.latch_until = max(self.latch_until, time.time() + 5.0)

            if self.args.dry_run:
                if hit:
                    log(f"命中 逐字={score:.2f} box={box}")
                time.sleep(poll)
                continue

            if self.state == "ARMED":
                # 人在用鼠标时不动手，免得抢光标
                cur = act.cursor_pos()
                moving = self.last_cursor is not None and (
                    abs(cur[0] - self.last_cursor[0]) > 3 or abs(cur[1] - self.last_cursor[1]) > 3)
                self.last_cursor = cur
                self.idle_since = 0.0 if moving else self.idle_since + poll
                if hit:
                    self.hits += 1
                    if self.hits >= self.cfg["confirm_frames"] and \
                       self.idle_since >= 0.8 and \
                       time.time() - self.last_action > self.cfg["cooldown_ms"] / 1000.0:
                        self.save_debug(frame, "before")
                        self.do_drag()
                        self.actions += 1
                        self.last_action = time.time()
                        self.hits = 0
                        self.cleared_at = None
                        self.quiet_until = time.time() + self.cfg["quiet_ms"] / 1000.0
                        self.state = "SETTLE"
                else:
                    self.hits = 0

            elif self.state == "SETTLE":
                # 划完只观察，不再动手：广告划走后会自动播下一集，
                # 这时候看到提示再补一刀就等于跳过一整集。
                if self.dismiss_if_dialog(frame):
                    self.cleared_at = None
                    self.state, self.hits = "ARMED", 0
                    continue
                if not hit:
                    self.cleared_at = time.time()
                if time.time() >= self.quiet_until:
                    if self.cleared_at is not None:
                        log(f"广告已划走（累计 {self.actions} 次）")
                        self.state, self.attempt = "ARMED", 0
                        self.last_action = time.time()
                        if self.args.once or self.actions >= self.cfg["max_actions"]:
                            log("结束")
                            self.running = False
                    else:
                        self.attempt += 1
                        if self.attempt > self.cfg["max_retries"]:
                            log(f"划了 {self.attempt} 次广告还在，可能页面变了，"
                                f"歇 {self.cfg['backoff_ms'] // 1000}s")
                            self.backoff_until = time.time() + self.cfg["backoff_ms"] / 1000.0
                            self.attempt, self.state = 0, "ARMED"
                        else:
                            log(f"观察期结束提示仍在（逐字 {score:.2f}），补划一次")
                            self.do_drag()
                            self.last_action = time.time()
                            self.cleared_at = None
                            self.quiet_until = time.time() + self.cfg["quiet_ms"] / 1000.0

            time.sleep(poll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", help="窗口标题关键字")
    ap.add_argument("--once", action="store_true", help="成功滑一次就退出")
    ap.add_argument("--dry-run", action="store_true", help="只检测不操作")
    ap.add_argument("--debug", action="store_true", help="保存触发前后画面")
    ap.add_argument("--list", action="store_true", help="列出候选窗口")
    ap.add_argument("--no-activate", action="store_true", help="不抢前台")
    args = ap.parse_args()

    wincap.set_dpi_aware()
    if args.list:
        for hwnd, title, box in wincap.list_windows():
            print(f"0x{hwnd:X}\t{box[2]}x{box[3]}\t{title}")
        return

    cfg = load_config()
    if args.title:
        cfg["title_keyword"] = args.title
    if args.no_activate:
        cfg["activate"] = False

    App(cfg, args).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断")
