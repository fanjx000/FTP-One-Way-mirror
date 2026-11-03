"""Tests for the 505 failure modes reported by the user.

Two server personalities:
  A. limited concurrency - the 2nd+ simultaneous STOR is refused with
     505 "Permission denied." (very common on router/NAS FTP services)
  B. rejects certain directory names with 505 (the MKD itself fails)

Both must end with every transferable file uploaded, and the log must explain
what happened instead of drowning the user in identical errors.

Run: python tools/test_505.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pyftpdlib.authorizers import DummyAuthorizer                     # noqa: E402
from pyftpdlib.handlers import FTPHandler                             # noqa: E402
from pyftpdlib.servers import ThreadedFTPServer                       # noqa: E402

from app.config import Config, Options, ServerConfig                  # noqa: E402
from app.engine import SyncEngine                                     # noqa: E402
from app.models import Job                                            # noqa: E402
from app.state import StateDB                                         # noqa: E402

FAILS: list[str] = []
BAD_CHARS = "#"


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


class LimitedHandler(FTPHandler):
    """Refuses a second simultaneous STOR with 505, like a cheap router does."""

    max_connections = 8
    _active = 0
    _lock = threading.Lock()
    limit = 1

    def ftp_OPTS(self, line):
        self.respond("501 Option not understood.")

    def ftp_MLSD(self, path):
        self.respond("500 Unknown command.")

    def ftp_MDTM(self, path):
        self.respond("500 Unknown command.")

    def ftp_MFMT(self, path, timeval):
        self.respond("500 Unknown command.")

    def ftp_STOR(self, file, mode="w"):
        cls = type(self)
        with cls._lock:
            busy = cls._active >= cls.limit
            if not busy:
                cls._active += 1
        if busy:
            self.respond("505 Permission denied.")
            return
        try:
            super().ftp_STOR(file, mode)
        finally:
            with cls._lock:
                cls._active -= 1


class PickyDirHandler(FTPHandler):
    """Refuses to create directories whose name contains '#', with 505."""

    def ftp_OPTS(self, line):
        self.respond("501 Option not understood.")

    def ftp_MLSD(self, path):
        self.respond("500 Unknown command.")

    def ftp_MKD(self, path):
        if any(ch in os.path.basename(path.rstrip("/")) for ch in BAD_CHARS):
            self.respond("505 Permission denied.")
            return
        super().ftp_MKD(path)

    def ftp_STOR(self, file, mode="w"):
        if not os.path.isdir(os.path.dirname(file)):
            self.respond("505 Permission denied.")
            return
        super().ftp_STOR(file, mode)


def serve(handler, root: Path, port: int):
    auth = DummyAuthorizer()
    auth.add_user("u", "p", str(root), perm="elradfmwMT")
    handler.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.7)
    return srv


def make_cfg(port: int, src: Path, remote: str, concurrency: int) -> Config:
    cfg = Config()
    cfg.server = ServerConfig(host="127.0.0.1", port=port, username="u",
                              password_token="", protocol="ftp", timeout=20)
    cfg.server.set_password("p")
    cfg.server.concurrency = concurrency
    cfg.options = Options(retries=0)
    cfg.jobs = [Job(id="j", source=str(src), kind="dir", remote=remote)]
    return cfg


def run_sync(cfg: Config, state: StateDB):
    logs: list[str] = []

    def sink(ev):
        if ev["type"] == "log":
            logs.append(ev["text"])

    s = SyncEngine(cfg, state, sink).run()
    return s, logs


def scenario_concurrency_limit(tmp: Path) -> None:
    print("\n[A] 服务器只允许 1 个上传连接，多余的返回 505")
    root, src = tmp / "rA", tmp / "sA"
    root.mkdir()
    (src / "d1").mkdir(parents=True)
    (src / "d2").mkdir(parents=True)
    for i in range(6):
        (src / "d1" / f"f{i}.txt").write_text("x" * 200)
        (src / "d2" / f"g{i}.txt").write_text("y" * 200)

    LimitedHandler.limit = 1
    srv = serve(LimitedHandler, root, 2201)
    cfg = make_cfg(2201, src, "/vol/Sync", concurrency=3)
    st = StateDB(str(tmp / "A.db"))
    try:
        t0 = time.time()
        s, logs = run_sync(cfg, st)
        dt = time.time() - t0
        print(f"     用时 {dt:.1f}s")
        check(s.failed == 0, f"最终无失败（{s.failed}）")
        check(s.uploaded_new == 12, f"12 个文件全部上传（{s.uploaded_new}）")
        check(any("单连接" in l for l in logs), "日志说明已自动改为单连接")
        check(any("正在改用单连接依次重试" in l for l in logs), "触发了单连接重试")
        check(cfg.server.concurrency == 1, "后续任务自动降低并发（内存内）")

        # second run: nothing to do even on this awkward server
        s2, _ = run_sync(cfg, st)
        check(s2.uploaded_new == 0 and s2.uploaded_changed == 0,
              f"二次运行零传输（新{s2.uploaded_new}/改{s2.uploaded_changed}）")
    finally:
        st.close()
        srv.close_all()


def scenario_bad_dir(tmp: Path) -> None:
    print("\n[B] 服务器拒绝某些目录名（MKD 返回 505）")
    root, src = tmp / "rB", tmp / "sB"
    root.mkdir()
    (src / "ok").mkdir(parents=True)
    (src / "bad#dir").mkdir(parents=True)
    (src / "ok" / "a.txt").write_text("A" * 100)
    (src / "ok" / "deep").mkdir()
    (src / "ok" / "deep" / "b.txt").write_text("B" * 100)
    for i in range(3):
        (src / "bad#dir" / f"x{i}.txt").write_text("x" * 50)

    srv = serve(PickyDirHandler, root, 2202)
    cfg = make_cfg(2202, src, "/vol/Sync", concurrency=2)
    st = StateDB(str(tmp / "B.db"))
    try:
        s, logs = run_sync(cfg, st)
        check(s.uploaded_new == 2, f"可上传的 2 个文件成功（{s.uploaded_new}）")
        check((root / "vol/Sync/ok/deep/b.txt").exists(), "正常目录下的文件已上传")
        check(s.dirs_created >= 3, f"真实创建的目录数被正确统计（{s.dirs_created}）")
        check(any("创建目录失败 bad#dir" in l for l in logs), "日志明确指出失败的目录名")
        check(any("父目录创建失败" in l for l in logs), "子文件标记为“父目录创建失败”")
        check(not any("已逐个尝试" in l and "未逐个尝试" not in l for l in logs),
              "没有逐个硬试被拒的文件")
        # 3 files blocked + 1 failed dir counted via messages
        check(s.failed == 3, f"3 个文件计为失败（{s.failed}）")
        check(any("失败明细" in l for l in logs), "输出失败明细分组")
    finally:
        st.close()
        srv.close_all()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ftpsync_505_"))
    try:
        scenario_concurrency_limit(tmp)
        scenario_bad_dir(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 62)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for item in FAILS:
            print(" -", item)
        return 1
    print("505 场景测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
