"""图片服务：落盘、缩略图缓存、懒加载（DEVELOPMENT.md §3.5）。

图片不入库：images/<sha256>.png，DB 只存路径。
缩略图用内存 LRU（@lru_cache），QImage 需 copy() 脱离原始 buffer。
"""
import hashlib
import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

THUMB_SIZE = (256, 256)  # 列表缩略图尺寸


class ImageService:
    def __init__(self, images_dir: Path):
        self._dir = images_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes) -> Path:
        """按内容 hash 落盘（重名直接复用），返回存储路径。"""
        digest = hashlib.sha256(data).hexdigest()
        path = self._dir / f"{digest}.png"
        if not path.exists():
            try:
                img = Image.open(BytesIO(data))
                img.save(path, "PNG")
                logger.info("图片已保存: %s", path.name)
            except Exception:
                logger.exception("图片落盘失败")
                raise
        return path

    @lru_cache(maxsize=128)
    def thumbnail(self, file_path: str):
        """缩略图（懒加载：滚动到可视区才调用）。失败返回 None。"""
        from PySide6.QtGui import QImage

        try:
            img = Image.open(file_path)
            img.thumbnail(THUMB_SIZE)
            img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, img.width * 4,
                          QImage.Format_RGBA8888)
            return qimg.copy()  # 复制以脱离 PIL 临时 buffer
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
        """删除单个**受管**图片（仅 images 目录内；失败只记日志不阻断）。"""
        if not self.is_managed(file_path):
            logger.warning("跳过非受管文件删除（保护用户文件）: %s", file_path)
            return
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            logger.exception("删除图片失败: %s", file_path)

    def delete_many(self, paths: list[str]) -> None:
        """批量删除受管图片（自动过滤非 images 目录路径）。"""
        for path in paths:
            self.delete(path)
