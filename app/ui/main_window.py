"""Main window."""
from __future__ import annotations

import copy
import os
import queue
import threading
import time
import uuid

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction, QDesktopServices, QFont, QKeySequence, QShortcut, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QTableView, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..about import html as about_html
from ..config import Config, data_dir, state_db_path
from ..safety import guarded, record, recent
from ..engine import SyncEngine
from ..ftpclient import FtpError, test_connection
from ..i18n import get_language, set_language, tr, trf
from ..models import Job
from ..state import StateDB
from .dialogs import JobDialog, ServerDialog
from .icon import app_icon
from .table import FileFilterProxy, FileTableModel
from .theme import ACCENT, BLUE, BORDER, ERR, OK, PANEL, TEXT_MUTED, WARN

MAX_LOG_LINES = 4000
MAX_DRAIN_EVENTS = 200      # events handled per UI tick
MAX_DRAIN_SECONDS = 0.03    # time budget per UI tick (keeps animations smooth)

# Windows rebuilt by a language switch would otherwise be garbage collected
# (their only owner is the old window), which makes the app quit by itself.
_KEEP_ALIVE: list = []


class SyncThread(threading.Thread):
    """Runs the engine in the background and pushes UI events into a queue."""

    def __init__(self, cfg: Config, state: StateDB, events: queue.Queue,
                 dry_run: bool, allow_mass: bool):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.state = state
        self.events = events
        self.dry_run = dry_run
        self.allow_mass = allow_mass
        self.cancel_event = threading.Event()
        self.engine: SyncEngine | None = None

    def run(self) -> None:
        try:
            self.engine = SyncEngine(self.cfg, self.state, self.events.put,
                                     dry_run=self.dry_run,
                                     allow_mass_delete=self.allow_mass,
                                     cancel=self.cancel_event)
            self.engine.run()
        except Exception as exc:  # noqa: BLE001
            self.events.put({"type": "log", "text": f"[{tr('异常')}] {exc}"})
            self.events.put({"type": "finished"})
        finally:
            if self.engine:
                self.engine.close()


class _DiagThread(threading.Thread):
    """Runs the server capability probe and posts the report to the UI queue."""

    def __init__(self, cfg, events: queue.Queue, targets=None):
        super().__init__(daemon=True)
        self.cfg = copy.deepcopy(cfg)
        self.events = events
        self.targets = list(targets or [])

    def run(self) -> None:
        import traceback

        from ..diagnose import run as diag_run
        try:
            report = diag_run(self.cfg, targets=self.targets)
            self.events.put({"type": "diag", "text": report.text()})
        except Exception as exc:  # noqa: BLE001 - the report itself must survive
            detail = traceback.format_exc(limit=3)
            self.events.put({"type": "diag",
                             "text": f"[error] {exc.__class__.__name__}: {exc}\n{detail}"})


