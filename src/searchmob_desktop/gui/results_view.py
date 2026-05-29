"""Results list backed by a `QStandardItemModel`. Click opens the URL in the system browser.

The Android `SearchScreen` shows a card per result with bold title, body snippet, and a small
engine badge. Here a `QListView` with a custom delegate gives the same shape without the cost of
laying out N `QWidget`s. The delegate draws title, URL (muted), snippet, and engine badge in
one item.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QDesktopServices,
    QFont,
    QPainter,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from searchmob_desktop.engines import SearchResult
from searchmob_desktop.engines.rank import RankRule, host_of_url

# Custom roles so the delegate does not have to parse the visible string back into fields.
_TITLE_ROLE = Qt.ItemDataRole.UserRole + 1
_URL_ROLE = Qt.ItemDataRole.UserRole + 2
_SNIPPET_ROLE = Qt.ItemDataRole.UserRole + 3
_ENGINE_ROLE = Qt.ItemDataRole.UserRole + 4


class _ResultDelegate(QStyledItemDelegate):
    """Paint a result row: title (bold), URL (muted), snippet (small), engine (badge color)."""

    _ROW_PADDING = 10
    _LINE_SPACING = 4

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        # Reserve enough vertical room for four single-line texts plus padding. We do not try to
        # word-wrap inside sizeHint; the delegate elides instead, so each row stays a constant
        # height and the list scrolls predictably.
        fm = option.fontMetrics
        line_h = fm.height()
        height = self._ROW_PADDING * 2 + line_h * 4 + self._LINE_SPACING * 3
        return QSize(option.rect.width(), height)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        # Background: let the style draw hover/selection so we honor the QSS palette.
        widget = option.widget
        style = widget.style() if widget is not None else option.styleObject.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, widget)

        rect = option.rect.adjusted(
            self._ROW_PADDING,
            self._ROW_PADDING,
            -self._ROW_PADDING,
            -self._ROW_PADDING,
        )
        fm = option.fontMetrics
        line_h = fm.height()

        title = str(index.data(_TITLE_ROLE) or "")
        url = str(index.data(_URL_ROLE) or "")
        snippet = str(index.data(_SNIPPET_ROLE) or "")
        engine = str(index.data(_ENGINE_ROLE) or "")

        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(option.palette.text().color())
        title_text = fm.elidedText(title or url, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect.left(), rect.top() + fm.ascent(), title_text)

        painter.setFont(option.font)
        painter.setPen(QColor("#3060a8"))
        url_y = rect.top() + line_h + self._LINE_SPACING + fm.ascent()
        url_text = fm.elidedText(url, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect.left(), url_y, url_text)

        if snippet:
            painter.setPen(option.palette.text().color())
            snippet_y = url_y + line_h + self._LINE_SPACING
            snippet_text = fm.elidedText(snippet, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect.left(), snippet_y, snippet_text)

        if engine:
            painter.setPen(QColor("#2a7a2a"))
            engine_y = rect.top() + (line_h + self._LINE_SPACING) * 3 + fm.ascent()
            engine_text = fm.elidedText(f"via {engine}", Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect.left(), engine_y, engine_text)

        painter.restore()


class ResultsView(QListView):
    """A `QListView` over a `QStandardItemModel` of search results.

    Right-clicking a result opens a menu to set a ranking rule for that result's domain; the chosen
    `(domain, RankRule)` is emitted via `ruleRequested` for the window to persist and re-apply.
    """

    # (domain, RankRule) chosen from a result's right-click menu.
    ruleRequested = Signal(str, RankRule)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setItemDelegate(_ResultDelegate(self))
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setUniformItemSizes(True)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.activated.connect(self._on_activated)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        domain = host_of_url(str(index.data(_URL_ROLE) or ""))
        if not domain:
            return
        menu = QMenu(self)
        menu.addAction(f"Domain: {domain}").setEnabled(False)
        menu.addSeparator()
        # NORMAL clears any existing rule for the domain.
        for label, rule in (
            ("Pin to top", RankRule.PIN),
            ("Raise", RankRule.RAISE),
            ("Lower", RankRule.LOWER),
            ("Block", RankRule.BLOCK),
            ("Clear rule", RankRule.NORMAL),
        ):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, r=rule: self.ruleRequested.emit(domain, r)
            )
        menu.exec(event.globalPos())

    def set_results(self, results: Sequence[SearchResult]) -> None:
        """Replace the model contents with `results`."""
        self._model.clear()
        for item in results:
            row = QStandardItem()
            row.setData(item.title, _TITLE_ROLE)
            row.setData(item.url, _URL_ROLE)
            row.setData(item.snippet, _SNIPPET_ROLE)
            row.setData(item.engine, _ENGINE_ROLE)
            # Accessible / screen-reader label: title + url in one string.
            row.setData(f"{item.title}\n{item.url}", Qt.ItemDataRole.DisplayRole)
            self._model.appendRow(row)

    def clear(self) -> None:
        self._model.clear()

    @property
    def result_count(self) -> int:
        return self._model.rowCount()

    def _on_activated(self, index: QModelIndex) -> None:
        url = str(index.data(_URL_ROLE) or "")
        if url:
            QDesktopServices.openUrl(QUrl(url))
