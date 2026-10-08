"""图片服务：落盘、缩略图缓存、懒加载（DEVELOPMENT.md §3.5）。

图片不入库：images/<sha256>.png，DB 只存路径。

**缩略图两级缓存**（实测：解码原图 3.04ms vs 读落盘缩略图 0.149ms，差 20×）：

1. 磁盘级：`images/<sha256>.t512.png`（长边 ≤512px）。缩略图在 `save()` 时就顺手生成，
   老条目首次被用到时懒回填。冷启动后仍是 0.149ms 级——这一层才是关键，因为
   `@lru_cache` 与 delegate 的 QPixmap 缓存都只活在**当前进程**内。
2. 内存级：`@lru_cache(maxsize=128)`，省掉同一屏反复绘制时的重复读盘。
   QImage 必须 copy() 才能脱离 PIL 临时 buffer。

**为什么是 512 而不是 256**（2026-09-30 用户反馈「缩略图看不清」）：列表现已
等比缩放到 68px 高的框内（宽截图可到 ~170px 宽），Retina dpr=2 下要 340×136
物理像素，256px 源已经不够。后缀里带尺寸（`.t512.png`），将来再调直接改常量、
老文件自动失效重生成。旧的 256px 文件（`.thumb.png`）在重写/删除时顺手清掉。

为什么必须两级都有：缩略图解码原先压在 delegate 的 `paint()` 上，一屏几张图就是
9-16ms，直接吃掉 60fps 的 16.7ms 预算（实测图片列表首轮滚动中位 9.77ms、
p95 16.23ms、最大 29.64ms）。落盘后每次启动第一次滚到图片也只付 0.15ms。
"""
import hashlib
import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

THUMB_SIZE = (512, 512)  # 落盘缩略图上限（等比缩放，长边封顶）
# ⚠️ 后缀里带尺寸：将来再调 THUMB_SIZE，老文件自动失效重生成，不必逐个开图验尺寸
# （旧版写的是 <digest>.thumb.png = 256px，见 _LEGACY_THUMB_SUFFIX，写入时顺手清掉）
THUMB_SUFFIX = ".t512.png"
_LEGACY_THUMB_SUFFIX = ".thumb.png"


