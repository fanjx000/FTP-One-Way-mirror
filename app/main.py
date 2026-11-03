"""Application entry point.

Command line switches (mainly for support and the build pipeline):

  FtpSync.exe                     normal UI
  FtpSync.exe --selftest out.png  render the window, save a screenshot, exit
  FtpSync.exe --selftest out.png --autosync
                                  ...and run a real sync first
  FtpSync.exe --diag out.txt      run the server diagnostics without the UI,
                                  write the report to out.txt, exit
  FtpSync.exe --selftest out.png --about
                                  ...and open Help -> About, saving the dialog to
                                  out-about.png (verifies the dialog really shows)
  FtpSync.exe --about [out.txt]   print the About text (version / owner / contact);
                                  the frozen build is windowed, so with no console
                                  attached it writes out.txt instead
"""
from __future__ import annotations

import os
import sys


def _write(path: str, text: str) -> None:
    """Write a report file, creating the folder when needed."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _run_diag_cli(target: str) -> int:
    """Headless diagnostics: no Qt window, useful for support tickets."""
    from .config import Config
    from .diagnose import run as diag_run
    from .i18n import set_language

    cfg = Config.load()
    set_language(cfg.language)
    targets = [j.remote for j in cfg.jobs if j.enabled and j.remote]
    try:
        report = diag_run(cfg.server, targets=targets)
        text = report.text()
        code = 0 if not report.is_blocking() else 1
    except Exception as exc:  # noqa: BLE001 - never crash a support command
        text = f"[error] {exc.__class__.__name__}: {exc}"
        code = 2
    from . import __version__
    header = (f"FtpSync diagnostics v{__version__}\n"
              f"server: {cfg.server.host}:{cfg.server.port}\n"
              f"user: {cfg.server.username}\ntargets: {targets or '-'}\n"
              + "-" * 52 + "\n\n")
    _write(target, header + text + "\n")
    return code


def _print_about(target: str = "") -> int:
    """Version and owner details, for support mails and build checks.

    The frozen build is a *windowed* program, so ``sys.stdout`` is ``None`` and a
    bare ``print`` would raise (and exit 1).  Text therefore goes to a file when
    no console is attached.
    """
    from .about import plain
    from .config import Config, data_dir
    from .i18n import set_language, tr

    set_language(Config.load().language)
    text = plain(tr)

    if target:
        _write(target, text + "\n")
        return 0
    if sys.stdout is not None:
        try:
            print(text)
        except UnicodeEncodeError:        # legacy console code page
            print(text.encode("utf-8", "replace").decode("utf-8", "replace"))
        return 0
    fallback = str(os.path.join(data_dir(), "about.txt"))
    _write(fallback, text + "\n")
    return 0


def main() -> int:
    # --about doubles as a switch for --selftest, so only treat it as a
    # standalone command when no screenshot run was requested
    if "--about" in sys.argv and "--selftest" not in sys.argv:
        idx = sys.argv.index("--about")
        out = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ""
        return _print_about(out)
    if "--diag" in sys.argv:
        idx = sys.argv.index("--diag")
        out = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "ftpsync-diagnose.txt"
        return _run_diag_cli(out)

    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication

    from .config import Config
    from .i18n import set_language, tr
    from .safety import install as install_safety
    from .safety import log_path, recent
    from .ui.icon import app_icon
    from .ui.main_window import MainWindow
    from .ui.theme import QSS

    set_language(Config.load().language)      # before any widget is built

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")            # consistent rendering of the dark stylesheet
    app.setApplicationName(tr("FTP 单向同步"))
    app.setApplicationDisplayName(tr("FTP 单向同步"))
    app.setOrganizationName("FtpSync")
    app.setStyleSheet(QSS)
    app.setWindowIcon(app_icon())

    # Keep the app alive and leave a trace when something goes wrong.
    def _notify(summary: str, detail: str) -> None:
        try:
            from PySide6.QtWidgets import QApplication as _App, QMessageBox
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("程序遇到问题"))
            box.setText(tr("刚才的操作出错了，程序已继续运行。"))
            box.setInformativeText(f"{summary}\n\n{tr('详细记录')}：{log_path()}")
            box.setDetailedText(detail[-4000:])
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
            _App.processEvents()
        except Exception:
            pass

    install_safety(_notify)

    win = MainWindow()
    win.show()

    if "--selftest" in sys.argv:
        idx = sys.argv.index("--selftest")
        target = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "selftest.png"

        def _grab_about() -> None:
            """Capture the About dialog, then quit."""
            from PySide6.QtWidgets import QMessageBox

            shot = target.replace(".png", "-about.png")
            for w in app.topLevelWidgets():
                if isinstance(w, QMessageBox) and w.isVisible():
                    w.grab().save(shot)
                    w.accept()
                    break
            QTimer.singleShot(200, app.quit)

            win._on_about()                 # same slot the menu action calls

        if "--about" in sys.argv:
            # QMessageBox.about() runs its own modal loop, so _on_about blocks
            # until the dialog is closed.  Grab from a timer that fires *inside*
            # that loop.
            def _open() -> None:
                QTimer.singleShot(500, _grab_about)
                win._on_about()

            QTimer.singleShot(600, _open)
            return app.exec()

        def _shot() -> None:
            win.grab().save(target)
            app.quit()

        def _wait_idle() -> None:
            if win._running:
                QTimer.singleShot(200, _wait_idle)
            else:
                QTimer.singleShot(400, _shot)

        if "--autosync" in sys.argv:
            QTimer.singleShot(400, lambda: win._start(dry_run=False))
            QTimer.singleShot(1200, _wait_idle)
        else:
            QTimer.singleShot(1600, _shot)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
