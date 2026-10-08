"""历史列表滚动帧成本探针：直接量 delegate 绘制一帧的真实耗时。

用法：
    python tools/bench_scroll.py                        # dpr=1
    QT_SCALE_FACTOR=2 python tools/bench_scroll.py      # 模拟 Retina

对可见行做一次强制同步重绘并计时（`viewport().repaint()`），逐滚动步采样，
报告 中位 / p95 / max / 超 16.7ms 的帧数。冷（无落盘缩略图）/ 热 / 整窗 三条
路径分开量。
"""
import hashlib
import io
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image as PILImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402

app = QApplication.instance() or QApplication([])

from app.types import ClipboardItem  # noqa: E402
from database.engine import create_db_engine  # noqa: E402
from database.migrations import migrate  # noqa: E402
from services.image_service import ImageService  # noqa: E402
from ui.history_view import HistoryView  # noqa: E402

BUDGET = 16.7
SIZES = [(1280, 800), (2940, 1912), (966, 434), (828, 984), (1440, 900)]


def _make_png(w: int, h: int) -> bytes:
    """一点细密纹理，别让全平色图解码/缩放被优化掉。"""
    img = PILImage.new("RGB", (w, h), (240, 240, 245))
    px = img.load()
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            px[x, y] = ((x * 7) % 256, (y * 11) % 256, ((x + y) * 3) % 256)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _seed(root: Path, n_images: int, n_text: int):
    root.mkdir(parents=True, exist_ok=True)
    eng = create_db_engine(root / "bench.db")
    migrate(eng)
    svc = ImageService(root / "images")
    from services import history_service, session_service

    session_service.ensure_default(eng)
    items = []
    for i in range(n_images):
        item = ClipboardItem(type="image", content="")
        item.file_path = str(svc.save(_make_png(*SIZES[i % len(SIZES)])))
        item.preview = f"截屏 {i}.png"
        item.hash = hashlib.sha256(f"img{i}".encode()).hexdigest()
        items.append(item)
    for i in range(n_text):
        item = ClipboardItem(type="text", content=f"示例文本条目 {i} " * 6)
        item.hash = hashlib.sha256(f"txt{i}".encode()).hexdigest()
        items.append(item)
    for item in items:
        history_service.save_item(eng, item)
    return eng, svc, history_service.list_recent(eng)


def _report(label: str, samples: list[float]) -> None:
    p95 = (statistics.quantiles(samples, n=20)[18]
           if len(samples) > 4 else max(samples))
    over = sum(1 for s in samples if s > BUDGET)
    print(f"{label:30s} 中位 {statistics.median(samples):6.2f}ms  "
          f"p95 {p95:6.2f}ms  max {max(samples):6.2f}ms  "
          f"超预算 {over}/{len(samples)}")


def bench(label: str, view, items, steps: int = 90, stride: int = 37) -> None:
    """滚动条逐步推进 + 强制同步重绘 viewport，量每帧的 delegate 绘制成本。"""
    view.set_items(items)
    bar = view._list.verticalScrollBar()
    vp = view._list.viewport()
    view.show()
    app.processEvents()
    vp.repaint()          # 先画一屏：暖一次布局/字体/图标缓存
    app.processEvents()

    samples = []
    for i in range(steps):
        bar.setValue((i * stride) % max(1, bar.maximum()))
        t0 = time.perf_counter()
        vp.repaint()
        samples.append((time.perf_counter() - t0) * 1000.0)
    _report(label, samples)
    view.close()


def bench_window(label: str, view, items, steps: int = 60,
                 stride: int = 37) -> None:
    """整窗重绘（列表 + 导航 + 搜索框投影 + 状态栏）——真机合成成本的近似。"""
    view.set_items(items)
    bar = view._list.verticalScrollBar()
    win = QMainWindow()
    win.setCentralWidget(view)
    win.resize(420, 700)
    win.show()
    app.processEvents()
    win.repaint()

    samples = []
    for i in range(steps):
        bar.setValue((i * stride) % max(1, bar.maximum()))
        t0 = time.perf_counter()
        win.repaint()
        samples.append((time.perf_counter() - t0) * 1000.0)
    _report(label, samples)
    win.close()


def bench_cold(label: str, root: Path, n_images: int, n_text: int) -> None:
    """真正的冷路径：删掉落盘缩略图 + 清内存缓存 + 不预热，首轮滚动的帧成本。"""
    eng, svc, items = _seed(root, n_images=n_images, n_text=n_text)
    for t in (root / "images").glob("*.thumb.png"):
        t.unlink()
    svc._thumbnail_cached.cache_clear()
    view = HistoryView()
    view.set_image_service(svc)
    view.resize(420, 700)
    bench(label, view, items, steps=40, stride=110)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        eng, svc, items = _seed(tmp / "main", n_images=60, n_text=240)
        dpr = app.primaryScreen().devicePixelRatio() if app.primaryScreen() else 1
        print(f"条目 {len(items)}（图片 60 / 文本 240）  dpr={dpr}  "
              f"视口 420x700  预算 {BUDGET}ms\n")

        view = HistoryView()
        view.set_image_service(svc)
        view.resize(420, 700)
        bench("热（落盘缩略图已就绪）", view, items)

        view = HistoryView()
        view.set_image_service(svc)
        view.resize(420, 700)
        bench_window("整窗重绘", view, items)

        bench_cold("冷（逐张解码原图）", tmp / "cold", 24, 90)


if __name__ == "__main__":
    main()
