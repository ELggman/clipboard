"""线性图标库：统一线宽 SF-Symbols 风格图标（QPainter 手绘）。

背景（本会话血泪史）：Qt 6.9 macOS 下 emoji 字形 / QPushButton·QLineEdit
图标渲染为空白，QPainter 自绘是唯一可靠路径。故所有图标用 QPainter +
QPainterPath 绘制成 QPixmap，供 delegate / 自绘控件使用。

风格：24px 逻辑基准、2px 线宽、圆头圆角、仅描边（except 实心点类）。
颜色由调用方按主题传入（深浅自适应）。
"""
import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

_BASE = 24      # 逻辑基准尺寸
_STROKE = 2.0   # 基准线宽（24px 下）


def _line(p, x1, y1, x2, y2) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _polyline(p, pts) -> None:
    path = QPainterPath(QPointF(*pts[0]))
    for x, y in pts[1:]:
        path.lineTo(x, y)
    p.drawPath(path)


# ---- 各图标绘制函数（24×24 坐标系） ----

def _clock(p) -> None:
    p.drawEllipse(QRectF(3, 3, 18, 18))
    _line(p, 12, 7, 12, 12)
    _line(p, 12, 12, 16, 14.5)


def _star(p) -> None:
    cx, cy, R, r = 12, 12, 9.2, 4.3
    pts = [QPointF(cx + (R if i % 2 == 0 else r) * math.cos(math.pi / 2 + i * math.pi / 5),
                   cy - (R if i % 2 == 0 else r) * math.sin(math.pi / 2 + i * math.pi / 5))
           for i in range(10)]
    poly = QPolygonF(pts)
    path = QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    p.drawPath(path)


def _clipboard(p) -> None:
    p.drawRoundedRect(QRectF(5.5, 5, 13, 15), 2, 2)
    p.drawRoundedRect(QRectF(10.2, 2.4, 3.6, 4.4), 1.4, 1.4)
    _line(p, 8.8, 11, 15.2, 11)
    _line(p, 8.8, 14.6, 13, 14.6)


def _chart(p) -> None:
    _polyline(p, [(4, 18), (9, 13), (13, 16), (20, 6)])
    p.drawEllipse(QPointF(4, 18), 1.8, 1.8)
    p.drawEllipse(QPointF(20, 6), 1.8, 1.8)


def _gear(p) -> None:
    for i in range(8):
        a = i * math.pi / 4
        _line(p, 12 + 5.8 * math.cos(a), 12 + 5.8 * math.sin(a),
              12 + 8.6 * math.cos(a), 12 + 8.6 * math.sin(a))
    p.drawEllipse(QRectF(6, 6, 12, 12))
    p.drawEllipse(QRectF(9.3, 9.3, 5.4, 5.4))


def _search(p) -> None:
    p.drawEllipse(QRectF(3.2, 3.2, 12.6, 12.6))
    _line(p, 14, 14, 20.4, 20.4)


def _code(p) -> None:
    _polyline(p, [(9.4, 5.4), (3.8, 12), (9.4, 18.6)])
    _polyline(p, [(14.6, 5.4), (20.2, 12), (14.6, 18.6)])


def _link(p) -> None:
    p.drawEllipse(QRectF(1.4, 11.6, 10.4, 10.4))
    p.drawEllipse(QRectF(12.2, 2, 10.4, 10.4))
    _line(p, 10, 14, 14, 10)


def _image(p) -> None:
    p.drawRoundedRect(QRectF(3.4, 4.4, 17.2, 15.2), 2, 2)
    _polyline(p, [(6.4, 16.6), (10.4, 11), (13.4, 14), (16, 11.6), (18, 16.6)])
    p.drawEllipse(QRectF(15.2, 6.8, 3, 3))


