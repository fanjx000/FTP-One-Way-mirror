"""UI smoke test + screenshots.

Boots the real main window against a local FTP server, performs an actual sync
through the GUI code path, then grabs PNGs so the layout can be reviewed.
Run:  python tools/shot.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = Path(tempfile.mkdtemp(prefix="ftpsync_ui_"))
os.environ["APPDATA"] = str(DATA)          # keep the real user profile clean

from pyftpdlib.authorizers import DummyAuthorizer          # noqa: E402
from pyftpdlib.handlers import FTPHandler                  # noqa: E402
from pyftpdlib.servers import ThreadedFTPServer            # noqa: E402

from PySide6.QtWidgets import QApplication                 # noqa: E402

PORT = 2125
FTP_ROOT = DATA / "ftproot"
LOCAL = DATA / "Documents"


def seed_files() -> None:
    (LOCAL / "Projects" / "app" / "src").mkdir(parents=True, exist_ok=True)
    (LOCAL / "Photos" / "2026").mkdir(parents=True, exist_ok=True)
    (LOCAL / "Notes").mkdir(parents=True, exist_ok=True)
    now = time.time()
    files = {
        "Projects/app/src/main.py": (b"print('hello')\n" * 40, now - 300),
        "Projects/app/src/utils.py": (b"def add(a,b):\n    return a+b\n" * 30, now - 3600),
        "Projects/app/README.md": (b"# App\n\nreadme\n" * 20, now - 7200),
        "Projects/report-q3.docx": (os.urandom(184320), now - 86400),
        "Photos/2026/IMG_0031.jpg": (os.urandom(2400000), now - 400000),
        "Photos/2026/IMG_0032.jpg": (os.urandom(1840000), now - 480000),
        "Photos/cover.png": (os.urandom(430000), now - 900000),
        "Notes/meeting.md": (b"- item\n" * 120, now - 600),
        "Notes/todo.txt": (b"todo\n" * 30, now - 120),
    }
    for rel, (data, mtime) in files.items():
        p = LOCAL / rel
        p.write_bytes(data)
        os.utime(p, (mtime, mtime))


def write_config() -> None:
    from app import dpapi
    cfg_dir = DATA / "FtpSync"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "version": 1,
        "server": {
            "protocol": "ftp", "host": "127.0.0.1", "port": PORT,
            "username": "demo", "password_token": dpapi.protect("demo"), "passive": True,
            "encoding": "utf-8", "timeout": 30, "concurrency": 3,
            "verify_tls": False, "remote_root": "/",
        },
        "options": {
            "delete_remote_extras": True, "preserve_mtime": True,
            "excludes": ["Thumbs.db", "desktop.ini", ".DS_Store", "~$*", "*.tmp"],
            "mass_delete_guard": True, "mass_delete_percent": 20,
            "mass_delete_min": 10, "follow_reparse": False, "skip_hidden": False,
            "retries": 2,
        },
        "jobs": [
            {"id": "j1", "source": str(LOCAL / "Projects"), "kind": "dir",
             "remote": "/backup/Documents/Projects", "enabled": True, "name": "项目代码"},
            {"id": "j2", "source": str(LOCAL / "Photos"), "kind": "dir",
             "remote": "/backup/Documents/Photos", "enabled": True, "name": "照片备份"},
            {"id": "j3", "source": str(LOCAL / "Notes" / "todo.txt"), "kind": "file",
             "remote": "/backup/Documents/Notes", "enabled": True, "name": "待办清单"},
        ],
    }
    (cfg_dir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                         encoding="utf-8")


def pump(app, seconds: float, until=None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            break
        time.sleep(0.02)


def main() -> int:
    seed_files()
    write_config()
    FTP_ROOT.mkdir(parents=True, exist_ok=True)
    auth = DummyAuthorizer()
    auth.add_user("demo", "demo", str(FTP_ROOT), perm="elradfmwMT")
    handler = FTPHandler
    handler.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.5)

    from app.ui.icon import app_icon
    from app.ui.theme import QSS
    from app.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())

    win = MainWindow()
    win.resize(1320, 860)
    win.show()
    pump(app, 0.8)
    win.grab().save(str(ROOT / "docs" / "screenshot-empty.png"))

    # real sync through the UI entry point
    win._start(dry_run=False)
    pump(app, 40, until=lambda: not win._running)
    pump(app, 0.6)
    win.grab().save(str(ROOT / "docs" / "screenshot-synced.png"))
    print("after sync:", win.lbl_phase.text())

    # second run: nothing to do (proves incremental behaviour in the GUI too)
    win._start(dry_run=False)
    pump(app, 30, until=lambda: not win._running)
    pump(app, 0.5)
    win.grab().save(str(ROOT / "docs" / "screenshot-nodiff.png"))
    print("second run:", win.lbl_phase.text())

    win.tabs.setCurrentIndex(1)
    pump(app, 0.3)
    win.grab().save(str(ROOT / "docs" / "screenshot-log.png"))

    # settings dialog
    from app.ui.dialogs import ServerDialog
    dlg = ServerDialog(win.cfg.server, win.cfg.options, win)
    dlg.resize(620, 580)
    dlg.show()
    pump(app, 0.5)
    dlg.grab().save(str(ROOT / "docs" / "screenshot-settings.png"))
    tabs = dlg.findChild(__import__("PySide6.QtWidgets", fromlist=["QTabWidget"]).QTabWidget)
    if tabs is not None:
        tabs.setCurrentIndex(1)
        pump(app, 0.5)
        dlg.grab().save(str(ROOT / "docs" / "screenshot-options.png"))
    dlg.close()

    # English UI screenshots
    from app.i18n import set_language
    set_language("en")
    en_win = MainWindow()
    en_win.resize(1320, 860)
    en_win.show()
    pump(app, 0.8)
    en_win.model.set_rows(win.model._rows[:40])
    en_win.chk_only_changed.setChecked(False)
    pump(app, 0.4)
    en_win.grab().save(str(ROOT / "docs" / "screenshot-en.png"))
    en_dlg = ServerDialog(en_win.cfg.server, en_win.cfg.options, en_win,
                          language="en")
    en_dlg.resize(620, 580)
    en_dlg.show()
    pump(app, 0.5)
    en_dlg.grab().save(str(ROOT / "docs" / "screenshot-settings-en.png"))
    en_dlg.close()
    en_win.close()
    set_language("zh")
    pump(app, 0.3)

    from app.ui.dialogs import JobDialog
    from app.models import Job
    jd = JobDialog(Job(id="x", source=str(LOCAL / "Projects"), kind="dir",
                       remote="/backup/Documents/Projects"), win.cfg.server, win)
    jd.show()
    pump(app, 0.4)
    jd.grab().save(str(ROOT / "docs" / "screenshot-job.png"))
    jd.close()

    # About boxes (both languages) - content comes from app/about.py
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtWidgets import QMessageBox as _Box
    from app.about import html as about_html
    from app.i18n import tr as _tr

    def shot_about(lang: str, name: str) -> None:
        set_language(lang)
        box = _Box(win)
        box.setWindowTitle(_tr("关于"))
        box.setTextFormat(_Qt.TextFormat.RichText)
        box.setText(about_html(_tr, trailing=_tr("配置目录：") + str(DATA / "FtpSync")))
        box.setStandardButtons(_Box.StandardButton.Ok)
        box.show()
        pump(app, 0.4)
        box.grab().save(str(ROOT / "docs" / name))
        box.close()

    shot_about("zh", "screenshot-about.png")
    shot_about("en", "screenshot-about-en.png")
    set_language("zh")

    print("---- LOG ----")
    print(win.txt_log.toPlainText()[-4000:])
    print("remote tree:")
    for p in sorted(FTP_ROOT.rglob("*")):
        print("  ", p.relative_to(FTP_ROOT))

    win.close()
    srv.close_all()
    shutil.rmtree(DATA, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
