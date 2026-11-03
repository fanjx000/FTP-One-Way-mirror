"""Qt table model for the per-file detail view (virtualised, handles 100k+ rows)."""
from __future__ import annotations

import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from ..i18n import tr
from ..models import A_SKIP, Row, action_label, status_label
from .theme import ACTION_COLORS, TEXT, TEXT_MUTED

COLUMNS = ["相对路径", "大小", "本地修改时间", "动作", "状态", "远端大小", "上次同步", "说明"]
DIM = "#7c8698"
OK_C = "#3ddc97"
ERR_C = "#ff6b6b"


def human_size(n: int) -> str:
    if n is None or n < 0:
        return "—"
    if n < 1024:
        return f"{n} B"
    val = float(n) / 1024
    for unit in ("KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.1f} {unit}" if val < 10 else f"{val:.0f} {unit}"
        val /= 1024
    return f"{n} B"


def human_time(epoch: float) -> str:
    if not epoch:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))
    except (OSError, ValueError):
        return "—"


class FileTableModel(QAbstractTableModel):
    SORT_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[Row] = []
        self._index: dict[str, int] = {}

    # ---- Qt API ---------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return tr(COLUMNS[section])
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        i, col = index.row(), index.column()
        # A sorted/filtered proxy can ask for a row that vanished after a model
        # reset; raising here happens inside Qt's paint loop and kills the app.
        if not (0 <= i < len(self._rows)) or not (0 <= col < len(COLUMNS)):
            return None
        row = self._rows[i]

        if role == Qt.DisplayRole:
            if col == 0:
                return row.rel + "/" if row.is_dir and not row.rel.endswith("/") else row.rel
            if col == 1:
                return "—" if row.is_dir else human_size(row.size)
            if col == 2:
                return "—" if row.is_dir else human_time(row.mtime)
            if col == 3:
                return action_label(row.action)
            if col == 4:
                return status_label(row.status)
            if col == 5:
                return human_size(row.remote_size) if row.remote_size else "—"
            if col == 6:
                return human_time(row.synced_at)
            if col == 7:
                return row.message
            return None

        if role == self.SORT_ROLE:
            if col == 1:
                return row.size
            if col == 2:
                return row.mtime
            if col == 5:
                return row.remote_size
            if col == 6:
                return row.synced_at
            return self.data(index, Qt.DisplayRole) or ""

        if role == Qt.ToolTipRole:
            tip = row.remote_path or row.rel
            return f"{tip}\n{row.message}" if row.message else tip

        if role == Qt.ForegroundRole:
            if col == 3:
                return QColor(ACTION_COLORS.get(row.action, TEXT))
            if col == 4:
                color = OK_C if row.status == "done" else ERR_C if row.status == "failed" else TEXT_MUTED
                return QColor(color)
            if row.action == A_SKIP and col in (0, 1, 2):
                return QColor(DIM)
            return None

        if role == Qt.TextAlignmentRole and col in (1, 5):
            return int(Qt.AlignRight | Qt.AlignVCenter)

        return None

    # ---- data helpers ---------------------------------------------------
    def clear(self) -> None:
        self.beginResetModel()
        self._rows = []
        self._index = {}
        self.endResetModel()

    def set_rows(self, rows: list[Row]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._index = {r.key: i for i, r in enumerate(self._rows)}
        self.endResetModel()

    def append_rows(self, rows: list[Row]) -> None:
        if not rows:
            return
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
        for r in rows:
            self._index[r.key] = len(self._rows)
            self._rows.append(r)
        self.endInsertRows()

    def update_row(self, key: str, status: str | None = None, message: str | None = None,
                   synced_at: float = 0.0) -> None:
        idx = self._index.get(key)
        if idx is None:
            return
        row = self._rows[idx]
        if status:
            row.status = status
        if message is not None:
            row.message = message
        if synced_at:
            row.synced_at = synced_at
        last = len(COLUMNS) - 1
        left, right = self.index(idx, 0), self.index(idx, last)
        if not (left.isValid() and right.isValid()):
            return
        self.dataChanged.emit(left, right, [Qt.DisplayRole, Qt.ForegroundRole])

    def row_at(self, i: int) -> Row | None:
        return self._rows[i] if 0 <= i < len(self._rows) else None

    def counts(self) -> dict:
        out = {"total": len(self._rows), "changed": 0, "failed": 0}
        for r in self._rows:
            if r.action != A_SKIP:
                out["changed"] += 1
            if r.status == "failed":
                out["failed"] += 1
        return out


class FileFilterProxy(QSortFilterProxyModel):
    """Filter by free text, 'only changed' and per-job selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(FileTableModel.SORT_ROLE)
        self.setDynamicSortFilter(True)
        self._text = ""
        self._only_changed = False
        self._job_id: str | None = None

    def set_text(self, text: str) -> None:
        self._text = (text or "").strip().lower()
        self.invalidateFilter()

    def set_only_changed(self, flag: bool) -> None:
        self._only_changed = bool(flag)
        self.invalidateFilter()

    def set_job(self, job_id: str | None) -> None:
        self._job_id = job_id
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, parent) -> bool:
        model = self.sourceModel()
        if model is None:
            return True
        row = model.row_at(source_row)
        if row is None:
            return True
        if self._job_id and row.job_id != self._job_id:
            return False
        if self._only_changed and row.action == A_SKIP:
            return False
        if self._text and self._text not in row.rel.lower():
            return False
        return True