class _TestThread(threading.Thread):
    def __init__(self, cfg, events: queue.Queue):
        super().__init__(daemon=True)
        self.cfg = copy.deepcopy(cfg)
        self.events = events

    def run(self) -> None:
        try:
            msg = test_connection(self.cfg)
            self.events.put({"type": "test_ok", "text": msg})
        except FtpError as exc:
            self.events.put({"type": "test_err", "text": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self.events.put({"type": "test_err", "text": str(exc)})


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = Config.load()
        self.db = StateDB(str(state_db_path()))
        self.events: queue.Queue = queue.Queue()
        self.model = FileTableModel(self)
        self.proxy = FileFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.worker: SyncThread | None = None
        self.test_worker: _TestThread | None = None
        self._last_summary = None
        self._running = False
        self._next_window = None
        self._skip_confirm = False
        self._finish_pending = False
        self._events_after_last_drain = False
        self._closing = False
        self._diag_worker: _DiagThread | None = None

        self.setWindowTitle(f"{tr('FTP 单向同步')}  v{__version__}")
        self.setWindowIcon(app_icon())
        try:
            w, h = (int(x) for x in str(self.cfg.window).lower().split("x"))
            self.resize(max(1040, w), max(660, h))
        except (ValueError, TypeError):
            self.resize(1280, 820)
        self.setMinimumSize(1040, 660)
        self._build_ui()
        self._build_menu()
        self._refresh_jobs()
        self._refresh_server_bar()

        self.timer = QTimer(self)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self._drain)
        self.timer.start()

        # Responsiveness watchdog: if the UI thread stops turning for longer than
        # WATCHDOG_STALL seconds, record it and make sure the buttons are usable
        # again (a stuck run must never leave the window dead).
        self._heartbeat = time.monotonic()
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.setInterval(250)
        self.heartbeat_timer.timeout.connect(self._beat)
        self.heartbeat_timer.start()
        self._watchdog = threading.Thread(target=self._watch_ui, daemon=True,
                                          name="ui-watchdog")
        self._watchdog.start()

        QShortcut(QKeySequence("F5"), self, self._on_preview)
        QShortcut(QKeySequence("Ctrl+Return"), self, self._on_start)
        QShortcut(QKeySequence("Ctrl+S"), self, self._on_settings)

    # ------------------------------------------------------------------ watchdog
    WATCHDOG_STALL = 5.0        # seconds without a UI turn before we intervene

    @guarded
    def _beat(self) -> None:
        self._heartbeat = time.monotonic()

    def _watch_ui(self) -> None:
        """Background watchdog - never touches widgets, only flags and the log."""
        while not self._closing:
            time.sleep(1.0)
            gap = time.monotonic() - self._heartbeat
            if gap < self.WATCHDOG_STALL:
                continue
            record("UI stall", f"event loop frozen for {gap:.1f}s "
                               f"(running={self._running}, worker_alive="
                               f"{self.worker.is_alive() if self.worker else None})")
            self._heartbeat = time.monotonic()
            # queue an unlock; it will run as soon as the loop breathes again
            try:
                self.events.put({"type": "unlock", "reason": "watchdog"})
            except Exception:
                pass

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(11)

        outer.addLayout(self._build_header())
        outer.addWidget(self._build_server_bar())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_jobs_panel())
        split.addWidget(self._build_detail_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([420, 840])
        outer.addWidget(split, 1)

        outer.addWidget(self._build_footer())
        self.setCentralWidget(central)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(QSize(40, 40)))
        logo.setFixedSize(42, 42)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        t = QLabel(tr("FTP 单向同步"))
        t.setObjectName("title")
        sub = QLabel(tr("把选定的 Windows 文件夹 / 文件镜像到 FTP 服务器"))
        sub.setObjectName("subtitle")
        titles.addWidget(t)
        titles.addWidget(sub)

        self.chip_status = QLabel(tr("就绪"))
        self._set_chip(self.chip_status, tr("就绪"), TEXT_MUTED)

        row.addWidget(logo)
        row.addLayout(titles)
        row.addStretch(1)
        row.addWidget(self.chip_status)
        return row

    def _build_server_bar(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        lbl = QLabel(tr("服务器"))
        lbl.setObjectName("muted")
        self.lbl_server = QLabel(tr("未配置"))
        self.lbl_server.setObjectName("mono")
        self.chip_proto = QLabel("FTP")
        self._set_chip(self.chip_proto, "FTP", BLUE)

        self.btn_test = QPushButton(tr("测试连接"))
        self.btn_test.setObjectName("ghost")
        self.btn_test.clicked.connect(self._on_test_conn)
        self.btn_diag = QPushButton(tr("诊断"))
        self.btn_diag.setObjectName("ghost")
        self.btn_diag.setToolTip(tr("逐项检测服务器的列举/建目录/时间戳能力，结果写入运行日志"))
        self.btn_diag.clicked.connect(self._on_diagnose)
        self.btn_settings = QPushButton(tr("服务器设置"))
        self.btn_settings.setObjectName("ghost")
        self.btn_settings.clicked.connect(self._on_settings)

        lay.addWidget(lbl)
        lay.addWidget(self.lbl_server)
        lay.addWidget(self.chip_proto)
        lay.addStretch(1)
        lay.addWidget(self.btn_diag)
        lay.addWidget(self.btn_test)
        lay.addWidget(self.btn_settings)
        return card

    def _build_jobs_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(380)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(13, 12, 13, 12)
        lay.setSpacing(9)

        head = QHBoxLayout()
        title = QLabel(tr("同步任务"))
        title.setObjectName("sectionTitle")
        self.lbl_jobs = QLabel(tr("0 个"))
        self.lbl_jobs.setObjectName("muted")
        head.addWidget(title)
        head.addWidget(self.lbl_jobs)
        head.addStretch(1)

        btn_add_dir = QPushButton(tr("＋ 文件夹"))
        btn_add_dir.clicked.connect(lambda: self._on_add_job("dir"))
        btn_add_file = QPushButton(tr("＋ 文件"))
        btn_add_file.clicked.connect(lambda: self._on_add_job("file"))
        head.addWidget(btn_add_dir)
        head.addWidget(btn_add_file)

        self.tbl_jobs = QTableWidget(0, 4)
        self.tbl_jobs.setHorizontalHeaderLabels([tr("启用"), tr("本地路径"),
                                                 tr("FTP 目标目录"), tr("最近同步")])
        self.tbl_jobs.verticalHeader().setVisible(False)
        self.tbl_jobs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_jobs.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_jobs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_jobs.setAlternatingRowColors(True)
        self.tbl_jobs.setShowGrid(False)
        self.tbl_jobs.verticalHeader().setDefaultSectionSize(30)
        hh = self.tbl_jobs.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.tbl_jobs.setColumnWidth(0, 46)
        self.tbl_jobs.setColumnWidth(2, 130)
        self.tbl_jobs.setColumnWidth(3, 118)
        self.tbl_jobs.itemChanged.connect(self._on_job_item_changed)
        self.tbl_jobs.itemDoubleClicked.connect(lambda _i: self._on_edit_job())

        foot = QHBoxLayout()
        foot.setSpacing(8)
        btn_edit = QPushButton(tr("编辑"))
        btn_edit.clicked.connect(self._on_edit_job)
        btn_remove = QPushButton(tr("移除"))
        btn_remove.setObjectName("danger")
        btn_remove.clicked.connect(self._on_remove_job)
        btn_open = QPushButton(tr("打开本地"))
        btn_open.setObjectName("ghost")
        btn_open.clicked.connect(self._on_open_local)
        foot.addWidget(btn_edit)
        foot.addWidget(btn_remove)
        foot.addStretch(1)
        foot.addWidget(btn_open)

        lay.addLayout(head)
        lay.addWidget(self.tbl_jobs, 1)
        lay.addLayout(foot)
        return card

    def _build_detail_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(13, 10, 13, 12)
        lay.setSpacing(8)

        self.tabs = QTabWidget()

        # --- files tab
        files = QWidget()
        fl = QVBoxLayout(files)
        fl.setContentsMargins(0, 8, 0, 0)
        fl.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText(tr("搜索路径…"))
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.setFixedWidth(240)
        self.ed_search.textChanged.connect(self.proxy.set_text)
        self.chk_only_changed = QCheckBox(tr("只看变更"))
        self.chk_only_changed.setChecked(True)
        self.chk_only_changed.toggled.connect(self._on_only_changed)
        self.lbl_counts = QLabel("—")
        self.lbl_counts.setObjectName("muted")
        bar.addWidget(self.ed_search)
        bar.addWidget(self.chk_only_changed)
        bar.addStretch(1)
        bar.addWidget(self.lbl_counts)

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(27)
        self.view.setWordWrap(False)
        vh = self.view.horizontalHeader()
        vh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in {1: 84, 2: 140, 3: 82, 4: 72, 5: 84, 6: 140, 7: 150}.items():
            vh.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.view.setColumnWidth(col, width)
        vh.setSortIndicator(0, Qt.SortOrder.AscendingOrder)

        fl.addLayout(bar)
        fl.addWidget(self.view, 1)

        # --- log tab
        logw = QWidget()
        ll = QVBoxLayout(logw)
        ll.setContentsMargins(0, 8, 0, 0)
        ll.setSpacing(6)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(MAX_LOG_LINES)
        font = QFont("Cascadia Mono", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.txt_log.setFont(font)
        row_log = QHBoxLayout()
        btn_clear = QPushButton(tr("清空"))
        btn_clear.setObjectName("ghost")
        btn_clear.clicked.connect(self.txt_log.clear)
        btn_copy = QPushButton(tr("复制全部"))
        btn_copy.setObjectName("ghost")
        btn_copy.clicked.connect(self._copy_log)
        row_log.addWidget(btn_clear)
        row_log.addWidget(btn_copy)
        row_log.addStretch(1)
        ll.addWidget(self.txt_log, 1)
        ll.addLayout(row_log)

        self.tabs.addTab(files, tr("文件明细"))
        self.tabs.addTab(logw, tr("运行日志"))
        lay.addWidget(self.tabs)
        return card

    def _build_footer(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self.lbl_phase = QLabel(tr("准备就绪 · 添加任务后点击“仅预览”或“开始同步”"))
        self.lbl_phase.setObjectName("muted")
        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("mono")
        top.addWidget(self.lbl_phase, 1)
        top.addWidget(self.lbl_progress)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)

        bottom = QHBoxLayout()
        bottom.setSpacing(9)
        self.chk_allow_mass = QCheckBox(tr("允许大批量删除"))
        self.chk_allow_mass.setToolTip(
            tr("当远端需要删除的条目超过保护阈值时，勾选此项才会真正删除"))
        self.lbl_last = QLabel("")
        self.lbl_last.setObjectName("muted")
        self.btn_preview = QPushButton(tr("仅预览"))
        self.btn_preview.setObjectName("ghost")
        self.btn_preview.setMinimumWidth(96)
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_start = QPushButton(tr("开始同步"))
        self.btn_start.setObjectName("primary")
        self.btn_start.setMinimumWidth(112)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_cancel = QPushButton(tr("取消"))
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        bottom.addWidget(self.chk_allow_mass)
        bottom.addWidget(self.lbl_last)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_preview)
        bottom.addWidget(self.btn_start)
        bottom.addWidget(self.btn_cancel)

        lay.addLayout(top)
        lay.addWidget(self.bar)
        lay.addLayout(bottom)
        return card

    def _build_menu(self) -> None:
        bar = self.menuBar()
        m_file = bar.addMenu(tr("文件"))
        act_dir = QAction(tr("打开数据目录"), self)
        act_dir.triggered.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(data_dir()))))
        act_quit = QAction(tr("退出"), self)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_dir)
        m_file.addSeparator()
        m_file.addAction(act_quit)

        m_tool = bar.addMenu(tr("工具"))
        act_set = QAction(tr("服务器设置…"), self)
        act_set.setShortcut("Ctrl+S")
        act_set.triggered.connect(self._on_settings)
        act_test = QAction(tr("测试连接"), self)
        act_test.triggered.connect(self._on_test_conn)
        act_diag = QAction(tr("服务器诊断…"), self)
        act_diag.triggered.connect(self._on_diagnose)
        m_tool.addAction(act_set)
        m_tool.addAction(act_test)
        m_tool.addAction(act_diag)

        m_help = bar.addMenu(tr("帮助"))
        act_crash = QAction(tr("查看崩溃日志"), self)
        act_crash.triggered.connect(self._on_show_crash_log)
        m_help.addAction(act_crash)
        m_help.addSeparator()
        act_about = QAction(tr("关于"), self)
        act_about.triggered.connect(self._on_about)
        m_help.addAction(act_about)

    # ------------------------------------------------------------------ helpers
    def _set_chip(self, label: QLabel, text: str, color: str) -> None:
        label.setText(text)
        label.setStyleSheet(
            f"color:{color}; border:1px solid {color}44; background:{color}18;"
            f"border-radius:10px; padding:2px 10px; font-size:12px;")

    def _log(self, text: str) -> None:
        """Append one line, guaranteeing a line break (appendPlainText can merge)."""
        doc = self.txt_log.document()
        empty = doc.characterCount() <= 1 and not self.txt_log.toPlainText()
        cursor = self.txt_log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not empty:
            cursor.insertText("\n")
        cursor.insertText(text)
        self.txt_log.setTextCursor(cursor)
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy_log(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.txt_log.toPlainText())

    @guarded
    def _refresh_server_bar(self) -> None:
        s = self.cfg.server
        proto = {"ftp": "FTP", "ftps": "FTPS", "ftpsi": tr("FTPS·隐式")}.get(s.protocol, "FTP")
        self._set_chip(self.chip_proto, proto, BLUE)
        if s.host:
            self.lbl_server.setText(f"{s.host}:{s.port}  ·  {s.username or 'anonymous'}")
            self.lbl_server.setStyleSheet(f"color:{TEXT_MUTED};")
        else:
            self.lbl_server.setText(tr("未配置 · 点击右侧“服务器设置”"))
            self.lbl_server.setStyleSheet(f"color:{WARN};")

    @guarded
    def _refresh_jobs(self) -> None:
        self.tbl_jobs.blockSignals(True)
        self.tbl_jobs.setRowCount(len(self.cfg.jobs))
        for i, job in enumerate(self.cfg.jobs):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                         | Qt.ItemFlag.ItemIsSelectable)
            chk.setCheckState(Qt.CheckState.Checked if job.enabled else Qt.CheckState.Unchecked)
            chk.setToolTip(tr("勾选后参与本次同步"))
            self.tbl_jobs.setItem(i, 0, chk)

            src = QTableWidgetItem(job.label if job.name else job.source)
            src.setToolTip(job.source)
            self.tbl_jobs.setItem(i, 1, src)

            dst = QTableWidgetItem(job.remote)
            dst.setToolTip(job.remote)
            self.tbl_jobs.setItem(i, 2, dst)

            last = self.db.last_run(job.id)
            item = QTableWidgetItem(
                time.strftime("%m-%d %H:%M", time.localtime(last)) if last else "—")
            item.setToolTip(tr("最近一次成功运行的时间") if last else tr("尚未同步"))
            self.tbl_jobs.setItem(i, 3, item)
        self.tbl_jobs.blockSignals(False)
        enabled = sum(1 for j in self.cfg.jobs if j.enabled)
        self.lbl_jobs.setText(trf("{total} 个 · 启用 {enabled}",
                                      total=len(self.cfg.jobs), enabled=enabled))
        self._update_counts()

    @guarded
    def _on_job_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        row = item.row()
        if 0 <= row < len(self.cfg.jobs):
            self.cfg.jobs[row].enabled = item.checkState() == Qt.CheckState.Checked
            self.cfg.save()
            enabled = sum(1 for j in self.cfg.jobs if j.enabled)
            self.lbl_jobs.setText(trf("{total} 个 · 启用 {enabled}",
                                      total=len(self.cfg.jobs), enabled=enabled))

    def _current_job(self) -> Job | None:
        row = self.tbl_jobs.currentRow()
        if row is None or row < 0 or row >= len(self.cfg.jobs):
            return None
        return self.cfg.jobs[row]

    def _update_counts(self) -> None:
        c = self.model.counts()
        if c["total"] == 0:
            self.lbl_counts.setText("—")
            return
        text = trf("共 {total} 项 · 变更 {changed}",
                   total=c["total"], changed=c["changed"])
        if c["failed"]:
            text += trf(" · 失败 {failed}", failed=c["failed"])
        self.lbl_counts.setText(text)

    @guarded
    def _on_only_changed(self, flag: bool) -> None:
        self.proxy.set_only_changed(flag)

    # ------------------------------------------------------------------ job actions
    @guarded
    def _on_add_job(self, kind: str) -> None:
        if not self.cfg.server.host:
            if QMessageBox.question(self, tr("提示"), tr("还没有配置 FTP 服务器，现在去配置吗？")) \
                    == QMessageBox.StandardButton.Yes:
                self._on_settings()
            if not self.cfg.server.host:
                return
        job = Job(id=uuid.uuid4().hex[:12], source="", kind=kind, remote="/",
                  enabled=True)
        dlg = JobDialog(job, self.cfg.server, self, kind)
        if dlg.exec() == JobDialog.DialogCode.Accepted:
            self.cfg.jobs.append(dlg.result_job())
            self.cfg.save()
            self._refresh_jobs()
            self._log(tr("已添加任务：") + f"{dlg.result_job().source} → {dlg.result_job().remote}")

    @guarded
    def _on_edit_job(self) -> None:
        job = self._current_job()
        if job is None:
            return
        dlg = JobDialog(job, self.cfg.server, self)
        if dlg.exec() == JobDialog.DialogCode.Accepted:
            new = dlg.result_job()
            idx = self.cfg.jobs.index(job)
            self.cfg.jobs[idx] = new
            self.cfg.save()
            self._refresh_jobs()

    @guarded
    def _on_remove_job(self) -> None:
        job = self._current_job()
        if job is None:
            return
        if QMessageBox.question(
                self, tr("移除任务"),
                tr("移除任务？\n") + job.source
                + tr("\n\n（不会删除任何文件，FTP 上已同步的内容保持不变）")) \
                != QMessageBox.StandardButton.Yes:
            return
        self.cfg.jobs.remove(job)
        self.cfg.save()
        self._refresh_jobs()

    def _on_open_local(self) -> None:
        job = self._current_job()
        if job is None:
            return
        target = job.source if os.path.isdir(job.source) else os.path.dirname(job.source)
        if os.path.isdir(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        else:
            QMessageBox.information(self, tr("打开"), tr("路径不存在。"))

    # ------------------------------------------------------------------ settings
    @guarded
    def _on_settings(self) -> None:
        dlg = ServerDialog(self.cfg.server, self.cfg.options, self,
                           language=self.cfg.language)
        if dlg.exec() != ServerDialog.DialogCode.Accepted:
            return
        server, options = dlg.result_values()
        self.cfg.server = server
        self.cfg.options = options
        new_lang = dlg.result_language()
        if new_lang and new_lang != self.cfg.language:
            self.cfg.language = new_lang
            self.cfg.save()
            set_language(new_lang)
            self._reload_ui()          # labels are built eagerly, so rebuild them
            return
        self.cfg.save()
        self._refresh_server_bar()
        self._log(tr("设置已保存。"))

    @guarded
    def _reload_ui(self) -> None:
        """Rebuild the window so every label picks up the new language."""
        if self._running:
            # a running sync owns the worker/state; rebuilding now would orphan them
            self._log(tr("同步进行中，语言将在下次启动时生效。"))
            return
        self.timer.stop()
        win = MainWindow()
        _KEEP_ALIVE.append(win)          # outlives this window, avoids instant death
        win.show()
        win.raise_()
        win.activateWindow()
        self._next_window = win
        self._skip_confirm = True
        self.close()

    @guarded
    def _on_test_conn(self) -> None:
        if not self.cfg.server.host:
            QMessageBox.information(self, tr("测试连接"), tr("请先配置服务器。"))
            self._on_settings()
            return
        self.btn_test.setEnabled(False)
        self.btn_test.setText(tr("连接中…"))
        self._set_chip(self.chip_status, tr("连接中"), WARN)
        self.test_worker = _TestThread(self.cfg.server, self.events)
        self.test_worker.start()
        self._log(tr("正在连接") + f" {self.cfg.server.host}:{self.cfg.server.port} …")

    @guarded
    def _on_diagnose(self) -> None:
        if not self.cfg.server.host:
            QMessageBox.information(self, tr("诊断"), tr("请先配置服务器。"))
            return
        self.btn_diag.setEnabled(False)
        self.btn_diag.setText(tr("诊断中…"))
        self._log("")
        self._log(tr("开始服务器诊断 …"))
        self.tabs.setCurrentIndex(1)
        targets = [j.remote for j in self.cfg.jobs if j.enabled and j.remote]
        self._diag_worker = _DiagThread(self.cfg.server, self.events, targets)
        self._diag_worker.start()

    @guarded
    def _on_show_crash_log(self) -> None:
        from ..safety import log_path
        text = recent(40000).strip()
        box = QMessageBox(self)
        box.setWindowTitle(tr("查看崩溃日志"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(tr("崩溃日志已保存到：") + log_path())
        box.setDetailedText(text or tr("（暂无记录）"))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        self.tabs.setCurrentIndex(1)
        if text:
            self._log(tr("崩溃日志已保存到：") + log_path())

    @guarded
    def _on_about(self) -> None:
        # text lives in about.py so `--about` prints exactly the same thing.
        # data_dir() returns a Path - interpolate it, do not concatenate.
        trailing = f"{tr('配置目录：')}{data_dir()}"
        QMessageBox.about(self, tr("关于"), about_html(tr, trailing=trailing))

    # ------------------------------------------------------------------ running
    def _validate(self) -> bool:
        if not self.cfg.server.host:
            QMessageBox.warning(self, tr("无法开始"), tr("请先配置并保存 FTP 服务器。"))
            return False
        jobs = [j for j in self.cfg.jobs if j.enabled]
        if not jobs:
            QMessageBox.warning(self, tr("无法开始"), tr("请先添加并启用至少一个同步任务。"))
            return False
        missing = [j.source for j in jobs if not os.path.exists(j.source)]
        if missing:
            QMessageBox.warning(self, tr("源路径不存在"),
                                tr("以下源路径不存在，请先修正：\n")
                                + "\n".join(missing[:6]))
            return False
        return True

    @guarded
    def _on_preview(self) -> None:
        self._start(dry_run=True)

    @guarded
    def _on_start(self) -> None:
        self._start(dry_run=False)

    def _start(self, dry_run: bool) -> None:
        if self._running or not self._validate():
            return
        self.cfg.save()
        self.model.clear()
        self._update_counts()
        self.bar.setValue(0)
        self.lbl_progress.setText("")
        self._running = True
        self.btn_start.setEnabled(False)
        self.btn_preview.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.chk_allow_mass.setEnabled(False)
        self._set_chip(self.chip_status, tr("预览中") if dry_run else tr("同步中"), ACCENT)
        self._log("")
        self._log("═" * 62)

        while not self.events.empty():
            try:
                self.events.get_nowait()
            except queue.Empty:
                break

        self.worker = SyncThread(copy.deepcopy(self.cfg), self.db, self.events,
                                 dry_run=dry_run,
                                 allow_mass=self.chk_allow_mass.isChecked())
        self.worker.start()

    @guarded
    def _on_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel_event.set()
            self._set_chip(self.chip_status, tr("正在取消"), WARN)
            self.lbl_phase.setText(tr("正在取消，等待当前文件传输结束…"))
            self.btn_cancel.setEnabled(False)

    @guarded
    def _finish_run(self) -> None:
        self._finish_pending = False
        self._running = False
        self.btn_start.setEnabled(True)
        self.btn_preview.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.chk_allow_mass.setEnabled(True)
        self.worker = None
        self._refresh_jobs()

    # ------------------------------------------------------------------ events
    @guarded
    def _drain(self) -> None:
        """Pump the engine's events into the UI without ever freezing it.

        Two hard rules keep the window responsive:
          * a *time budget* per turn, not just an event count - a burst of row
            updates used to keep this slot busy for seconds, which looks exactly
            like "the app stopped responding";
          * run completion is decided by the worker thread being finished, not by
            the queue being empty.  If an event arrived after the worker stopped
            the queue never went empty and the buttons stayed disabled forever.
        """
        deadline = time.monotonic() + MAX_DRAIN_SECONDS
        processed = 0
        while processed < MAX_DRAIN_EVENTS and time.monotonic() < deadline:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            processed += 1
            self._handle(ev)
        if processed:
            self._events_after_last_drain = not self.events.empty()
        if self._finish_pending and self.events.empty():
            self._finish_run()

        if self.test_worker is not None and not self.test_worker.is_alive():
            self.test_worker = None

        # leave the remaining events for the next tick, but still finish the run
        if self._running and self.worker is not None and not self.worker.is_alive():
            if self.events.empty():
                self._finish_run()
            else:
                self._finish_pending = True

    @guarded
    def _handle(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "log":
            self._log(ev["text"])
        elif kind == "phase":
            self.lbl_phase.setText(ev["text"])
        elif kind == "rows":
            rows = ev.get("rows") or []
            self.model.append_rows(rows)
            self._update_counts()
        elif kind == "row":
            self.model.update_row(ev.get("key", ""), ev.get("status"),
                                  ev.get("message"), ev.get("synced_at") or 0.0)
        elif kind == "progress":
            done, total = ev.get("done", 0), max(1, ev.get("total", 1))
            pct = int(min(100, done * 100 / total))
            self.bar.setValue(pct)
            sent = ev.get("bytes", 0) / 1048576
            self.lbl_progress.setText(f"{done}/{total}" + (f" · {sent:.1f} MB" if sent else ""))
        elif kind == "summary":
            s = ev["summary"]
            self._last_summary = s
            self.bar.setValue(100 if not s.aborted else self.bar.value())
            self.lbl_phase.setText(
                (tr("已取消 · ") if s.aborted else tr("完成 · ")) + s.short()
                + trf(" · 用时 {s}s", s=f"{s.elapsed:.1f}"))
            color = ERR if s.failed else (WARN if s.aborted else OK)
            self._set_chip(self.chip_status,
                           tr("失败") if s.failed else
                           (tr("已取消") if s.aborted else tr("完成")), color)
            self.lbl_last.setText(tr("最近一次：") + time.strftime(
                "%Y-%m-%d %H:%M", time.localtime()))
            self._update_counts()
            if s.messages:
                for m in s.messages[:8]:
                    self._log(f"[{tr('摘要')}] {m}")
        elif kind == "test_ok":
            self.btn_test.setEnabled(True)
            self.btn_test.setText(tr("测试连接"))
            self._set_chip(self.chip_status, tr("已连接"), OK)
            self._log(f"[{tr('连接')}] {ev['text']}")
            self.lbl_phase.setText(ev["text"])
        elif kind == "test_err":
            self.btn_test.setEnabled(True)
            self.btn_test.setText(tr("测试连接"))
            self._set_chip(self.chip_status, tr("连接失败"), ERR)
            self._log(f"[{tr('连接失败')}] {ev['text']}")
            self.lbl_phase.setText(tr("连接失败：") + ev["text"])
        elif kind == "unlock":
            # the UI thread was blocked; restore a usable state
            if self._running and (self.worker is None or not self.worker.is_alive()):
                self._finish_run()
            self.btn_preview.setEnabled(True)
            self.btn_start.setEnabled(True)
            self.btn_cancel.setEnabled(self._running)
            self._set_chip(self.chip_status,
                           tr("失败") if self._running else tr("完成"),
                           WARN if self._running else OK)
            self._log(tr("界面曾短暂无响应，已自动恢复；如再次发生请打开“查看崩溃日志”。"))
        elif kind == "diag":
            self.btn_diag.setEnabled(True)
            self.btn_diag.setText(tr("诊断"))
            text = (ev.get("text") or "").strip()
            self._log(text or tr("诊断没有返回任何内容"))
            self._log(tr("诊断结束，报告可直接复制给我。"))
        elif kind == "finished":
            pass

    # ------------------------------------------------------------------ close
    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        if self._running and self.worker is not None and not getattr(self, "_skip_confirm", False):
            if QMessageBox.question(self, tr("正在同步"), tr("同步正在进行，确定退出吗？")) \
                    != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel_event.set()
            self.worker.join(timeout=5)
        try:
            self.cfg.window = f"{self.width()}x{self.height()}"
            self.cfg.save()
        except Exception as exc:  # noqa: BLE001
            record("saving window size failed", str(exc))
        if self.worker is not None and self.worker.is_alive():
            # still finishing: let it own the database, exit anyway
            self.worker = None
        else:
            try:
                self.db.close()
            except Exception as exc:  # noqa: BLE001
                record("closing state db failed", str(exc))
        super().closeEvent(event)