def _file(p) -> None:
    path = QPainterPath(QPointF(6, 3))
    path.lineTo(14, 3)
    path.lineTo(19, 8)
    path.lineTo(19, 21)
    path.lineTo(6, 21)
    path.closeSubpath()
    p.drawPath(path)
    _polyline(p, [(14, 3), (14, 8), (19, 8)])


def _text(p) -> None:
    _line(p, 5, 6, 19, 6)
    _line(p, 12, 6, 12, 19)
    _line(p, 8.4, 19, 15.6, 19)


def _lock(p) -> None:
    p.drawRoundedRect(QRectF(6.6, 10.6, 10.8, 9.4), 1.8, 1.8)
    path = QPainterPath()
    path.addRoundedRect(QRectF(8.6, 5.2, 6.8, 5.8), 3.2, 3.2)
    p.drawPath(path)
    _line(p, 12, 13.4, 12, 15.8)
    p.drawEllipse(QPointF(12, 13.2), 1.3, 1.3)


def _more(p) -> None:
    color = p.pen().color()
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    for x in (7, 12, 17):
        p.drawEllipse(QPointF(x, 12), 1.8, 1.8)


def _chevron(p) -> None:
    _polyline(p, [(9.4, 5), (16.4, 12), (9.4, 19)])


# ---- 注册表 ----

_ICONS = {
    "clock": _clock,
    "star": _star,
    "clipboard": _clipboard,
    "chart": _chart,
    "gear": _gear,
    "search": _search,
    "code": _code,
    "link": _link,
    "image": _image,
    "file": _file,
    "text": _text,
    "lock": _lock,
    "more": _more,
    "chevron": _chevron,
}


def available() -> tuple[str, ...]:
    return tuple(_ICONS)


_SUPERSAMPLE = 2   # 超采样倍率：物理画布 = 逻辑 size × 2（Retina 1:1、普通屏下采样）

# ⚠️ 两处已知坑（本会话血泪）：
# 1. 高 DPI 模糊：pixmap 只建 size×size 物理像素，Retina（dpr=2）显示时
#    需放大到 2×size → 像素不足发虚。必须按 size×2 建物理画布。
# 2. devicePixelRatio 的 QPainter 坐标系 bug（PySide6 macOS 实测）：给
#    pixmap setDevicePixelRatio(dpr) 后，painter.scale(size*dpr/_BASE) 绘制
#    的图标会整体缩小并偏移（link 内容 bbox 变小、画偏右下），且在部分
#    目标上被 Qt 放大 2 倍显示。故**不用 devicePixelRatio**：固定 2x 超采样
#    dpr=1 画布 + 调用端 drawPixmap 显式传目标逻辑尺寸（见调用处注释）。


@lru_cache(maxsize=512)
def make_icon(name: str, size: int, color_name: str) -> QPixmap:
    """按名称/尺寸/颜色渲染图标（缓存 key：名称+尺寸+颜色名）。

    物理画布 size×2（dpr=1），画笔宽度按逻辑尺寸 ×2 以匹配超采样。
    调用端必须用 drawPixmap(x, y, size, size, pix) 显式传目标逻辑尺寸，
    否则 pix 逻辑宽 = size×2 会被画成 2 倍大（勿用 3 参无 rect 形式）。
    """
    draw = _ICONS.get(name)
    if draw is None:
        return QPixmap()
    color = QColor(color_name)
    phys = max(2, round(size * _SUPERSAMPLE))
    pix = QPixmap(phys, phys)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # 物理坐标系绘制：24 基准画满 phys 物理像素（逻辑仍 = size）
    painter.scale(phys / _BASE, phys / _BASE)
    pen = QPen(color, max(1.4, _STROKE * size / _BASE) * _SUPERSAMPLE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter)
    painter.end()
    return pix


def icon(name: str, size: int, color: QColor) -> QPixmap:
    """便捷入口：接受 QColor（内部转 name 走缓存）。"""
    return make_icon(name, size, color.name(QColor.NameFormat.HexArgb))
