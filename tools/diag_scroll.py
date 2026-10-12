"""滚动帧率诊断 —— **在真机上跑**（offscreen 量不出真东西）。

用法（项目根目录）:
    .venv/bin/python tools/diag_scroll.py

打印四块：
1. 显示器与刷新率：**Qt 报的** vs **macOS 报的**。ProMotion 屏上这两个经常不一致
   （Qt 报的是显示模式的标称速率，常常是 60，而面板能跑 120），我们要的是后者。
2. 一段**真实滚动**驱动起来后，动画时钟的**帧间隔分布**——超目标周期 1.5 倍的
   算掉帧，直接看「能不能跟住」。
3. 单帧**整屏绘制**耗时（开/关各档装饰各量一次），看绘制占预算多少。
4. 结论行：如果 2 里掉帧多而 3 里绘制很闲，瓶颈就不在绘制（多半在输入/合成）。

不需要数据库、不写任何文件。把输出整段贴回来即可。
"""
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer       # noqa: E402
from PySide6.QtGui import QWheelEvent                        # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

app = QApplication(sys.argv)

import ui.scroll_fx as scroll_fx                             # noqa: E402
from app.types import ClipboardItem                          # noqa: E402
from ui.animations import (_mac_screen_rate, frame_interval_ms,  # noqa: E402
                           refresh_rate, refresh_rate_cache_clear)
from ui.history_view import HistoryView                      # noqa: E402

ALL = ("scrollbar", "edge_fade", "parallax", "lift", "depth")


def section(title: str) -> None:
    print(f"\n{'─' * 64}\n{title}\n{'─' * 64}")


# ── 1. 显示器与刷新率 ──────────────────────────────────────────────
section("1. 显示器与刷新率")
refresh_rate_cache_clear()   # 诊断要读当下的值，不吃 TTL 缓存（换显示器后尤其）
screen = app.primaryScreen()
print(f"  Qt  primaryScreen()      : {screen.name() if screen else '(无)'}")
print(f"  Qt  refreshRate()        : {screen.refreshRate() if screen else 0:.1f} Hz")
print(f"  macOS NSScreen           : {_mac_screen_rate():.1f} Hz  ← 我们实际采用")
print(f"  最终 refresh_rate()      : {refresh_rate():.1f} Hz")
print(f"  理想刷新周期              : {1000.0 / refresh_rate():.2f} ms")
print(f"  → frame_interval_ms()    : {frame_interval_ms()} ms"
      f"   ← 必须**小于**理想周期（宁可多画一帧，不能漏一帧）")
if frame_interval_ms() > 1000.0 / refresh_rate():
    print("  ⚠️ 间隔比屏幕周期还长：屏幕该刷新时帧还没画完 → 同一帧被显示两次")
if screen and abs(screen.refreshRate() - _mac_screen_rate()) > 1 and _mac_screen_rate() > 0:
    print("  ⚠️ 两者不一致——正是 ProMotion 上 Qt 报不准的那种情况，我们已按 macOS 的算")
print(f"  devicePixelRatio         : {screen.devicePixelRatio() if screen else 0}")

budget = 1000.0 / refresh_rate()   # 一个刷新周期 = 单帧预算（ms）

# ── 搭一个列表（文本 + 图片混合，贴近真实）─────────────────────────
view = HistoryView()
rows = []
for i in range(80):
    rows.append(ClipboardItem(type="text",
                              content=f"条目 {i}：这是一段用来占位的正文内容，长度中等"))
view.set_items(rows)
view.resize(560, 760)
view.show()
app.processEvents()
view._delegate.enter_animator.stop()
app.processEvents()

lst = view._list
fx = lst._scroll_fx
bar = lst.verticalScrollBar()
vp = lst.viewport()
print(f"  视口（逻辑）             : {vp.width()} x {vp.height()}"
      f"   物理 ≈ {int(vp.width() * vp.devicePixelRatio())} x "
      f"{int(vp.height() * vp.devicePixelRatio())}")

