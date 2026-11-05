from __future__ import annotations

import math
import os

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from searchmob_desktop.gui.theme import active_palette

_TWO_PI = 2.0 * math.pi


class WaveOverlay(QWidget):
    RUN_DURATION_MS = 3000
    STOP_DURATION_MS = 200
    TIMER_INTERVAL = 16

    LAYERS = (
        (2.0, 0.35, 1.0, 0.45),
        (3.5, 0.25, 1.4, 0.35),
        (5.0, 0.15, 0.7, 0.25),
    )

    def __init__(self, parent: QLineEdit, reduced_motion: bool = False) -> None:
        super().__init__(parent)
        self._line_edit = parent
        self._reduced_motion_flag = reduced_motion

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.setGeometry(self._line_edit.rect())

        self._run_timer = QElapsedTimer()
        self._stop_timer = QElapsedTimer()
        self._mode = "idle"
        self._stop_start_raw = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(self.TIMER_INTERVAL)
        self._timer.timeout.connect(self._on_tick)

        self._paths = [QPainterPath() for _ in self.LAYERS]
        self._top_paths = [QPainterPath() for _ in self.LAYERS]
        self._wipe_rect = QRectF()
        self._clip_path = QPainterPath()

        self._line_edit.installEventFilter(self)
        self._line_edit.destroyed.connect(self.deleteLater)
        self.lower()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._line_edit and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._line_edit.rect())
            self.update()
        return False

    def _reduced_motion_enabled(self) -> bool:
        if self._reduced_motion_flag:
            return True
        try:
            hints = QApplication.styleHints()
            fn = getattr(hints, "prefersReducedMotion", None)
            if callable(fn):
                return bool(fn())
        except Exception:
            pass
        return os.environ.get("SEARCHMOB_REDUCED_MOTION", "") == "1"

    def _raw_progress(self) -> float:
        if self._mode == "stop":
            elapsed = self._stop_timer.elapsed()
            ratio = min(1.0, max(0.0, elapsed / float(self.STOP_DURATION_MS)))
            eased = 1.0 - (1.0 - ratio) ** 3.0
            raw = self._stop_start_raw + (1.0 - self._stop_start_raw) * eased
            return min(1.0, max(0.0, raw))
        if self._mode == "run":
            elapsed = self._run_timer.elapsed()
            return min(1.0, max(0.0, elapsed / float(self.RUN_DURATION_MS)))
        return 0.0

    def start(self) -> None:
        self._mode = "run"
        self._run_timer.start()
        self._stop_start_raw = 0.0
        self.show()
        self.lower()
        if not self._timer.isActive():
            self._timer.start(self.TIMER_INTERVAL)
        self.update()

    def stop(self) -> None:
        if self._mode != "run":
            return
        self._stop_start_raw = self._raw_progress()
        if self._stop_start_raw >= 0.9999:
            self._finish_stop()
            return
        self._mode = "stop"
        self._stop_timer.start()
        if not self._timer.isActive():
            self._timer.start(self.TIMER_INTERVAL)

    def _finish_stop(self) -> None:
        self._mode = "idle"
        if self._timer.isActive():
            self._timer.stop()
        self.hide()
        self.update()

    def _on_tick(self) -> None:
        if self._mode == "stop":
            if self._stop_timer.elapsed() >= self.STOP_DURATION_MS:
                self._finish_stop()
                return
        self.update()

    @staticmethod
    def _reset_path(path: QPainterPath) -> None:
        try:
            path.clear()
        except AttributeError:
            path.__init__()

    def _elapsed_seconds(self) -> float:
        if self._mode in ("run", "stop") and self._run_timer.isValid():
            return self._run_timer.elapsed() / 1000.0
        return 0.0

    def paintEvent(self, event: QEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        width = rect.width()
        height = rect.height()
        if width <= 0 or height <= 0:
            painter.end()
            return

        self._reset_path(self._clip_path)
        self._clip_path.addRoundedRect(QRectF(rect), 10.0, 10.0)
        painter.setClipPath(self._clip_path)

        palette = active_palette()
        raw = self._raw_progress()
        display = 1.0 - (1.0 - raw) ** 3.0
        fill_x = display * width

        if self._reduced_motion_enabled():
            accent = QColor(palette.accent)
            accent.setAlphaF(0.42)
            self._wipe_rect.setRect(0.0, 0.0, fill_x, float(height))
            painter.fillRect(self._wipe_rect, accent)
            painter.end()
            return

        wave_time = self._elapsed_seconds()
        accent_base = QColor(palette.accent)
        surface_base = QColor(palette.surface)

        for index in reversed(range(len(self.LAYERS))):
            frequency, amplitude, speed, alpha = self.LAYERS[index]
            path = self._paths[index]
            top_path = self._top_paths[index]
            self._reset_path(path)
            self._reset_path(top_path)

            if fill_x <= 0:
                continue

            accent_color = QColor(accent_base)
            accent_color.setAlphaF(alpha)
            surface_color = QColor(surface_base)
            surface_color.setAlphaF(alpha * 0.75)

            gradient = QLinearGradient(0.0, 0.0, 0.0, float(height))
            gradient.setColorAt(0.0, surface_color)
            gradient.setColorAt(1.0, accent_color)

            path.moveTo(0.0, float(height))
            for px in range(int(fill_x) + 1):
                x = float(px)
                phase = (_TWO_PI * frequency * (x / float(width))) + (
                    wave_time * speed * _TWO_PI
                )
                y = (height * 0.5) + (amplitude * height * 0.5 * math.sin(phase))
                path.lineTo(x, y)
                if px == 0:
                    top_path.moveTo(x, y)
                else:
                    top_path.lineTo(x, y)

            path.lineTo(fill_x, float(height))
            path.closeSubpath()

            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)

            foam_color = QColor(255, 255, 255, int(255 * min(1.0, alpha * 1.2)))
            foam_pen = QPen(foam_color, max(1, height // 28))
            foam_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            foam_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(foam_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(top_path)

        painter.end()

    def sizeHint(self) -> QSize:
        if self._line_edit is not None:
            return self._line_edit.size()
        return QSize(120, 24)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)
