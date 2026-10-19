import sys
import math

from PySide6.QtCore import (
    Qt,
    QTimer,
    QElapsedTimer,
    QRectF,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QFont,
    QWheelEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractScrollArea,
)


# ============================================================
# Configuration
# ============================================================

ITEM_COUNT = 100

ITEM_HEIGHT = 76.0
ITEM_SPACING = 14.0
ITEM_STEP = ITEM_HEIGHT + ITEM_SPACING

SIDE_MARGIN = 20.0


# ============================================================
# Smooth Card View
# ============================================================

class SmoothCardView(QAbstractScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)

        # ====================================================
        # Basic
        # ====================================================

        self.setFrameShape(
            QAbstractScrollArea.NoFrame
        )

        self.setFocusPolicy(
            Qt.NoFocus
        )

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.setStyleSheet("""
            QAbstractScrollArea {
                background: #111318;
                border: none;
            }
        """)

        self.viewport().setAttribute(
            Qt.WA_OpaquePaintEvent,
            True
        )

        # ====================================================
        # Data
        # ====================================================

        self.items = [
            f"Card {i + 1:02d}"
            for i in range(ITEM_COUNT)
        ]

        # ====================================================
        # Scroll physics
        # ====================================================

        self.scroll_y = 0.0

        self.velocity = 0.0

        # 正常惯性
        self.friction = 4.6

        # 最大速度
        self.max_velocity = 1800.0

        # ====================================================
        # Input
        # ====================================================

        # 触控板
        self.touchpad_gain = 5.5

        # 鼠标
        self.mouse_wheel_impulse = 420.0

        # ====================================================
        # Overscroll
        # ====================================================

        self.spring_strength = 210.0

        self.spring_damping = 24.0

        self.max_overscroll = 90.0

        # ====================================================
        # Visual effects
        # ====================================================

        # 中心卡片
        self.center_scale = 1.0

        # 边缘卡片缩小到 90%
        self.edge_scale = 0.90

        # 最大 parallax
        self.parallax_strength = 12.0

        # ====================================================
        # Timing
        # ====================================================

        self.clock = QElapsedTimer()

        self.timer = QTimer(self)

        self.timer.setTimerType(
            Qt.PreciseTimer
        )

        self.timer.timeout.connect(
            self.physics_step
        )

        self.frame_interval = 8

        self.update_frame_rate()

        # ====================================================
        # Drag
        # ====================================================

        self.dragging = False

        self.last_mouse_y = 0.0

        # ====================================================
        # Font
        # ====================================================

        self.card_font = QFont(
            "Segoe UI",
            11
        )

    # ========================================================
    # Geometry
    # ========================================================

    def content_height(self):

        return max(
            0.0,
            len(self.items) *
            ITEM_STEP
            -
            ITEM_SPACING
        )

    def max_scroll(self):

        return max(
            0.0,
            self.content_height()
            -
            self.viewport().height()
        )

    # ========================================================
    # Refresh rate
    # ========================================================

    def update_frame_rate(self):

        screen = self.screen()

        if screen is None:

            refresh_rate = 60.0

        else:

            refresh_rate = (
                screen.refreshRate()
            )

            if refresh_rate <= 0:

                refresh_rate = 60.0

        self.frame_interval = max(
            1,
            round(
                1000.0 /
                refresh_rate
            )
        )

        self.timer.setInterval(
            self.frame_interval
        )

    # ========================================================
    # Start physics
    # ========================================================

    def start_physics(self):

        if not self.timer.isActive():

            self.clock.start()

            self.timer.start(
                self.frame_interval
            )

    # ========================================================
    # Wheel
    # ========================================================

    def wheelEvent(
        self,
        event: QWheelEvent
    ):

        pixel_delta = (
            event.pixelDelta().y()
        )

        # ====================================================
        # Touchpad
        # ====================================================

        if pixel_delta != 0:

            delta = float(
                pixel_delta
            )

            self.velocity -= (
                delta *
                self.touchpad_gain *
                7.0
            )

        # ====================================================
        # Mouse wheel
        # ====================================================

        else:

            angle = (
                event.angleDelta().y()
            )

            if angle == 0:

                event.ignore()
                return

            notches = (
                angle /
                120.0
            )

            self.velocity -= (
                notches *
                self.mouse_wheel_impulse
            )

        # ====================================================
        # Velocity limit
        # ====================================================

        self.velocity = max(
            -self.max_velocity,
            min(
                self.max_velocity,
                self.velocity
            )
        )

        self.start_physics()

        event.accept()

    # ========================================================
    # Mouse drag
    # ========================================================

    def mousePressEvent(
        self,
        event: QMouseEvent
    ):

        if event.button() == Qt.LeftButton:

            self.dragging = True

            self.last_mouse_y = (
                event.position().y()
            )

            self.velocity = 0.0

            self.start_physics()

            event.accept()

            return

        super().mousePressEvent(event)

    def mouseMoveEvent(
        self,
        event: QMouseEvent
    ):

        if not self.dragging:

            super().mouseMoveEvent(event)
            return

        current_y = (
            event.position().y()
        )

        delta = (
            current_y -
            self.last_mouse_y
        )

        self.last_mouse_y = current_y

        self.scroll_y -= delta

        self.velocity = (
            -delta * 60.0
        )

        maximum = self.max_scroll()

        self.scroll_y = max(
            -self.max_overscroll,
            min(
                maximum +
                self.max_overscroll,
                self.scroll_y
            )
        )

        self.viewport().update()

        event.accept()

    def mouseReleaseEvent(
        self,
        event: QMouseEvent
    ):

        if (
            event.button() ==
            Qt.LeftButton
            and
            self.dragging
        ):

            self.dragging = False

            self.start_physics()

            event.accept()

            return

        super().mouseReleaseEvent(event)

    # ========================================================
    # Physics
    # ========================================================

    def physics_step(self):

        if not self.clock.isValid():

            self.clock.start()

            return

        dt = (
            self.clock.restart()
            /
            1000.0
        )

        dt = min(
            max(
                dt,
                0.0001
            ),
            0.033
        )

        maximum = (
            self.max_scroll()
        )

        # ====================================================
        # Top overscroll
        # ====================================================

        if self.scroll_y < 0.0:

            displacement = (
                self.scroll_y
            )

            acceleration = (
                -self.spring_strength *
                displacement
                -
                self.spring_damping *
                self.velocity
            )

            self.velocity += (
                acceleration *
                dt
            )

            self.scroll_y += (
                self.velocity *
                dt
            )

        # ====================================================
        # Bottom overscroll
        # ====================================================

        elif self.scroll_y > maximum:

            displacement = (
                self.scroll_y -
                maximum
            )

            acceleration = (
                -self.spring_strength *
                displacement
                -
                self.spring_damping *
                self.velocity
            )

            self.velocity += (
                acceleration *
                dt
            )

            self.scroll_y += (
                self.velocity *
                dt
            )

        # ====================================================
        # Normal physics
        # ====================================================

        else:

            self.scroll_y += (
                self.velocity *
                dt
            )

            self.velocity *= math.exp(
                -self.friction *
                dt
            )

        # ====================================================
        # Overscroll limit
        # ====================================================

        if (
            self.scroll_y <
            -self.max_overscroll
        ):

            self.scroll_y = (
                -self.max_overscroll
            )

            if self.velocity < 0:

                self.velocity = 0.0

        elif (
            self.scroll_y >
            maximum +
            self.max_overscroll
        ):

            self.scroll_y = (
                maximum +
                self.max_overscroll
            )

            if self.velocity > 0:

                self.velocity = 0.0

        # ====================================================
        # Spring settle
        # ====================================================

        if self.scroll_y < 0:

            if (
                abs(self.scroll_y) < 0.05
                and
                abs(self.velocity) < 1.0
            ):

                self.scroll_y = 0.0
                self.velocity = 0.0

        elif self.scroll_y > maximum:

            if (
                abs(
                    self.scroll_y -
                    maximum
                ) < 0.05
                and
                abs(self.velocity) < 1.0
            ):

                self.scroll_y = maximum
                self.velocity = 0.0

        # ====================================================
        # Redraw
        # ====================================================

        self.viewport().update()

        # ====================================================
        # Stop
        # ====================================================

        if (
            abs(self.velocity) < 1.0
            and
            0.0 <=
            self.scroll_y <=
            maximum
        ):

            self.velocity = 0.0

            self.timer.stop()

    # ========================================================
    # Paint
    # ========================================================

    def paintEvent(self, event):

        painter = QPainter(
            self.viewport()
        )

        painter.setRenderHint(
            QPainter.Antialiasing,
            True
        )

        painter.setRenderHint(
            QPainter.TextAntialiasing,
            True
        )

        # ====================================================
        # Background
        # ====================================================

        painter.fillRect(
            self.viewport().rect(),
            QColor("#111318")
        )

        width = (
            self.viewport().width()
        )

        height = (
            self.viewport().height()
        )

        # ====================================================
        # Visible items
        # ====================================================

        first_index = max(
            0,
            int(
                self.scroll_y /
                ITEM_STEP
            ) - 2
        )

        last_index = min(
            len(self.items),
            int(
                (
                    self.scroll_y +
                    height
                )
                /
                ITEM_STEP
            ) + 3
        )

        for index in range(
            first_index,
            last_index
        ):

            base_y = (
                index *
                ITEM_STEP
                -
                self.scroll_y
            )

            self.paint_card(
                painter,
                index,
                base_y,
                width,
                height
            )

        painter.end()

    # ========================================================
    # Paint card
    # ========================================================

    def paint_card(
        self,
        painter,
        index,
        base_y,
        viewport_width,
        viewport_height
    ):

        card_x = SIDE_MARGIN

        card_width = (
            viewport_width -
            SIDE_MARGIN * 2
        )

        card_y = (
            base_y +
            ITEM_SPACING / 2.0
        )

        card_height = (
            ITEM_HEIGHT
        )

        # ====================================================
        # Cull
        # ====================================================

        if (
            card_y +
            card_height <
            -40
            or
            card_y >
            viewport_height + 40
        ):

            return

        # ====================================================
        # Distance to center
        # ====================================================

        card_center_y = (
            card_y +
            card_height /
            2.0
        )

        viewport_center_y = (
            viewport_height /
            2.0
        )

        distance = abs(
            card_center_y -
            viewport_center_y
        )

        max_distance = (
            viewport_height *
            0.60
        )

        t = min(
            distance /
            max_distance,
            1.0
        )

        # ====================================================
        # Smoothstep
        # ====================================================

        t = (
            t *
            t *
            (
                3.0 -
                2.0 *
                t
            )
        )

        # ====================================================
        # Scale
        #
        # 1.00 -> 0.90
        # ====================================================

        scale = (
            1.0 -
            (
                1.0 -
                self.edge_scale
            )
            *
            t
        )

        # ====================================================
        # Visual depth
        #
        # 不再使用 painter.setOpacity()
        #
        # 这样卡片重叠不会 alpha 叠加变深。
        # ====================================================

        # 中间更亮
        brightness = (
            1.0 -
            0.18 * t
        )

        # ====================================================
        # Parallax
        #
        # 最大约 12px
        # ====================================================

        if card_center_y < viewport_center_y:

            direction = -1.0

        else:

            direction = 1.0

        parallax = (
            direction *
            self.parallax_strength *
            t
        )

        card_y += parallax

        # ====================================================
        # Additional motion based on velocity
        #
        # 让高速滚动时卡片视觉变化更加明显。
        # ====================================================

        velocity_factor = min(
            abs(self.velocity) /
            self.max_velocity,
            1.0
        )

        # 只增加一点动态位移
        motion_offset = (
            -math.copysign(
                4.0 *
                velocity_factor,
                self.velocity
            )
            if abs(self.velocity) > 20
            else 0.0
        )

        card_y += motion_offset

        # ====================================================
        # Center
        # ====================================================

        center_x = (
            card_x +
            card_width /
            2.0
        )

        center_y = (
            card_y +
            card_height /
            2.0
        )

        painter.save()

        # ====================================================
        # Scale
        # ====================================================

        painter.translate(
            center_x,
            center_y
        )

        painter.scale(
            scale,
            scale
        )

        painter.translate(
            -center_x,
            -center_y
        )

        # ====================================================
        # Colors
        # ====================================================

        base_r = int(
            32 * brightness
        )

        base_g = int(
            35 * brightness
        )

        base_b = int(
            42 * brightness
        )

        card_color = QColor(
            base_r,
            base_g,
            base_b
        )

        # ====================================================
        # Shadow
        # ====================================================

        shadow_rect = QRectF(
            card_x,
            card_y + 5.0,
            card_width,
            card_height
        )

        shadow_path = QPainterPath()

        shadow_path.addRoundedRect(
            shadow_rect,
            18.0,
            18.0
        )

        # 不使用 opacity
        # shadow 本身使用固定 alpha
        painter.fillPath(
            shadow_path,
            QColor(
                0,
                0,
                0,
                38
            )
        )

        # ====================================================
        # Card
        # ====================================================

        card_rect = QRectF(
            card_x,
            card_y,
            card_width,
            card_height
        )

        card_path = QPainterPath()

        card_path.addRoundedRect(
            card_rect,
            18.0,
            18.0
        )

        painter.fillPath(
            card_path,
            card_color
        )

        # ====================================================
        # Border
        # ====================================================

        border_alpha = int(
            12 +
            12 *
            (
                1.0 -
                t
            )
        )

        painter.setPen(
            QColor(
                255,
                255,
                255,
                border_alpha
            )
        )

        painter.drawPath(
            card_path
        )

        # ====================================================
        # Text
        # ====================================================

        text_brightness = int(
            235 -
            35 * t
        )

        painter.setPen(
            QColor(
                text_brightness,
                text_brightness,
                min(
                    255,
                    text_brightness + 5
                )
            )
        )

        painter.setFont(
            self.card_font
        )

        text_rect = QRectF(
            card_x + 24,
            card_y,
            card_width - 48,
            card_height
        )

        painter.drawText(
            text_rect,
            Qt.AlignLeft |
            Qt.AlignVCenter,
            self.items[index]
        )

        painter.restore()

    # ========================================================
    # Resize
    # ========================================================

    def resizeEvent(self, event):

        super().resizeEvent(event)

        self.update_frame_rate()

        maximum = (
            self.max_scroll()
        )

        self.scroll_y = max(
            -self.max_overscroll,
            min(
                maximum +
                self.max_overscroll,
                self.scroll_y
            )
        )

        self.viewport().update()

    # ========================================================
    # Show
    # ========================================================

    def showEvent(self, event):

        super().showEvent(event)

        self.update_frame_rate()


# ============================================================
# Main
# ============================================================

def main():

    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    view = SmoothCardView()

    view.resize(
        520,
        720
    )

    view.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())