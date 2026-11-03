"""Dialogs: server settings (3 tabs), job editor, remote folder picker."""
from __future__ import annotations

import copy
import os
import posixpath
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import Options, ServerConfig
from ..ftpclient import FtpError, FtpSession, norm_remote, test_connection
from ..i18n import LANGUAGES, get_language, tr, trf
from ..models import Job
from .theme import BORDER, ERR, OK, TEXT_MUTED


def _sep() -> QWidget:
    w = QWidget()
    w.setFixedHeight(1)
    w.setStyleSheet(f"background:{BORDER};")
    return w


class _ProbeSignals(QObject):
    """Carrier for the probe result (emitted from a worker thread)."""

    done = Signal(bool, str)


class _TestWorker:
    """Connection probe on a plain thread.

    Deliberately *not* a QThread: a QThread owned by a dialog aborts the whole
    process ("Destroyed while thread is still running") when the user closes the
    dialog while a test is in flight.  A plain daemon thread plus a queued signal
    has no such ownership problem.
    """

    def __init__(self, cfg: ServerConfig, on_done) -> None:
        self.signals = _ProbeSignals()
        self.signals.done.connect(on_done)      # auto -> queued across threads
        self._cfg = copy.deepcopy(cfg)
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="conn-test")

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            self.signals.done.emit(True, test_connection(self._cfg))
        except FtpError as exc:
            self.signals.done.emit(False, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.signals.done.emit(False, f"{exc}")


# --------------------------------------------------------------------------- server
class ServerDialog(QDialog):
    """Server + sync options + exclude patterns."""

    def __init__(self, server: ServerConfig, options: Options, parent=None,
                 language: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("设置"))
        self.setMinimumWidth(600)
        self._server = copy.deepcopy(server)
        self._options = copy.deepcopy(options)
        self._language = language or get_language()
        self._test_worker: _TestWorker | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), tr("常规"))
        tabs.addTab(self._build_server_tab(), tr("服务器"))
        tabs.addTab(self._build_options_tab(), tr("同步选项"))
        tabs.addTab(self._build_exclude_tab(), tr("排除规则"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("保存"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 14)
        lay.setSpacing(12)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    # ---- general tab ----------------------------------------------------
    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(6, 14, 6, 6)
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cb_lang = QComboBox()
        for code, name in LANGUAGES:
            self.cb_lang.addItem(name, code)     # language names stay untranslated
        idx = self.cb_lang.findData(self._language)
        self.cb_lang.setCurrentIndex(max(0, idx))

        hint = QLabel(tr("切换语言后界面会立即重新加载。"))
        hint.setObjectName("muted")
        hint.setWordWrap(True)

        form.addRow(tr("界面语言"), self.cb_lang)
        form.addRow("", hint)
        return w

    def result_language(self) -> str:
        return self._language

    # ---- server tab -----------------------------------------------------
    def _build_server_tab(self) -> QWidget:
        s = self._server
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(6, 14, 6, 6)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cb_proto = QComboBox()
        self.cb_proto.addItem("FTP", "ftp")
        self.cb_proto.addItem(tr("FTPS（显式 TLS）"), "ftps")
        self.cb_proto.addItem(tr("FTPS（隐式 TLS，990）"), "ftpsi")
        idx = max(0, self.cb_proto.findData(s.protocol))
        self.cb_proto.setCurrentIndex(idx)
        self.cb_proto.currentIndexChanged.connect(self._on_proto_changed)

        self.ed_host = QLineEdit(s.host)
        self.ed_host.setPlaceholderText(tr("例如 192.168.1.10 或 ftp.example.com"))
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(s.port or 21)
        row_host = QHBoxLayout()
        row_host.setSpacing(8)
        row_host.addWidget(self.ed_host, 1)
        row_host.addWidget(QLabel(tr("端口")))
        row_host.addWidget(self.sp_port)
        w_host = QWidget()
        w_host.setLayout(row_host)
        row_host.setContentsMargins(0, 0, 0, 0)

        self.ed_user = QLineEdit(s.username)
        self.ed_pass = QLineEdit(s.password)
        self.ed_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_pass.setPlaceholderText(tr("留空表示匿名登录"))
        chk_show = QCheckBox(tr("显示"))
        chk_show.toggled.connect(
            lambda on: self.ed_pass.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        row_pwd = QHBoxLayout()
        row_pwd.setSpacing(8)
        row_pwd.addWidget(self.ed_pass, 1)
        row_pwd.addWidget(chk_show)
        w_pwd = QWidget()
        w_pwd.setLayout(row_pwd)
        row_pwd.setContentsMargins(0, 0, 0, 0)

        self.cb_enc = QComboBox()
        for label, val in [("UTF-8（推荐）", "utf-8"), ("GBK（部分国产 FTP）", "gbk"),
                           ("Latin-1", "latin-1")]:
            self.cb_enc.addItem(tr(label), val)
        self.cb_enc.setCurrentIndex(max(0, self.cb_enc.findData(s.encoding)))

        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(5, 600)
        self.sp_timeout.setSuffix(tr(" 秒"))
        self.sp_timeout.setValue(s.timeout)

        self.sp_conc = QSpinBox()
        self.sp_conc.setRange(1, 8)
        self.sp_conc.setValue(s.concurrency)
        lbl_conc = QLabel(tr("同时上传的文件数（连接数），1~8"))
        lbl_conc.setObjectName("muted")

        self.chk_passive = QCheckBox(tr("被动模式（PASV，推荐）"))
        self.chk_passive.setChecked(s.passive)
        self.chk_tls = QCheckBox(tr("校验证书（自签名证书请勿勾选）"))
        self.chk_tls.setChecked(s.verify_tls)

        form.addRow(tr("协议"), self.cb_proto)
        form.addRow(tr("服务器"), w_host)
        form.addRow(tr("用户名"), self.ed_user)
        form.addRow(tr("密码"), w_pwd)
        form.addRow(tr("字符编码"), self.cb_enc)
        form.addRow(tr("超时"), self.sp_timeout)
        form.addRow(tr("并发"), self.sp_conc)
        form.addRow("", lbl_conc)
        form.addRow("", self.chk_passive)
        form.addRow("", self.chk_tls)

        self.btn_test = QPushButton(tr("测试连接"))
        self.btn_test.clicked.connect(self._on_test)
        self.lbl_test = QLabel("")
        self.lbl_test.setWordWrap(True)
        row_test = QHBoxLayout()
        row_test.addWidget(self.btn_test)
        row_test.addWidget(self.lbl_test, 1)
        w_test = QWidget()
        w_test.setLayout(row_test)
        row_test.setContentsMargins(0, 0, 0, 0)
        form.addRow("", w_test)
        return w

    def _on_proto_changed(self) -> None:
        proto = self.cb_proto.currentData()
        if proto == "ftpsi" and self.sp_port.value() in (21, 990):
            self.sp_port.setValue(990)
        elif proto != "ftpsi" and self.sp_port.value() == 990:
            self.sp_port.setValue(21)

    def _collect_server(self) -> ServerConfig:
        s = copy.deepcopy(self._server)
        s.protocol = self.cb_proto.currentData()
        s.host = self.ed_host.text().strip()
        s.port = self.sp_port.value()
        s.username = self.ed_user.text().strip() or "anonymous"
        if self.ed_pass.text() or not s.password_token:
            s.set_password(self.ed_pass.text())
        s.encoding = self.cb_enc.currentData()
        s.timeout = self.sp_timeout.value()
        s.concurrency = self.sp_conc.value()
        s.passive = self.chk_passive.isChecked()
        s.verify_tls = self.chk_tls.isChecked()
        return s

    def _on_test(self) -> None:
        cfg = self._collect_server()
        if not cfg.host:
            self.lbl_test.setText(tr("请先填写服务器地址"))
            self.lbl_test.setStyleSheet(f"color:{ERR};")
            return
        self.btn_test.setEnabled(False)
        self.lbl_test.setText(tr("正在连接…"))
        self.lbl_test.setStyleSheet(f"color:{TEXT_MUTED};")
        self._test_worker = _TestWorker(cfg, self._on_test_done)
        self._test_worker.start()

    def _on_test_done(self, ok: bool, msg: str) -> None:
        self.btn_test.setEnabled(True)
        self.lbl_test.setText(msg)
        self.lbl_test.setStyleSheet(f"color:{OK if ok else ERR};")

    # ---- tab 2 ----------------------------------------------------------
    def _build_options_tab(self) -> QWidget:
        o = self._options
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 14, 6, 6)
        lay.setSpacing(9)

        self.chk_delete = QCheckBox(tr("删除远端多余的文件/文件夹（单向镜像，保持与本地一致）"))
        self.chk_delete.setChecked(o.delete_remote_extras)
        self.chk_mtime = QCheckBox(tr("上传后把修改时间同步到 FTP（下次对比更快）"))
        self.chk_mtime.setChecked(o.preserve_mtime)
        self.chk_guard = QCheckBox(tr("大批量删除保护：单次删除超过阈值时先跳过"))
        self.chk_guard.setChecked(o.mass_delete_guard)

        row_pct = QHBoxLayout()
        row_pct.setSpacing(8)
        self.sp_pct = QSpinBox()
        self.sp_pct.setRange(1, 100)
        self.sp_pct.setSuffix(" %")
        self.sp_pct.setValue(o.mass_delete_percent)
        self.sp_min = QSpinBox()
        self.sp_min.setRange(1, 10000)
        self.sp_min.setSuffix(tr(" 项"))
        self.sp_min.setValue(o.mass_delete_min)
        row_pct.addWidget(QLabel(tr("删除比例超过")))
        row_pct.addWidget(self.sp_pct)
        row_pct.addWidget(QLabel(tr("且不少于")))
        row_pct.addWidget(self.sp_min)
        row_pct.addStretch(1)
        w_pct = QWidget()
        w_pct.setLayout(row_pct)
        row_pct.setContentsMargins(24, 0, 0, 0)

        self.sp_retries = QSpinBox()
        self.sp_retries.setRange(0, 5)
        self.sp_retries.setSuffix(tr(" 次"))
        self.sp_retries.setValue(o.retries)
        row_retry = QHBoxLayout()
        row_retry.setSpacing(8)
        row_retry.addWidget(QLabel(tr("传输失败自动重试")))
        row_retry.addWidget(self.sp_retries)
        row_retry.addStretch(1)
        w_retry = QWidget()
        w_retry.setLayout(row_retry)
        row_retry.setContentsMargins(0, 0, 0, 0)

        self.chk_reparse = QCheckBox(tr("跟随符号链接 / 目录联接（默认关闭，避免循环）"))
        self.chk_reparse.setChecked(o.follow_reparse)
        self.chk_hidden = QCheckBox(tr("跳过隐藏文件与文件夹"))
        self.chk_hidden.setChecked(o.skip_hidden)
        self.chk_cloud = QCheckBox(tr("不下载 OneDrive 未缓存的云端文件（这些文件将不会上传）"))
        self.chk_cloud.setChecked(o.skip_cloud_only)
        self.chk_cloud.setToolTip(
            tr("OneDrive 的“按需文件”在本机只是占位符，读取时会触发下载。\n"
                  "若只想同步已经下载到本地的内容，勾选此项。"))

        note = QLabel(tr("始终以 Windows 侧为准单向覆盖 FTP；首次建议先“仅预览”。"))
        note.setWordWrap(True)
        note.setObjectName("muted")

        lay.addWidget(self.chk_delete)
        lay.addWidget(self.chk_mtime)
        lay.addWidget(self.chk_guard)
        lay.addWidget(w_pct)
        lay.addWidget(_sep())
        lay.addWidget(w_retry)
        lay.addWidget(self.chk_reparse)
        lay.addWidget(self.chk_hidden)
        lay.addWidget(self.chk_cloud)
        lay.addStretch(1)
        note.setMinimumHeight(note.sizeHint().height())
        lay.addWidget(note)
        return w

    # ---- tab 3 ----------------------------------------------------------
    def _build_exclude_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 14, 6, 6)
        lay.setSpacing(8)
        hint = QLabel(tr("每行一个通配符，匹配文件名或相对路径（不区分大小写），如 ~$*、*.tmp"))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        self.ed_excl = QPlainTextEdit("\n".join(self._options.excludes))
        self.ed_excl.setPlaceholderText("Thumbs.db\n~$*")
        hint.setMinimumHeight(hint.sizeHint().height())
        lay.addWidget(hint)
        lay.addWidget(self.ed_excl, 1)
        return w

    # ---- result ---------------------------------------------------------
    def _on_ok(self) -> None:
        cfg = self._collect_server()
        if not cfg.host:
            QMessageBox.warning(self, tr("设置"), tr("请填写服务器地址。"))
            return
        self._server = cfg
        o = self._options
        o.delete_remote_extras = self.chk_delete.isChecked()
        o.preserve_mtime = self.chk_mtime.isChecked()
        o.mass_delete_guard = self.chk_guard.isChecked()
        o.mass_delete_percent = self.sp_pct.value()
        o.mass_delete_min = self.sp_min.value()
        o.retries = self.sp_retries.value()
        o.follow_reparse = self.chk_reparse.isChecked()
        o.skip_hidden = self.chk_hidden.isChecked()
        o.skip_cloud_only = self.chk_cloud.isChecked()
        self._language = self.cb_lang.currentData() or self._language
        o.excludes = [ln.strip() for ln in self.ed_excl.toPlainText().splitlines() if ln.strip()]
        self.accept()

    def result_values(self) -> tuple[ServerConfig, Options]:
        return self._server, self._options


# --------------------------------------------------------------------------- job
class JobDialog(QDialog):
    def __init__(self, job: Job, server: ServerConfig, parent=None, kind: str = "dir"):
        super().__init__(parent)
        self.server = server
        self.job = copy.deepcopy(job)
        self.job.kind = job.kind or kind
        is_dir = self.job.kind == "dir"
        self.setWindowTitle(tr("编辑同步任务") if job.source else
                            (tr("添加文件夹") if is_dir else tr("添加文件")))
        self.setMinimumWidth(620)

        form = QFormLayout()
        form.setSpacing(11)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ed_source = QLineEdit(self.job.source)
        self.ed_source.setPlaceholderText("C:\\Users\\me\\Documents")
        btn_src = QPushButton(tr("浏览…"))
        btn_src.clicked.connect(self._pick_source)
        row_src = QHBoxLayout()
        row_src.setSpacing(8)
        row_src.addWidget(self.ed_source, 1)
        row_src.addWidget(btn_src)
        w_src = QWidget()
        w_src.setLayout(row_src)
        row_src.setContentsMargins(0, 0, 0, 0)

        self.ed_remote = QLineEdit(self.job.remote or "/")
        self.ed_remote.setPlaceholderText("/backup/Documents")
        btn_remote = QPushButton(tr("浏览远端…"))
        btn_remote.clicked.connect(self._pick_remote)
        row_remote = QHBoxLayout()
        row_remote.setSpacing(8)
        row_remote.addWidget(self.ed_remote, 1)
        row_remote.addWidget(btn_remote)
        w_remote = QWidget()
        w_remote.setLayout(row_remote)
        row_remote.setContentsMargins(0, 0, 0, 0)

        self.ed_name = QLineEdit(self.job.name)
        self.ed_name.setPlaceholderText(tr("可选，便于识别"))

        self.chk_enabled = QCheckBox(tr("启用此任务"))
        self.chk_enabled.setChecked(self.job.enabled)

        hint = QLabel(tr("远端目录会自动创建；本地文件夹结构会原样复制到该目录下。"))
        hint.setWordWrap(True)
        hint.setObjectName("muted")

        form.addRow(tr("本地文件夹") if is_dir else tr("本地文件"), w_src)
        form.addRow(tr("FTP 目标目录"), w_remote)
        form.addRow(tr("备注名称"), self.ed_name)
        form.addRow("", self.chk_enabled)
        form.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("确定"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 14)
        lay.setSpacing(14)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def _pick_source(self) -> None:
        if self.job.kind == "dir":
            path = QFileDialog.getExistingDirectory(self, tr("选择要同步的文件夹"),
                                                    self.ed_source.text() or os.path.expanduser("~"))
        else:
            path, _ = QFileDialog.getOpenFileName(self, tr("选择要同步的文件"),
                                                 self.ed_source.text() or os.path.expanduser("~"))
        if path:
            self.ed_source.setText(os.path.normpath(path))

    def _pick_remote(self) -> None:
        dlg = RemotePickerDialog(self.server, self.ed_remote.text() or "/", self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_path:
            self.ed_remote.setText(dlg.selected_path)

    def _on_ok(self) -> None:
        src = self.ed_source.text().strip()
        remote = self.ed_remote.text().strip()
        if not src:
            QMessageBox.warning(self, tr("任务"), tr("请选择本地路径。"))
            return
        if not os.path.exists(src):
            if QMessageBox.question(self, tr("任务"),
                                   tr("路径当前不存在：\n") + src
                                   + tr("\n\n仍然保存吗？")) \
                    != QMessageBox.StandardButton.Yes:
                return
        if not remote:
            remote = "/"
        if not remote.startswith("/"):
            remote = "/" + remote
        self.job.source = os.path.normpath(src)
        self.job.kind = "dir" if os.path.isdir(src) else ("file" if os.path.isfile(src)
                                                         else self.job.kind)
        self.job.remote = norm_remote(remote)
        self.job.name = self.ed_name.text().strip()
        self.job.enabled = self.chk_enabled.isChecked()
        self.accept()

    def result_job(self) -> Job:
        return self.job


# --------------------------------------------------------------------------- picker
class RemotePickerDialog(QDialog):
    """Simple remote directory browser."""

    def __init__(self, server: ServerConfig, start: str = "/", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("选择 FTP 目标目录"))
        self.resize(520, 460)
        self.server = copy.deepcopy(server)
        self.selected_path = norm_remote(start)
        self._session: FtpSession | None = None

        self.ed_path = QLineEdit(self.selected_path)
        self.ed_path.returnPressed.connect(self._go)
        btn_go = QPushButton(tr("转到"))
        btn_go.setObjectName("ghost")
        btn_go.clicked.connect(self._go)
        btn_up = QPushButton(tr("上级"))
        btn_up.setObjectName("ghost")
        btn_up.clicked.connect(self._up)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(tr("路径")))
        row.addWidget(self.ed_path, 1)
        row.addWidget(btn_go)
        row.addWidget(btn_up)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._enter())
        self.lbl_info = QLabel("")
        self.lbl_info.setObjectName("muted")

        btn_new = QPushButton(tr("新建文件夹"))
        btn_new.setObjectName("ghost")
        btn_new.clicked.connect(self._mkdir)
        btn_pick = QPushButton(tr("选择此目录"))
        btn_pick.setObjectName("primary")
        btn_pick.clicked.connect(self._choose)
        btn_cancel = QPushButton(tr("取消"))
        btn_cancel.clicked.connect(self.reject)
        row_btn = QHBoxLayout()
        row_btn.addWidget(btn_new)
        row_btn.addStretch(1)
        row_btn.addWidget(btn_cancel)
        row_btn.addWidget(btn_pick)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 14)
        lay.setSpacing(10)
        lay.addLayout(row)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.lbl_info)
        lay.addLayout(row_btn)

        self._load(self.selected_path)

    # ---- helpers --------------------------------------------------------
    def _ensure_session(self) -> bool:
        if self._session is not None:
            return True
        try:
            self._session = FtpSession(self.server)
            self._session.connect()
            return True
        except FtpError as exc:
            self.lbl_info.setText(str(exc))
            self.lbl_info.setStyleSheet(f"color:{ERR};")
            self._session = None
            return False

    def _load(self, path: str) -> None:
        path = norm_remote(path)
        self.ed_path.setText(path)
        self.list.clear()
        if not self._ensure_session():
            return
        try:
            dirs = self._session.list_dirs(path)
        except Exception as exc:  # noqa: BLE001
            self.lbl_info.setText(tr("无法读取目录：") + f"{exc}")
            self.lbl_info.setStyleSheet(f"color:{ERR};")
            return
        for name in dirs:
            self.list.addItem("📁  " + name)
        self.lbl_info.setStyleSheet(f"color:{TEXT_MUTED};")
        self.lbl_info.setText(
            trf("{n} 个子目录 · 双击进入，或直接选择此目录", n=len(dirs)))
        self.selected_path = path

    def _go(self) -> None:
        self._load(self.ed_path.text())

    def _up(self) -> None:
        cur = norm_remote(self.ed_path.text())
        if cur == "/":
            return
        parent = posixpath.dirname(cur) or "/"
        self._load(parent)

    def _enter(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        name = item.text().replace("📁  ", "").strip()
        self._load(posixpath.join(norm_remote(self.ed_path.text()), name))

    def _mkdir(self) -> None:
        name, ok = QInputDialog.getText(self, tr("新建文件夹"), tr("文件夹名称："))
        if not ok or not name.strip():
            return
        if not self._ensure_session():
            return
        target = posixpath.join(norm_remote(self.ed_path.text()), name.strip())
        try:
            self._session.ensure_dir(target)
            self._load(norm_remote(self.ed_path.text()))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("新建文件夹"), tr("创建失败：") + f"{exc}")

    def _choose(self) -> None:
        self.selected_path = norm_remote(self.ed_path.text())
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._session is not None:
            self._session.close()
            self._session = None
        super().closeEvent(event)

    def done(self, code: int) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        super().done(code)
