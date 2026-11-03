"""Help -> About must really show a dialog, in both languages.

This is a regression test for v1.8.1, where ``data_dir()`` (a ``pathlib.Path``)
was concatenated to a string with ``+``.  The ``TypeError`` was swallowed by the
slot guard, so clicking *About* simply did nothing - no window, no error.
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

DATA = Path(tempfile.mkdtemp(prefix="about_test_"))
os.environ["APPDATA"] = str(DATA)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def seed() -> None:
    from app import dpapi
    cfg = DATA / "FtpSync"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.json").write_text(json.dumps({
        "version": 1,
        "server": {"protocol": "ftp", "host": "127.0.0.1", "port": 21,
                   "username": "u", "password_token": dpapi.protect("p"),
                   "passive": True, "encoding": "utf-8", "timeout": 3,
                   "concurrency": 1, "verify_tls": False, "remote_root": "/"},
        "options": {}, "jobs": [], "language": "zh",
    }, ensure_ascii=False), encoding="utf-8")


def pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    seed()
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app import i18n, safety
    from app.ui.main_window import MainWindow
    from app.ui.theme import QSS

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    safety.install()

    # capture what the real method passes to QMessageBox.about
    calls: list = []
    original = QMessageBox.about
    QMessageBox.about = staticmethod(
        lambda parent, title, text: calls.append((title, text)))

    for lang, expect in (("zh", ("开发者：", "2026-11-02", "fanjunxin@gmail.com")),
                         ("en", ("Owner:", "Developed:", "Contact:",
                                 "fanjunxin@gmail.com"))):
        print(f"\n[{lang}] Help -> About")
        i18n.set_language(lang)
        win = MainWindow()
        win.show()
        pump(app, 0.3)
        calls.clear()

        menus = {a.text(): a.menu() for a in win.menuBar().actions()}
        help_menu = menus.get(i18n.tr("帮助"))
        check(help_menu is not None, "存在「帮助」菜单")
        about_act = [a for a in help_menu.actions()
                     if a.text() == i18n.tr("关于")] if help_menu else []
        check(bool(about_act), "存在「关于」菜单项")

        about_act[0].trigger()          # exactly what a mouse click does
        pump(app, 0.2)

        check(len(calls) == 1, f"弹出了关于对话框（{len(calls)} 次）")
        if calls:
            title, text = calls[0]
            check(title == i18n.tr("关于"), f"标题正确（{title}）")
            for want in expect:
                check(want in text, f"包含「{want}」")
            check("配置目录" in text or "Config folder" in text,
                  "包含配置目录")
            check("<a href=\"mailto:" in text, "邮箱是 mailto 链接")
            check("Traceback" not in text, "内容中没有堆栈")
        win.close()
        pump(app, 0.2)

    QMessageBox.about = original

    # the slot guard must not have recorded anything for _on_about
    log = safety.recent()
    check("slot _on_about failed" not in log, "崩溃日志中没有 _on_about 失败记录")

    # -- the failure reporting itself -----------------------------------
    print("\n[guard] 槽函数异常必须被看到，而不是静默")
    shown: list = []
    safety._notifier = lambda summary, detail: shown.append((summary, detail))
    safety._last_slot_notice.clear()

    from app.safety import guarded

    @guarded
    def boom() -> None:
        raise ValueError("simulated failure")

    boom()
    check(len(shown) == 1, f"异常触发了提示（{len(shown)} 次）")
    check(bool(shown) and "simulated failure" in shown[0][0],
          "提示里带有原始错误信息")
    boom()
    check(len(shown) == 1, "重复异常不会反复弹窗（限频生效）")

    print()
    print("=" * 64)
    if FAILS:
        print(f"关于对话框测试失败 {len(FAILS)} 项：")
        for f in FAILS:
            print("  -", f)
        return 1
    print("关于对话框测试全部通过 ✔ —— About 能正常弹出，槽异常不再静默")
    return 0


if __name__ == "__main__":
    sys.exit(main())
