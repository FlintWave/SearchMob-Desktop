"""Results list backed by a `QStandardItemModel`. Click opens the URL in the system browser.

The Android `SearchScreen` shows a card per result with bold title, body snippet, and a small
engine badge. Here a `QListView` with a custom delegate gives the same shape without the cost of
laying out N `QWidget`s. The delegate draws title, URL (muted), snippet, and engine badge in
one item.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QDesktopServices,
    QFont,
    QPainter,
    QPen,
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
from searchmob_desktop.gui.theme import active_palette

# Custom roles so the delegate does not have to parse the visible string back into fields.
_TITLE_ROLE = Qt.ItemDataRole.UserRole + 1
_URL_ROLE = Qt.ItemDataRole.UserRole + 2
_SNIPPET_ROLE = Qt.ItemDataRole.UserRole + 3
_ENGINE_ROLE = Qt.ItemDataRole.UserRole + 4


class _ResultDelegate(QStyledItemDelegate):
    """Paint a result row: title (bold), URL (muted), snippet (small), engine (badge color)."""

    # Outer margin between the item rect edge and the drawn card (the list also sets `spacing`,
    # so cards never touch). Inner padding is the gap from the card edge to the text.
    _CARD_MARGIN = 3
    _CARD_PADDING = 14
    _CARD_RADIUS = 12
    _LINE_SPACING = 4

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        # Reserve enough vertical room for four single-line texts plus card padding and margin. We
        # do not word-wrap inside sizeHint; the delegate elides instead, so each row stays a
        # constant height and the list scrolls predictably.
        fm = option.fontMetrics
        line_h = fm.height()
        height = (
            self._CARD_MARGIN * 2 + self._CARD_PADDING * 2 + line_h * 4 + self._LINE_SPACING * 3
        )
        return QSize(option.rect.width(), height)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        palette = active_palette()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Draw a rounded card filling the item rect (minus the outer margin). Hover/selection get a
        # lighter fill and an accent hairline so the active row reads clearly.
        card_rect = QRectF(option.rect).adjusted(
            self._CARD_MARGIN,
            self._CARD_MARGIN,
            -self._CARD_MARGIN,
            -self._CARD_MARGIN,
        )
        state = option.state
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        selected = bool(state & QStyle.StateFlag.State_Selected)
        fill = palette.card_hover if (hovered or selected) else palette.card
        painter.setBrush(QColor(fill))
        if selected:
            painter.setPen(QPen(QColor(palette.accent), 1))
        else:
            painter.setPen(QPen(QColor(palette.border), 1))
        painter.drawRoundedRect(card_rect, self._CARD_RADIUS, self._CARD_RADIUS)

        # Text area: inside the card by the inner padding.
        rect = card_rect.adjusted(
            self._CARD_PADDING,
            self._CARD_PADDING,
            -self._CARD_PADDING,
            -self._CARD_PADDING,
        ).toRect()
        fm = option.fontMetrics
        line_h = fm.height()

        title = str(index.data(_TITLE_ROLE) or "")
        url = str(index.data(_URL_ROLE) or "")
        snippet = str(index.data(_SNIPPET_ROLE) or "")
        engine = str(index.data(_ENGINE_ROLE) or "")

        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(palette.text))
        title_text = fm.elidedText(title or url, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect.left(), rect.top() + fm.ascent(), title_text)

        painter.setFont(option.font)
        painter.setPen(QColor(palette.url))
        url_y = rect.top() + line_h + self._LINE_SPACING + fm.ascent()
        url_text = fm.elidedText(url, Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect.left(), url_y, url_text)

        if snippet:
            painter.setPen(QColor(palette.muted))
            snippet_y = url_y + line_h + self._LINE_SPACING
            snippet_text = fm.elidedText(snippet, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect.left(), snippet_y, snippet_text)

        if engine:
            painter.setPen(QColor(palette.engine))
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
    # (url, row) emitted when a result is opened, so the window can learn from the click (the row is
    # the displayed position, which the personalization model needs for its skip-above signal).
    resultActivated = Signal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setItemDelegate(_ResultDelegate(self))
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setUniformItemSizes(True)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)  # so hover repaints the card under the cursor
        self.setSpacing(4)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        # Single left-click opens the result, matching the served page (a plain link) so a result
        # is never "unclickable". `clicked` is the single-click signal; `activated` is kept for the
        # keyboard path (Enter) and platforms whose style activates on a single click. Right-click
        # is unaffected (it raises the ranking menu via contextMenuEvent).
        self.clicked.connect(self._on_activated)
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
            # Tell the window first (so it can learn from the click) and then open the URL.
            self.resultActivated.emit(url, index.row())
            QDesktopServices.openUrl(QUrl(url))
