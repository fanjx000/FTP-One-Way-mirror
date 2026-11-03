"""Verify the English UI has no untranslated (Chinese) text left.

Builds the real windows with language=en and walks every widget, plus renders the
settings/job dialogs and the file table with sample rows.

Run: python tools/test_i18n.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(tempfile.mkdtemp(prefix="ftpsync_i18n_"))
os.environ["APPDATA"] = str(DATA)

from PySide6.QtCore import Qt                                           # noqa: E402
from PySide6.QtWidgets import (                                          # noqa: E402
    QAbstractButton, QApplication, QComboBox, QLabel, QWidget, QAbstractItemView,
)

CJK = re.compile(r"[\u4e00-\u9fff]")
ISSUES: list[str] = []


def seed() -> None:
    local = DATA / "Documents"
    (local / "Sub").mkdir(parents=True)
    (local / "Sub" / "a.txt").write_text("x" * 10)
    cfg_dir = DATA / "FtpSync"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({
        "version": 1,
        "server": {"protocol": "ftps", "host": "ftp.example.com", "port": 21,
                   "username": "user", "password_token": "", "passive": True,
                   "encoding": "utf-8", "timeout": 30, "concurrency": 2,
                   "verify_tls": False, "remote_root": "/"},
        "options": {"delete_remote_extras": True, "preserve_mtime": True,
                    "excludes": ["Thumbs.db"], "mass_delete_guard": True,
                    "mass_delete_percent": 20, "mass_delete_min": 10,
                    "follow_reparse": False, "skip_hidden": False,
                    "skip_cloud_only": False, "retries": 2},
        "jobs": [{"id": "j1", "source": str(local), "kind": "dir",
                  "remote": "/backup/Docs", "enabled": True, "name": "Docs"}],
        "language": "en",
    }, ensure_ascii=False), encoding="utf-8")


def scan(widget: QWidget, where: str) -> None:
    for child in widget.findChildren(QWidget):
        if not child.isVisible():
            continue
        texts: list[str] = []
        if isinstance(child, (QLabel, QAbstractButton)):
            texts.append(child.text() if hasattr(child, "text") else "")
            if hasattr(child, "toolTip"):
                texts.append(child.toolTip())
        if isinstance(child, QComboBox):
            texts += [child.itemText(i) for i in range(child.count())]
        if isinstance(child, QAbstractItemView) and child.model() is not None:
            model = child.model()
            try:
                cols = model.columnCount()
            except (TypeError, ValueError):
                cols = 1
            for c in range(max(0, cols)):
                try:
                    h = model.headerData(c, Qt.Orientation.Horizontal)
                except (TypeError, ValueError):
                    h = None
                if h:
                    texts.append(str(h))
            for r in range(min(model.rowCount(), 6)):
                for c in range(cols):
                    idx = model.index(r, c)
                    v = model.data(idx, Qt.ItemDataRole.DisplayRole)
                    if v:
                        texts.append(str(v))
        for t in texts:
            if t in ("中文", "English"):
                continue          # language names are shown untranslated on purpose
            if t and CJK.search(t):
                ISSUES.append(f"{where} :: {type(child).__name__} → {t[:60]!r}")


def _sync_in_english() -> None:
    """Run a real sync with the UI language set to English and check the log."""
    import threading
    import time as _t
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import ThreadedFTPServer

    from app.config import Config, Options, ServerConfig
    from app.engine import SyncEngine
    from app.models import Job
    from app.state import StateDB

    root = DATA / "ftp"
    src = DATA / "src"
    root.mkdir(parents=True, exist_ok=True)
    (src / "sub").mkdir(parents=True, exist_ok=True)
    (src / "a file.txt").write_text("A" * 100)
    (src / "sub" / "b.txt").write_text("B" * 100)

    auth = DummyAuthorizer()
    auth.add_user("u", "p", str(root), perm="elradfmwMT")
    handler = FTPHandler
    handler.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", 2299), handler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    _t.sleep(0.7)

    cfg = Config()
    cfg.server = ServerConfig(host="127.0.0.1", port=2299, username="u",
                              password_token="", protocol="ftp", timeout=20)
    cfg.server.set_password("p")
    cfg.server.concurrency = 1
    cfg.options = Options()
    cfg.jobs = [Job(id="en", source=str(src), kind="dir", remote="/vol/Test")]

    logs: list[str] = []

    def sink(ev):
        if ev["type"] == "log":
            logs.append(ev["text"])

    st = StateDB(str(DATA / "en.db"))
    eng = SyncEngine(cfg, st, sink)
    first = eng.run()
    eng.run()                     # second run: no-change path
    # cancellation path
    eng.cancel.set()
    eng.run()
    st.close()
    srv.close_all()

    bad = [l for l in logs if CJK.search(l)]
    if bad:
        ISSUES.append(f"English log still contains Chinese ({len(bad)} lines):")
        for l in bad[:12]:
            ISSUES.append(f"    {l[:110]}")
    if first.uploaded_new != 2:
        ISSUES.append(f"english sync uploaded {first.uploaded_new} instead of 2")


def main() -> int:
    seed()
    from app.i18n import set_language

    set_language("en")
    from app.ui.main_window import MainWindow
    from app.ui.dialogs import JobDialog, RemotePickerDialog, ServerDialog
    from app.ui.theme import QSS
    from app.models import Job, Row

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    win = MainWindow()
    win.resize(1320, 860)
    win.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)

    rows = [Row("j1", "Docs", "Sub/a.txt", "/backup/Docs/Sub/a.txt", False,
                "upload_new", 1024, time.time(), status="done", message=""),
            Row("j1", "Docs", "b.txt", "/backup/Docs/b.txt", False,
                "delete", 2048, time.time(), status="failed",
                message="550 Permission denied."),
            Row("j1", "Docs", "c.txt", "/backup/Docs/c.txt", False,
                "skip", 4096, time.time(), status="skipped", message="")]
    win.model.set_rows(rows)
    win.chk_only_changed.setChecked(False)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)

    scan(win, "main window")

    win._log("Settings saved.")

    dlg = ServerDialog(win.cfg.server, win.cfg.options, win, language="en")
    dlg.resize(620, 580)
    dlg.show()
    from PySide6.QtWidgets import QTabWidget
    tabs = dlg.findChild(QTabWidget)
    for i in range(tabs.count()):
        tabs.setCurrentIndex(i)
        for _ in range(8):
            app.processEvents()
            time.sleep(0.01)
        scan(dlg, f"settings tab {i}")
    dlg.close()

    jdlg = JobDialog(Job(id="x", source=str(DATA / "Documents"), kind="dir",
                         remote="/backup/Docs"), win.cfg.server, win)
    jdlg.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    scan(jdlg, "job dialog")
    jdlg.close()

    rp = RemotePickerDialog(win.cfg.server, "/", win)
    rp.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    scan(rp, "remote picker")
    rp.close()

    win.close()
    for _ in range(5):
        app.processEvents()

    _sync_in_english()

    # switching back must restore Chinese everywhere
    set_language("zh")
    win2 = MainWindow()
    win2.show()
    for _ in range(15):
        app.processEvents()
        time.sleep(0.02)
    zh_texts = [c.text() for c in win2.findChildren(QLabel) if c.isVisible()]
    if not any("仅预览" in t for t in zh_texts):
        ISSUES.append("switching back to Chinese did not restore the labels")
    # the in-app language switch rebuilds the window
    win2.cfg.language = "en"
    set_language("en")
    win2._reload_ui()
    for _ in range(15):
        app.processEvents()
        time.sleep(0.02)
    nxt = win2._next_window
    txt = [c.text() for c in nxt.findChildren(QLabel) if c.isVisible()]
    if not any("Preview only" in t for t in txt) and not any(
            "Start sync" in t for t in txt):
        ISSUES.append("rebuilding the window did not apply English")
    nxt.close()
    for _ in range(5):
        app.processEvents()

    print("=" * 66)
    if ISSUES:
        print(f"English UI still shows {len(set(ISSUES))} Chinese strings:")
        for item in sorted(set(ISSUES)):
            print("  -", item)
        return 1
    print("English UI check passed: no Chinese text left in any widget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
