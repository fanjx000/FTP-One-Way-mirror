"""Crash protection: make sure a failure never makes the window disappear.

A frozen windowed build has no console, so an unhandled exception (or a Qt abort)
looks exactly like "the app closed by itself".  This module installs the safety
nets that turn those into a readable crash log plus a message box:

* ``sys.excepthook``        - exceptions in the main thread (Qt slots, timers)
* ``threading.excepthook``  - exceptions in worker threads
* ``faulthandler``          - hard crashes / aborts (C level, stack dump)
* Qt message handler        - qWarning / qFatal from the Qt side
* log rotation              - the file never grows without bound

Everything here is defensive: a failing handler must never raise.
"""
from __future__ import annotations

import datetime as _dt
import faulthandler
import os
import sys
import threading
import traceback
from typing import Callable, List, Optional

MAX_LOG_BYTES = 512 * 1024
LOG_NAME = "crash.log"

_lock = threading.Lock()
_log_path: Optional[str] = None
_notifier: Optional[Callable[[str, str], None]] = None
_fault_file = None
_shown = 0                     # how many dialogs we already showed this session
MAX_DIALOGS = 3
_last_slot_notice: dict = {}   # slot name -> monotonic time of the last dialog
SLOT_NOTICE_INTERVAL = 20.0    # seconds; stops a repeating slot from spamming


def log_path() -> str:
    """Where the crash log lives (next to the config)."""
    global _log_path
    if _log_path:
        return _log_path
    try:
        from .config import data_dir
        base = str(data_dir())
        os.makedirs(base, exist_ok=True)
    except Exception:
        base = os.path.expanduser("~")
    _log_path = os.path.join(base, LOG_NAME)
    return _log_path


def _rotate() -> None:
    """Keep the log small: one previous copy is enough."""
    path = log_path()
    try:
        if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
            old = path + ".1"
            if os.path.exists(old):
                os.remove(old)
            os.replace(path, old)
    except OSError:
        pass


def record(kind: str, text: str) -> str:
    """Append one entry to the crash log and return it (never raises)."""
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n===== {stamp}  {kind} =====\n{text.rstrip()}\n"
    try:
        with _lock:
            _rotate()
            with open(log_path(), "a", encoding="utf-8") as fh:
                fh.write(entry)
                fh.flush()
    except Exception:
        pass
    return entry


def install(notifier: Optional[Callable[[str, str], None]] = None) -> None:
    """Install every safety net.  Call once, right after QApplication exists."""
    global _notifier, _fault_file
    _notifier = notifier

    # -- hard crashes (segfault / abort) ---------------------------------
    try:
        _rotate()
        _fault_file = open(log_path(), "a", encoding="utf-8")
        _fault_file.write(f"\n===== {_dt.datetime.now():%Y-%m-%d %H:%M:%S}  "
                          f"session start (pid {os.getpid()}) =====\n")
        _fault_file.flush()
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception:
        pass

    # -- python exceptions, main thread ----------------------------------
    def _hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        record("unhandled exception (main thread)", text)
        _notify(str(exc), text)

    sys.excepthook = _hook

    # -- python exceptions, worker threads -------------------------------
    def _thread_hook(args) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        text = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))
        record(f"unhandled exception (thread {name})", text)

    threading.excepthook = _thread_hook

    # -- Qt messages ------------------------------------------------------
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        levels = {QtMsgType.QtFatalMsg: "Qt FATAL",
                  QtMsgType.QtCriticalMsg: "Qt critical",
                  QtMsgType.QtWarningMsg: "Qt warning"}

        def _handler(mode, context, message) -> None:
            if mode not in levels:
                return
            where = f"{context.file}:{context.line}" if context and context.file else ""
            record(levels[mode], f"{message}\n  at {where}")

        qInstallMessageHandler(_handler)
    except Exception:
        pass


def _notify(summary: str, detail: str) -> None:
    """Show a crash dialog at most a few times, and never from a worker thread."""
    global _shown
    if _notifier is None or _shown >= MAX_DIALOGS:
        return
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        _shown += 1
        _notifier(summary, detail)
    except Exception:
        pass


def recent(limit: int = 12000) -> str:
    """Tail of the crash log, for 'copy details' buttons."""
    try:
        for path in (log_path() + ".1", log_path()):
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    data = fh.read()
                if data:
                    return data[-limit:]
    except Exception:
        pass
    return ""


def guarded(fn):
    """Decorator for Qt slots: log a failure instead of killing the app.

    An exception escaping a slot is the most common reason a Qt application
    disappears without a trace in a windowed build.  Silently swallowing it is
    almost as bad, though: the user clicks a menu item and simply nothing
    happens.  So the failure is recorded *and* reported through the notifier,
    rate-limited per slot so a repeating timer cannot spam dialogs.
    """
    import functools
    import time

    name = getattr(fn, "__name__", "?")

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            record(f"slot {name} failed", text)
            try:
                sys.__stderr__ and sys.__stderr__.write(text)
            except Exception:
                pass
            now = time.monotonic()
            if now - _last_slot_notice.get(name, 0.0) >= SLOT_NOTICE_INTERVAL:
                _last_slot_notice[name] = now
                _notify(f"{name}: {exc.__class__.__name__}: {exc}", text)
            return None

    return wrapper
