"""Layout audit: finds clipped / overflowing / overlapping widgets without a human eye.

Run: python tools/ui_audit.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(tempfile.mkdtemp(prefix="ftpsync_audit_"))
os.environ["APPDATA"] = str(DATA)

from PySide6.QtWidgets import (                                          # noqa: E402
    QAbstractButton, QApplication, QCheckBox, QLabel, QPushButton, QWidget,
)

ISSUES: list[str] = []


def seed() -> None:
    local = DATA / "Documents"
    (local / "Projects" / "src").mkdir(parents=True)
    for i in range(3):
        (local / "Projects" / "src" / f"file{i}.py").write_text("x = 1\n" * 50)
    deep = local / "Projects" / "very-long-directory-name-for-testing-overflow" / "deep"
    deep.mkdir(parents=True)
    (deep / "a-rather-long-file-name-that-should-be-elided-not-clipped.py").write_text("y\n")
    cfg_dir = DATA / "FtpSync"
    cfg_dir.mkdir(parents=True)
    cfg = {
        "version": 1,
        "server": {"protocol": "ftps", "host": "ftp.example-corporation.com", "port": 21,
                   "username": "backup-operator", "password_token": "", "passive": True,
                   "encoding": "utf-8", "timeout": 30, "concurrency": 3,
                   "verify_tls": False, "remote_root": "/"},
        "options": {"delete_remote_extras": True, "preserve_mtime": True,
                    "excludes": ["Thumbs.db"], "mass_delete_guard": True,
                    "mass_delete_percent": 20, "mass_delete_min": 10,
                    "follow_reparse": False, "skip_hidden": False, "retries": 2},
        "jobs": [
            {"id": "j1", "source": str(local / "Projects"), "kind": "dir",
             "remote": "/backup/Documents/Projects", "enabled": True, "name": "项目代码"},
            {"id": "j2", "source": str(local / "Projects" / "src" / "file0.py"), "kind": "file",
             "remote": "/backup/Documents/Projects/src", "enabled": False, "name": ""},
        ],
    }
    (cfg_dir / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def audit(widget: QWidget, label: str) -> None:
    for child in widget.findChildren(QWidget):
        if not child.isVisible() or child.width() <= 1:
            continue
        if isinstance(child, (QLabel, QAbstractButton)):
            sh = child.sizeHint()
            wrapped = bool(getattr(child, "wordWrap", lambda: False)())
            if not wrapped and sh.width() > child.width() + 3:
                text = child.text() if hasattr(child, "text") else ""
                ISSUES.append(f"[文字挤压] {label} :: {type(child).__name__}('{text[:32]}') "
                              f"sizeHint {sh.width()}px > 实际 {child.width()}px")
            if sh.height() > child.height() + 3:
                ISSUES.append(f"[高度不足] {label} :: {type(child).__name__} "
                              f"sizeHint {sh.height()}px > 实际 {child.height()}px")


def overlaps(widget: QWidget, label: str) -> None:
    for parent in [widget] + widget.findChildren(QWidget):
        if not parent.isVisible():
            continue
        kids = [c for c in parent.children()
                if isinstance(c, QWidget) and c.isVisible() and not c.isWindow()]
        for i in range(len(kids)):
            for j in range(i + 1, len(kids)):
                a, b = kids[i].geometry(), kids[j].geometry()
                if a.intersects(b) and not a.contains(b) and not b.contains(a):
                    inter = a.intersected(b)
                    if inter.width() > 3 and inter.height() > 3:
                        ISSUES.append(
                            f"[重叠] {label} :: {type(parent).__name__} 内 "
                            f"{type(kids[i]).__name__} ∩ {type(kids[j]).__name__}")


def cfg_server():
    from app.config import ServerConfig
    return ServerConfig(host="ftp.example-corporation.com", port=21,
                        username="backup-operator", protocol="ftps")


def cfg_options():
    from app.config import Options
    return Options()


def main() -> int:
    seed()
    from app.ui.main_window import MainWindow
    from app.ui.theme import QSS
    from app.models import Row

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    for size in [(1320, 860), (1040, 660)]:
        win = MainWindow()
        win.resize(*size)
        win.show()
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)

        rows = []
        for i, (act, st) in enumerate([("upload_new", "done"), ("upload_update", "pending"),
                                       ("delete", "done"), ("skip", "skipped"),
                                       ("mkdir", "done")]):
            rows.append(Row("j1", "项目代码", f"src/module_{i}.py",
                            "/backup/Documents/Projects/src/module.py", False, act,
                            1024 * (i + 1) * 37, time.time() - 3600 * i,
                            remote_size=1024 * (i + 1) * 30,
                            remote_mtime=time.time() - 3700 * i,
                            synced_at=time.time() - 100 * i, status=st,
                            message="示例说明文字" if i == 2 else ""))
        win.model.set_rows(rows)
        win.chk_only_changed.setChecked(False)
        for _ in range(10):
            app.processEvents()
            time.sleep(0.01)

        lbl = f"{size[0]}x{size[1]}"
        audit(win, lbl)
        overlaps(win, lbl)

        vh = win.view.horizontalHeader()
        total = sum(vh.sectionSize(c) for c in range(vh.count()))
        if total < win.view.viewport().width() - 40:
            ISSUES.append(f"[表格留白] {lbl} :: 列宽合计 {total}px，"
                          f"视口 {win.view.viewport().width()}px")
        win.close()
        for _ in range(3):
            app.processEvents()

    # dialogs: the settings dialog gained new options, audit it as well
    from app.ui.dialogs import ServerDialog, JobDialog
    from app.models import Job
    dlg = ServerDialog(cfg_server(), cfg_options(), None)
    dlg.resize(600, 560)
    dlg.show()
    for _ in range(15):
        app.processEvents()
        time.sleep(0.02)
    from PySide6.QtWidgets import QTabWidget
    tabw = dlg.findChild(QTabWidget)
    if tabw is not None:
        for i in range(tabw.count()):
            tabw.setCurrentIndex(i)
            for _ in range(6):
                app.processEvents()
                time.sleep(0.01)
            audit(dlg, f"settings-tab{i}")
            overlaps(dlg, f"settings-tab{i}")
    dlg.close()

    jdlg = JobDialog(Job(id="x", source=os.path.expanduser("~"), kind="dir",
                         remote="/backup/我的 文档"), cfg_server(), None)
    jdlg.show()
    for _ in range(15):
        app.processEvents()
        time.sleep(0.02)
    audit(jdlg, "job-dialog")
    overlaps(jdlg, "job-dialog")
    jdlg.close()

    # ENGLISH PASS (English labels are longer; re-check for clipping)
    from app.i18n import set_language as _set_lang
    _set_lang("en")
    for size in [(1320, 860), (1040, 660)]:
        en = MainWindow()
        en.resize(*size)
        en.show()
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)
        lbl = f"EN {size[0]}x{size[1]}"
        audit(en, lbl)
        overlaps(en, lbl)
        en.close()
        for _ in range(3):
            app.processEvents()
    _set_lang("zh")

    print("=" * 70)
    if ISSUES:
        print(f"发现 {len(set(ISSUES))} 个布局问题：")
        for item in sorted(set(ISSUES)):
            print(" -", item)
    else:
        print("布局审计通过，未发现截断 / 重叠 / 越界问题。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
