"""缩略图落盘缓存测试（offscreen）。

验收标准 → 用例一一对应（见 `services/image_service.py` 模块文档）：
- 缩略图在 `save()` 时就落盘，之后冷启动第一次滚到图片也只付「读小文件」的钱
  （实测：解原图 ~3ms / 读落盘缩略图 ~0.15ms；不落盘的话每次启动都要重解一遍）
- 落盘缩略图与直接解码**逐像素一致**（换了缓存层不能改变画出来的东西）
- 老条目懒回填：小文件缺失时仍能出图，并把它补写回去
- 只对**受管**路径落盘——FILE 条目指向用户原始文档，绝不能往用户目录写东西
- 删除受管图片时连带清掉缩略图
- 失败不毒化缓存（沿用 test_thumbnail_retries_after_file_appears 的既有不变量）
"""
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image as PILImage
from PySide6.QtWidgets import QApplication

from services.image_service import THUMB_SUFFIX, ImageService

pytest_app = QApplication.instance() or QApplication([])

PNG = io.BytesIO()
PILImage.new("RGB", (1200, 900), (90, 120, 200)).save(PNG, "PNG")
PNG_BYTES = PNG.getvalue()


def _service(tmp_path) -> ImageService:
    svc = ImageService(tmp_path / "images")
    svc._thumbnail_cached.cache_clear()  # 每个用例从冷缓存开始
    return svc


def _thumb_of(svc: ImageService, path) -> Path:
    return Path(path).with_name(Path(path).stem + THUMB_SUFFIX)


# ---- 落盘 ----

def test_save_writes_thumbnail_next_to_image(tmp_path):
    svc = _service(tmp_path)
    path = svc.save(PNG_BYTES)
    assert path.exists()
    assert _thumb_of(svc, path).exists()


def test_saved_thumbnail_matches_direct_decode(tmp_path):
    """换缓存层不能改像素：落盘缩略图读出来的 QImage 与解原图逐像素一致。"""
    svc = _service(tmp_path)
    path = svc.save(PNG_BYTES)
    fast = svc.thumbnail(str(path))          # 走落盘小文件

    _thumb_of(svc, path).unlink()            # 挪开小文件 → 逼它解原图
    svc._thumbnail_cached.cache_clear()
    slow = svc.thumbnail(str(path))          # 走原图解码

    assert fast == slow
    assert (fast.width(), fast.height()) == (512, 384)  # 等比缩放到 512 宽


def test_thumbnail_backfills_when_file_missing(tmp_path):
    """老条目（没有落盘缩略图）仍能出图，并把小文件补写回去 → 下次走快路径。"""
    svc = _service(tmp_path)
    path = svc.save(PNG_BYTES)
    thumb = _thumb_of(svc, path)
    thumb.unlink()
    svc._thumbnail_cached.cache_clear()

    qimg = svc.thumbnail(str(path))
    assert qimg is not None and not qimg.isNull()
    assert thumb.exists(), "懒回填没把缩略图补写回去"


# ---- 只碰受管文件 ----

def test_non_managed_path_gets_no_thumbnail(tmp_path):
    """用户原始文档：能出图，但绝不往它的目录写 .thumb.png。"""
    svc = _service(tmp_path)
    user_file = tmp_path / "用户文档.png"
    user_file.write_bytes(PNG_BYTES)

    qimg = svc.thumbnail(str(user_file))
    assert qimg is not None
    assert not _thumb_of(svc, user_file).exists()
    assert list(tmp_path.glob("*.thumb.png")) == []


def test_prefetch_only_touches_managed_paths(tmp_path):
    """预热是后台补写：受管路径写小文件，非受管路径跳过（同样不碰用户目录）。"""
    svc = _service(tmp_path)
    managed = svc.save(PNG_BYTES)
    _thumb_of(svc, managed).unlink()
    user_file = tmp_path / "外部.png"
    user_file.write_bytes(PNG_BYTES)

    svc._warm([str(managed), str(user_file)])   # 同步跑一遍线程体

    assert _thumb_of(svc, managed).exists()
    assert not _thumb_of(svc, user_file).exists()


# ---- 删除连带清理 ----

def test_delete_removes_thumbnail_too(tmp_path):
    svc = _service(tmp_path)
    path = svc.save(PNG_BYTES)
    thumb = _thumb_of(svc, path)
    assert thumb.exists()

    svc.delete(str(path))
    assert not path.exists()
    assert not thumb.exists(), "删图后缩略图残留 = 白占磁盘"


# ---- 失败不毒化 ----

def test_missing_file_returns_none_and_retries(tmp_path):
    """文件缺失 → None 且不进缓存；文件随后出现时能重试成功（回归）。"""
    svc = _service(tmp_path)
    target = svc._dir / "later.png"
    assert svc.thumbnail(str(target)) is None

    target.write_bytes(PNG_BYTES)
    qimg = svc.thumbnail(str(target))
    assert qimg is not None and not qimg.isNull()


def test_thumbnail_survives_prefetch_after_delete(tmp_path):
    """删掉受管图片后预热不应崩（路径已不存在）。"""
    svc = _service(tmp_path)
    path = svc.save(PNG_BYTES)
    svc.delete(str(path))
    svc._warm([str(path)])  # 不抛异常即通过