class ImageService:
    def __init__(self, images_dir: Path):
        self._dir = images_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes) -> Path:
        """落盘：先解码重编码为 PNG，按 **PNG 字节**的 sha256 命名并返回路径。

        为什么要重编码再算 hash：来源剪贴板可能是 TIFF/其它格式（截图/
        Safari），旧实现按「原始字节」sha256 命名，但文件内容其实已是重编码
        的 PNG —— 之后 Quick Paste 重新复制该图，系统剪贴板拿到的是 PNG
        字节，digest 与 DB 里存的「原始 TIFF digest」不同 → 去重失效，产生
        重复条目（用户实测）。统一为「PNG 内容 digest」后，重复制闭环 hash
        一致，去重命中。重名直接复用，不入数据库。
        """
        img = Image.open(BytesIO(data))
        buf = BytesIO()
        img.save(buf, "PNG")
        png_bytes = buf.getvalue()  # 落盘即这份字节 → 命名即内容 digest
        digest = hashlib.sha256(png_bytes).hexdigest()
        path = self._dir / f"{digest}.png"
        if not path.exists():
            path.write_bytes(png_bytes)
            # 缩略图顺手生成：此处 img 已经解码在手，边际成本 ~0.5ms；不做的话
            # 之后每次冷启动滚到这张图都要重解一遍原图（3ms）。
            self._write_thumb(img, path)
            logger.info("图片已保存: %s", path.name)
        return path

    # ---- 缩略图 ----

    def _thumb_path(self, file_path) -> Path | None:
        """受管图片的落盘缩略图路径；**非受管返回 None**。

        安全边界与 `is_managed()` 同源：FILE 条目的 file_path 指向用户原始文档，
        绝不允许往用户目录里写 .thumb.png。
        """
        if not self.is_managed(file_path):
            return None
        p = Path(file_path)
        return p.with_name(p.stem + THUMB_SUFFIX)

    @staticmethod
    def _encode_thumb(img) -> bytes:
        """原图 → 缩略图 PNG 字节（与绘制路径同一套管线，保证像素一致）。"""
        thumb = img.copy()
        thumb.thumbnail(THUMB_SIZE)
        buf = BytesIO()
        thumb.convert("RGBA").save(buf, "PNG")
        return buf.getvalue()

    def _write_thumb(self, img, file_path) -> None:
        """把缩略图落盘。失败只记日志——**不能**因此让原图保存/绘制失败。"""
        thumb_path = self._thumb_path(file_path)
        if thumb_path is None:
            return
        try:
            thumb_path.write_bytes(self._encode_thumb(img))
            # 顺手清掉旧尺寸的缩略图（老版本写的 256px），免得留成孤儿文件
            legacy = thumb_path.with_name(
                Path(file_path).stem + _LEGACY_THUMB_SUFFIX)
            if legacy != thumb_path and legacy.exists():
                legacy.unlink(missing_ok=True)
        except Exception:
            logger.exception("缩略图落盘失败（不影响原图）: %s", thumb_path)

    @lru_cache(maxsize=128)
    def _thumbnail_cached(self, file_path: str):
        """缩略图解码（仅成功结果进缓存；失败抛异常不缓存）。

        快路径：读同目录已落盘的 `<stem>.t512.png`（0.15ms）。
        慢路径：老条目还没有落盘缩略图 → 解原图（~3ms），**顺手补写**，
        下次即走快路径。补写只为受管路径。
        """
        from PySide6.QtGui import QImage

        thumb_path = self._thumb_path(file_path)
        if thumb_path is not None and thumb_path.exists():
            qimg = QImage(str(thumb_path))
            if not qimg.isNull():
                # 与慢路径同一格式契约：RGBA8888（读盘默认给 ARGB32）
                return qimg.convertToFormat(QImage.Format.Format_RGBA8888)
        img = Image.open(file_path)
        self._write_thumb(img, file_path)  # 懒回填：下一次就是快路径
        thumb = img.copy()
        thumb.thumbnail(THUMB_SIZE)
        thumb = thumb.convert("RGBA")
        data = thumb.tobytes("raw", "RGBA")
        qimg = QImage(data, thumb.width, thumb.height, thumb.width * 4,
                      QImage.Format.Format_RGBA8888)
        return qimg.copy()  # 复制以脱离 PIL 临时 buffer

    def prefetch(self, paths) -> None:
        """后台预热：把还没落盘缩略图的图片补写掉（页面装载后调用一次）。

        老条目第一次被滚到仍要付一次 ~3ms 解码（随后才走 0.15ms 快路径）。预热把
        这一次成本挪到后台线程，几秒内整库转成小文件——否则「升级后第一次滚图片」
        还是会卡一下。

        用普通 daemon 线程而不是 QThreadPool：预热过程**只做 PIL 解码 + 文件读写，
        完全不碰任何 Qt 对象**（不构造 QImage），所以既没有线程亲和性问题，也不用
        操心 QRunnable 的 Python/C++ 所有权。daemon 线程不会拖住退出。
        """
        todo = []
        for path in paths:
            if not path:
                continue
            thumb = self._thumb_path(path)
            if thumb is not None and not thumb.exists():
                todo.append(path)
        if not todo:
            return
        import threading

        threading.Thread(target=self._warm, args=(todo,), daemon=True,
                         name="thumb-prefetch").start()

    def _warm(self, paths) -> None:
        """后台线程体：逐张补写缩略图。失败只记日志（预热失败不影响功能）。"""
        for path in paths:
            try:
                thumb = self._thumb_path(path)
                if thumb is None or thumb.exists():
                    continue
                img = Image.open(path)
                self._write_thumb(img, path)
                img.close()  # 批量预热时别攒着文件句柄
            except Exception:
                logger.debug("缩略图预热失败: %s", path)

    def thumbnail(self, file_path: str):
        """缩略图（懒加载：滚动到可视区才调用）。失败返回 None 且**不缓存**。

        关键：@lru_cache 会缓存 None 返回值——文件缺失时的失败会被
        永久缓存，文件随后出现也永远返回 None（实测踩坑：历史/收藏
        全部缩略图消失，重启才恢复）。失败路径必须走未缓存入口重试。
        """
        try:
            return self._thumbnail_cached(file_path)
        except Exception:
            logger.exception("缩略图生成失败: %s", file_path)
            return None

    def is_managed(self, file_path: str) -> bool:
        """路径是否属于 app 管理的 images 目录。

        关键安全边界：FILE 条目的 file_path 指向用户**原始文档**，
        删除历史时只允许清理本目录内的副本，绝不触碰用户文件
        （实测踩坑：清数据把用户原文档删掉，收藏快照指向空路径）。
        """
        try:
            return Path(file_path).resolve().parent == self._dir.resolve()
        except OSError:
            return False

    def delete(self, file_path: str) -> None:
        """删除单个**受管**图片及其落盘缩略图（仅 images 目录内；失败只记日志不阻断）。"""
        if not self.is_managed(file_path):
            logger.warning("跳过非受管文件删除（保护用户文件）: %s", file_path)
            return
        try:
            Path(file_path).unlink(missing_ok=True)
            thumb_path = self._thumb_path(file_path)
            if thumb_path is not None:
                thumb_path.unlink(missing_ok=True)
                # 旧尺寸的缩略图一并清掉（升级时留下的孤儿）
                thumb_path.with_name(
                    Path(file_path).stem + _LEGACY_THUMB_SUFFIX
                ).unlink(missing_ok=True)
        except OSError:
            logger.exception("删除图片失败: %s", file_path)

    def delete_many(self, paths: list[str]) -> None:
        """批量删除受管图片（自动过滤非 images 目录路径）。"""
        for path in paths:
            self.delete(path)
