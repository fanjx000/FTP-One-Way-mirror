"""Application icon drawn with QPainter (no external assets needed)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)


def _draw(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # rounded background with a soft vertical gradient
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0.0, QColor("#5aa7ff"))
    grad.setColorAt(1.0, QColor("#2f6fd0"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(1, 1, size - 2, size - 2), size * 0.24, size * 0.24)
    p.fillPath(path, QBrush(grad))

    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(1.6, size * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)

    s = size / 64.0
    top_y, bot_y = 24 * s, 40 * s
    left_x, right_x = 15 * s, 49 * s

    # upper arrow ->
    p.drawLine(QPointF(left_x, top_y), QPointF(right_x - 2 * s, top_y))
    p.setBrush(QBrush(QColor("#ffffff")))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([
        QPointF(right_x, top_y), QPointF(right_x - 9 * s, top_y - 6.5 * s),
        QPointF(right_x - 9 * s, top_y + 6.5 * s)]))
    # lower arrow <-
    p.setPen(pen)
    p.drawLine(QPointF(right_x, bot_y), QPointF(left_x + 2 * s, bot_y))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([
        QPointF(left_x, bot_y), QPointF(left_x + 9 * s, bot_y - 6.5 * s),
        QPointF(left_x + 9 * s, bot_y + 6.5 * s)]))
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_draw(size))
    return icon
