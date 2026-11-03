"""Crash-resistance tests: deliberately provoke the failure modes that used to
kill the windowed app, and assert it survives with a log entry.

Each case mirrors a real report:
  A. exception raised inside a Qt slot (timer / button)
  B. the settings dialog closed while "test connection" is running
     (used to abort the process: "QThread: Destroyed while thread is still running")
  C. the table model asked for a row that no longer exists (paint-time IndexError)
  D. language switch: the rebuilt window must survive garbage collection
  E. the crash log is written and readable

Run: python tools/test_crash_safety.py
"""
from __future__ import annotations

import gc
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(tempfile.mkdtemp(prefix="ftpsync_safe_"))
os.environ["APPDATA"] = str(DATA)

from PySide6.QtCore import QTimer, Qt                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel                      # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def seed() -> None:
    from app import dpapi
    local = DATA / "src"
    local.mkdir(parents=True, exist_ok=True)
    (local / "a.txt").write_text("a" * 100)
    c = DATA / "FtpSync"
    c.mkdir(parents=True, exist_ok=True)
    (c / "config.json").write_text(json.dumps({
        "version": 1,
        "server": {"protocol": "ftp", "host": "127.0.0.1", "port": 21,
                   "username": "u", "password_token": dpapi.protect("p"),
                   "passive": True, "encoding": "utf-8", "timeout": 3,
                   "concurrency": 1, "verify_tls": False, "remote_root": "/"},
        "options": {}, "jobs": [{"id": "j", "source": str(local), "kind": "dir",
                                 "remote": "/x", "enabled": True, "name": "s"}],
        "language": "zh",
    }, ensure_ascii=False), encoding="utf-8")


def pump(app, seconds: float = 0.35) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    seed()
    from app import safety
    from app.ui.theme import QSS

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    safety.install()          # no dialog in tests

    from app.ui.main_window import MainWindow
    from app.ui.dialogs import ServerDialog
    from app.models import Row

    print("\n[A] Qt 槽函数里抛异常（定时器 / 按钮）")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    pump(app, 0.4)

    @safety.guarded
    def boom() -> None:
        raise RuntimeError("deliberate slot failure")

    boom()                                    # must not propagate
    win._drain = boom                          # timer callback raising
    QTimer.singleShot(0, boom)
    pump(app, 0.5)
    check(win.isVisible(), "窗口仍然显示（槽异常没有杀掉程序）")
    check("deliberate slot failure" in safety.recent(),
          "异常写入了崩溃日志")

    print("\n[B] 测试连接进行中关闭设置对话框（旧的 QThread 崩溃点）")
    for i in range(3):
        dlg = ServerDialog(win.cfg.server, win.cfg.options, win, language="zh")
        dlg.show()
        pump(app, 0.15)
        dlg._on_test()                        # starts the probe (connection will fail)
        pump(app, 0.05)
        dlg.close()                           # close while the probe is in flight
        dlg.deleteLater()
        pump(app, 0.25)
        gc.collect()
    check(True, "连续 3 次'测试中关闭对话框'未导致进程退出")
    check(win.isVisible(), "主窗口仍在")

    print("\n[C] 表格模型被问到不存在的行")
    win.model.set_rows([
        Row("j", "s", "a.txt", "/x/a.txt", False, "upload_new", 10, time.time(),
            status="pending", message=""),
    ])
    pump(app, 0.15)
    bad = win.model.index(5, 0)               # out of range
    value = win.model.data(bad, Qt.ItemDataRole.DisplayRole)
    check(value is None, "越界索引返回 None 而不是抛异常")
    check(win.model.data(win.model.index(-1, 0), 0) is None, "负索引同样安全")
    win.model.update_row("no-such-key", "done", "x", time.time())
    check(True, "更新不存在的行不会崩溃")

    print("\n[D] 切换语言重建窗口后不能被回收")
    win.cfg.language = "en"
    from app.i18n import set_language
    set_language("en")
    old = win
    old._reload_ui()
    pump(app, 0.5)
    gc.collect()
    pump(app, 0.3)
    rebuilt = old._next_window
    check(rebuilt is not None and rebuilt.isVisible(),
          "重建后的窗口仍然可见（未被垃圾回收）")
    labels = [c.text() for c in rebuilt.findChildren(QLabel) if c.isVisible()]
    check(any("Start sync" in t or "Preview only" in t for t in labels),
          "重建窗口使用英文界面")
    rebuilt.close()
    pump(app, 0.2)
    from app.i18n import set_language as sl
    sl("zh")

    print("\n[E] 崩溃日志可读、位置已知")
    log = safety.log_path()
    check(os.path.exists(log), f"日志文件存在：{log}")
    check(len(safety.recent()) > 0, "能读回日志内容")
    check("session start" in safety.recent() or "unhandled" in safety.recent(),
          "日志包含会话/异常标记")

    for w in list(win.findChildren(QLabel)):
        pass
    old.close()
    pump(app, 0.2)

    print("\n" + "=" * 60)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(" -", f)
        return 1
    print("崩溃防护测试全部通过 ✔ —— 上述故障都不再导致程序退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
