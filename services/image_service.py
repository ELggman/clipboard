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

    def delete(self, file_path: str) -> None:
        """删除记录时同步删图片文件（失败只记日志，不阻断主流程）。"""
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            logger.exception("删除图片失败: %s", file_path)
