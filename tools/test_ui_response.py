"""UI responsiveness tests.

The reported symptom was "clicking Preview makes the window stop responding but
the process keeps running".  These tests prove the window recovers:

  A. a huge row burst no longer blocks the event loop (time budget per tick)
  B. a run whose worker finished but whose queue kept trickling events still
     reaches the finished state (buttons re-enabled) - the old "stuck forever"
     bug
  C. a genuinely frozen UI thread is detected by the watchdog, logged, and the
     window comes back usable afterwards
  D. three previews in a row on a 500-file tree stay responsive

Run: python tools/test_ui_response.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = Path(tempfile.mkdtemp(prefix="ftpsync_resp_"))
os.environ["APPDATA"] = str(DATA)

from PySide6.QtCore import QTimer                                      # noqa: E402
from PySide6.QtWidgets import QApplication                             # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def seed(files: int = 500, dirs: int = 70) -> None:
    from app import dpapi
    src = DATA / "src"
    for d in range(dirs):
        (src / f"d{d:03d}").mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (src / f"d{i % dirs:03d}" / f"f{i}.txt").write_text("x" * 50)
    c = DATA / "FtpSync"
    c.mkdir(parents=True, exist_ok=True)
    (c / "config.json").write_text(json.dumps({
        "version": 1,
        "server": {"protocol": "ftp", "host": "127.0.0.1", "port": 1,
                   "username": "u", "password_token": dpapi.protect("p"),
                   "passive": True, "encoding": "utf-8", "timeout": 3,
                   "concurrency": 1, "verify_tls": False, "remote_root": "/"},
        "options": {}, "jobs": [{"id": "j", "source": str(src), "kind": "dir",
                                 "remote": "/x", "enabled": True, "name": "s"}],
        "language": "zh",
    }, ensure_ascii=False), encoding="utf-8")


class Heartbeat:
    """Measures the longest gap between event-loop turns."""

    def __init__(self, app, interval: int = 40) -> None:
        self.app = app
        self.last = time.monotonic()
        self.max_gap = 0.0
        self.ticks = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(interval)

    def _tick(self) -> None:
        now = time.monotonic()
        self.max_gap = max(self.max_gap, now - self.last)
        self.last = now
        self.ticks += 1

    def reset(self) -> None:
        self.max_gap = 0.0
        self.last = time.monotonic()

    def stop(self) -> None:
        self.timer.stop()


def pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.004)


def main() -> int:
    seed()
    from app import safety

    app = QApplication(sys.argv)
    from app.ui.theme import QSS
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    safety.install()

    from app.ui.main_window import MainWindow
    from app.models import Row

    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    pump(app, 0.4)
    beat = Heartbeat(app)
    pump(app, 0.3)

    # ---------------------------------------------------------------- A
    print("\n[A] 一次性推入 5000 行更新：事件循环不能被长时间阻塞")
    win.model.clear()
    rows = [Row("j", "s", f"f{i}.txt", f"/x/f{i}.txt", False, "upload_new",
                100, time.time(), status="pending", message="")
            for i in range(300)]
    win.model.set_rows(rows)
    pump(app, 0.2)
    beat.reset()
    t0 = time.monotonic()
    for i in range(5000):
        win.events.put({"type": "row", "key": rows[i % 300].key,
                        "status": "done", "message": "", "synced_at": time.time()})
    # 5000 events / 200 per tick / ~10 ticks per second -> a few seconds.
    # The point is that the window stays responsive *while* draining.
    pump(app, 4.0)
    left = win.events.qsize()
    check(beat.max_gap < 0.5,
          f"最长单次卡顿 {beat.max_gap * 1000:.0f}ms < 500ms（预算生效）")
    check(left == 0, f"事件最终全部处理完（剩余 {left}）")
    check(beat.ticks > 40,
          f"排空过程中界面持续响应（{beat.ticks} 次心跳）")
    win.model.clear()
    pump(app, 0.2)

    # ---------------------------------------------------------------- B
    print("\n[B] worker 已结束但队列仍在滴答：必须仍然进入完成态")
    win._running = True
    win.btn_preview.setEnabled(False)
    win.btn_start.setEnabled(False)
    win.btn_cancel.setEnabled(True)

    class DeadWorker:
        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

        cancel_event = threading.Event()

    win.worker = DeadWorker()
    stop = threading.Event()

    def trickle() -> None:
        # keeps the queue non-empty so `events.empty()` is never true
        while not stop.is_set():
            win.events.put({"type": "log", "text": "."})
            time.sleep(0.005)

    t = threading.Thread(target=trickle, daemon=True)
    t.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and win._running:
        app.processEvents()
        time.sleep(0.004)
    stop.set()
    t.join(timeout=1)
    pump(app, 0.5)
    check(not win._running, "运行已标记结束（不会被队列持续有事件卡住）")
    check(win.btn_preview.isEnabled() and win.btn_start.isEnabled(),
          "预览/开始按钮已恢复可用")
    check(win.btn_cancel.isEnabled() is False, "取消按钮已禁用")
    while not win.events.empty():
        win.events.get_nowait()

    # ---------------------------------------------------------------- C
    print("\n[C] 主线程真的卡死 6 秒：看门狗要记录并恢复")
    win._heartbeat = time.monotonic()
    time.sleep(6.5)                       # no processEvents at all -> frozen UI
    record_before = safety.recent()
    check("UI stall" in record_before, "看门狗把冻结写进了日志")
    win.events.put({"type": "log", "text": "resume"})
    pump(app, 1.5)                        # unblock and let the queued unlock run
    check(win.btn_preview.isEnabled() and win.btn_start.isEnabled(),
          "恢复后按钮可用（窗口重新可操作）")
    log_now = win.txt_log.toPlainText()
    check("自动恢复" in log_now, "运行日志里提示了已自动恢复")

    # ---------------------------------------------------------------- D
    print("\n[D] 连续预览 3 次（本地无服务器，快速失败）：界面始终响应")
    beat.reset()
    for i in range(3):
        win._on_preview()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and win._running:
            app.processEvents()
            time.sleep(0.004)
        pump(app, 0.2)
    check(beat.max_gap < 1.0, f"三次预览最长卡顿 {beat.max_gap * 1000:.0f}ms < 1000ms")
    check(win.btn_preview.isEnabled(), "预览按钮可用")
    check(win.isVisible(), "窗口仍在")

    beat.stop()
    win.close()
    pump(app, 0.3)

    print("\n" + "=" * 64)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(" -", f)
        return 1
    print("界面响应测试全部通过 ✔ —— 预览不会再让窗口卡死")
    return 0


if __name__ == "__main__":
    sys.exit(main())
