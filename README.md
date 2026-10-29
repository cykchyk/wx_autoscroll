# wx_autoscroll

**微信 PC 端小程序短剧：广告挡屏时自动上滑，把广告划走。**

[![license](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg)]()
[![python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)]()

小程序短剧在剧集之间会插一段全屏广告，广告不会自己关，底部只有一行
「上滑继续播放剧集 ↑」。手动滑一下广告就没了，接着自动播下一集；
不滑就一直卡在那儿。

这个工具做的事就一件：**看见那行字，就替你滑一下**。滑完不再补刀——
广告关掉后小程序自己会续播，多滑一次就等于跳过一整集。

```
        ( 广告 / 剧集画面 )
────────────────────────────────────
 疯狂水世界  广告      [进入小游戏]      ← 广告条，干扰项
────────────────────────────────────
         上滑继续播放剧集  ↑             ← 认这一行
────────────────────────────────────
```

## 特性

- **认字，不认像素**：把提示条切成一个个字形逐个比对，旁边多图标、多文字、字号略变都不影响
- **一次广告只划一刀**：划完进入 10 秒静默观察期，期间绝不补刀，不会跳过自动续播的下一集
- **真手势，不是滚轮**：小程序是移动端页面，滚轮不触发；用 `SendInput` 合成"按住向上拖"
- **不误伤别的窗口**：动作前校验前台状态、9 点采样确认没被遮挡、鼠标空闲才动手
- **零重依赖**：只用 OpenCV + numpy + ctypes，不装 OCR 引擎、不联网、不读内存

单帧检测 **0.8ms**，CPU 占用可以忽略。

## 快速开始

### 用打包好的 exe

1. 到 [Releases](../../releases) 下载 `wx_autoscroll.exe`
2. 双击运行，把小程序窗口留在前台
3. `F8` 暂停/继续，`F9` 退出

### 从源码运行

```bash
pip install -r requirements.txt
python main.py
```

### 命令行

```
wx_autoscroll.exe              # 开始看护
wx_autoscroll.exe --dry-run    # 只检测不操作，实时打印逐字命中率
wx_autoscroll.exe --once       # 划成功一次就退出
wx_autoscroll.exe --list       # 列出候选窗口标题
wx_autoscroll.exe --title 某剧  # 指定窗口标题关键字
```

自查有没有在干活：`--dry-run` 会打印 `命中 逐字=0.88`。正常播放时是 0.00，
提示出现会跳到 0.6 以上——一眼能分清"没认出来"和"没轮到"。

## 它是怎么判断的

整条链路分四步，都是纯 OpenCV：

| 步骤 | 做法 | 解决的问题 |
|---|---|---|
| 1 定位 | 窗口下方找"整行中位灰度 < 40"的深色带 | 提示条就长在这条带里，先把搜索范围压到 1/4 |
| 2 分行 | 带内按亮像素的横向游程切成文字行 | 广告条的文案和提示条各成一行，互不干扰 |
| 3 切字 | 行内按列投影切成单个字形 | 拿到一个个独立的字，而不是一条黑盒子 |
| 4 认字 | 每个字形归一化到 24×20，与模板逐字比对、从左到右计票 | 8 个字中命中 ≥5 个且平均分 ≥0.55 才算数 |

### 为什么不用整行模板

一开始就是整行模板匹配，然后被现实教育了：同一句提示，在广告态下左侧多出一个小图标，
文字框从 126px 变成 145px，**相关度从 1.000 直接掉到 0.174**，检测当场失效。

改成逐字后同一帧 **8/8 命中**。整行匹配对"旁边多一个像素"零容忍，逐字匹配只关心字本身。

### 为什么不用 OCR

PaddleOCR / Tesseract 确实更通用，代价是几十到上百 MB 的模型、额外运行时，以及
20~300ms 的单帧耗时。而这里的 UI 是固定的 8 个字，逐字模板在等价精度下只要 0.8ms，
且不需要联网下载模型。真换了文案，跑一次 `calibrate.py` 重新学 8 个字即可。

### 实测数据

| 场景 | 结果 |
|---|---|
| 原始画面 | 8/8，1.00 |
| 广告态（多一个图标） | 8/8，1.00 |
| 缩放 0.85× ~ 1.4× | 全部命中 |
| 抹掉提示条 / 纯视频 / 无提示 | 全部 0.00 |
| 单帧耗时 | 0.8ms |

## 为什么手势是这个形状

小程序短剧页是"上滑"手势翻页，滚轮不触发。所以用 `SendInput` 合成
`按下 → 20 段移动 → 抬起`，smoothstep 曲线，全程约 300ms。

**踩过的坑**：按在广告图片 `<img>` 上拖，Chromium 会起一次原生 HTML5 拖放，
弹出「当前小程序不支持拖入文件」把页面挡住，滑不动。所以默认从**左侧空白列 (x≈0.12)**
起手——那里不是图片元素，实测无弹窗且一次滑走。程序还会识别这个弹窗、自动点「确定」，
再换下一个起手点兜底。

## 配置

`config.json` 与 exe 同目录，不存在时用内置默认值：