# ── 2. 真实滚动下的帧间隔 ─────────────────────────────────────────
section("2. 真实滚动：动画时钟的帧间隔")
bar.setValue(bar.maximum() // 2)
app.processEvents()

gaps, last = [], [None]


def _stamp() -> None:
    now = time.perf_counter()
    if last[0] is not None:
        gaps.append((now - last[0]) * 1000.0)
    last[0] = now


fx._timer.timeout.connect(_stamp)


def _wheel() -> None:
    QApplication.sendEvent(vp, QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, -960), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False))


driver = QTimer()
driver.timeout.connect(_wheel)
driver.start(16)                       # 每 16ms 送一次滚轮，模拟连续滚动
QTimer.singleShot(2500, app.quit)
app.exec()
driver.stop()

target = frame_interval_ms()
gaps = gaps[3:]
if len(gaps) >= 10:
    s = sorted(gaps)
    med = s[len(s) // 2]
    late = [g for g in s if g > target * 1.5]
    print(f"  采样 {len(s)} 帧，目标周期 {target}ms（理想 {budget:.2f}ms）")
    print(f"  中位 {med:6.2f}ms   p95 {s[int(len(s) * .95)]:6.2f}ms   max {s[-1]:6.2f}ms"
          f"   σ {statistics.pstdev(s):5.2f}ms")
    print(f"  掉帧（> {target * 1.5:.1f}ms）: {len(late)} 次"
          f"{f'，最长 {max(late):.1f}ms' if late else ' ✓'}")
    print(f"  实测帧率 ≈ {1000.0 / med:.1f} fps（屏幕 {refresh_rate():.0f}Hz）")
    if med > budget:
        print("  ⚠️ 出帧**慢于**屏幕刷新——同一帧会被显示两次，看着就是不丝滑；"
              "frame_interval_ms() 必须取整到**小于**理想周期")
else:
    print("  采样太少（窗口没真正显示？），跳过")

# ── 3. 单帧绘制耗时 ───────────────────────────────────────────────
section("3. 单帧整屏绘制耗时（当前设置 / 各档）")


def paint_ms(n: int = 50) -> tuple[float, float, float]:
    """→ (中位, p95, max)。**p95/max 才是关键**：中位再小，偶尔一帧超预算照样卡。"""
    vp.repaint()
    app.processEvents()
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        vp.grab()
        ts.append((time.perf_counter() - t) * 1000.0)
    ts.sort()
    return ts[len(ts) // 2], ts[int(len(ts) * 0.95)], ts[-1]


print(f"  （预算 = 一个刷新周期 {budget:.2f}ms；p95/max 超它就会卡一下）")
for label, effects in (
    ("全关（基准）", {}),
    ("只开景深", {"depth": True}),
    ("只开抬升", {"lift": True}),
    ("四个原始装饰", {"scrollbar": True, "edge_fade": True,
                      "parallax": True, "lift": True}),
    ("全开", dict.fromkeys(ALL, True)),
):
    scroll_fx.set_scroll_effects(dict.fromkeys(ALL, False))
    scroll_fx.set_scroll_effects(dict.fromkeys(ALL, False) | effects)
    fx.apply_settings()
    fx._timer.stop()
    fx._activity = 1.0                 # 推到「正在滚动」的样子
    fx._down = 1.0
    app.processEvents()
    med, p95, mx = paint_ms()
    flag = "  ← p95 超预算" if p95 > budget else ""
    print(f"  {label:<14} 中位 {med:6.2f}  p95 {p95:6.2f}  max {mx:6.2f}ms{flag}")

scroll_fx.set_scroll_effects(dict.fromkeys(ALL, True))
fx._activity = 0.0
fx._down = 0.0
view.close()

section("怎么读")
print("  · 2 里掉帧多、3 里绘制很闲 → 瓶颈不在绘制（看输入事件频率 / 系统合成 / 刷新率第 1 块）")
print("  · 3 里某档明显更贵 → 那一档就是元凶，可以单独关掉对比")
print("  · 1 里 Qt 与 macOS 不一致 → 就是被 Qt 报低了刷新率，本版已按 macOS 的算")