| 键 | 默认 | 说明 |
|---|---|---|
| `title_keyword` | `绿泡泡短剧` | 窗口标题关键字，换小程序改这里 |
| `class_name` | `Chrome_WidgetWin_0` | 小程序窗口类名（微信 4.x 实测） |
| `poll_ms` | `100` | 轮询间隔 |
| `confirm_frames` | `3` | 连续命中多少帧才动手 |
| `score_threshold` | `0.6` | 逐字命中占比下限（8 个字中 5 个） |
| `roi_top` | `0.75` | 只在窗口下方 25% 找提示条 |
| `gestures` | 见文件 | 起手点/终点（相对比例），按顺序重试 |
| `drag_steps` / `drag_ms` | `20` / `300` | 拖拽分几段、总时长 |
| `quiet_ms` | `10000` | 划完的静默观察期，期间绝不补刀 |
| `max_retries` | `1` | 观察期满广告还在，才补划一次 |
| `backoff_ms` | `60000` | 连续失败后歇多久 |
| `activate` | `true` | 允许在用户空闲时把窗口置前 |
| `dismiss_dialog` | `true` | 自动关掉"不支持拖入文件"弹窗 |

> 跳过集了？把 `quiet_ms` 调大（比如 20000）。划不动？加大 `drag_ms` 或换 `gestures` 起手点。

## 重新标定

微信改版、换小程序、提示文案变了，会认不出来。把提示留在画面上跑一次：

```bash
python calibrate.py --save
```

它会抓当前画面、列出所有文字行的逐字命中率、把最像的那行写回
`assets/hint_template.png`，并画一张标注图到 `debug/`。

## 项目结构

```
wx_autoscroll/
├─ main.py                    状态机：待命 → 划 → 10s 静默观察 → 回待命
├─ detect.py                  逐字识别 + 弹窗识别
├─ act.py                     SendInput 合成拖拽
├─ wincap.py                  窗口定位 / 遮挡检测 / BitBlt 抓帧
├─ calibrate.py               重新标定字形模板
├─ config.json                配置
├─ assets/hint_template.png   提示条文字行模板
├─ build.bat                  一键打包 exe
└─ requirements.txt
```

## 已知限制

- **只认这一句提示**。文案换成「上滑继续观看」之类需要重新标定。
- **只测过微信 4.x + Windows 10/11**。微信 3.x 的小程序窗口类和进程名不同，需自行调整。
- **依赖窗口可见**。抓屏抓的是屏幕像素，窗口被完全遮挡时需要置前；不想被抢焦点就加
  `--no-activate`，但那样遮挡时不会动作。
- **会短暂接管鼠标**。拖拽期间别抢鼠标，动作完光标会还原。
- **缩放极端时不认**。窗口缩到 0.8 倍以下命中率会掉；正常尺寸无影响。

## FAQ

**完全没反应？**
先看同目录 `wx_autoscroll.log`。只有"锁定窗口"没有后续，说明窗口不在前台；
有"窗口不在前台"说明你正在用别的程序，它让位了。再用 `--dry-run` 看逐字分数。

**划了但没划掉？**
日志会写"补划一次"。多半是拖拽被广告位吃掉，换个起手点或加长 `drag_ms`。

**会不会误伤别的窗口？**
动作前会校验前台窗口句柄 + 9 点采样确认没被遮挡，任一不满足就跳过本轮。
`title_keyword` 不匹配的窗口根本不会被锁定。

**杀不掉 / 关了还在跑？**
PyInstaller 单文件是双进程，任务管理器里结束 `wx_autoscroll.exe` 全部实例即可。

## 开发

```bash
pip install -r requirements.txt
python main.py --dry-run      # 调检测
python main.py --debug        # 触发时保存前后帧到 debug/
python calibrate.py           # 看文字行分割效果
```

打包：

```bash
build.bat                     # 或 python -m PyInstaller ...（见文件内命令）
```

## 许可

[**The Unlicense**](LICENSE) —— 公有领域。

这份代码不保留任何版权：可以任意复制、修改、商用、闭源、再发布，
**不需要署名，也不需要保留版权声明**。比 MIT 更彻底的地方就在于少了"保留声明"这一条。

第三方依赖遵循各自协议：OpenCV（Apache-2.0）、NumPy（BSD-3-Clause）。

## 免责声明

- 与腾讯、微信无任何关联，非官方工具。
- 本工具不修改客户端、不注入进程、不拦截或篡改广告请求，只是在你本来就要手动上滑的时候
  替你完成这一次上滑动作。
- 自动化操作第三方客户端可能违反其用户协议，使用风险自负。
- 仅限个人学习与自用，请遵守当地法律法规与平台条款。

---

## English

A tiny Windows utility for WeChat PC mini-program dramas: when a full-screen ad
blocks the episode and the page shows the hint 「上滑继续播放剧集」 (swipe up to
continue), it performs exactly one swipe-up gesture, then stays quiet for 10s —
the app auto-plays the next episode by itself, so a second swipe would skip one.

- Detects the hint by **per-glyph template matching** (8 characters segmented,
  normalized, voted), not whole-line correlation — robust to extra icons.
- Injects a real drag via `SendInput` (wheel does nothing on these mobile pages).
- Guards: foreground check, 9-point occlusion test, mouse-idle check.
- Pure OpenCV + numpy + ctypes. No OCR runtime, no network, no memory reading.

Licensed under **The Unlicense** (public domain).
