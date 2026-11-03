"""Reproduce "550 Permission denied" on MKD for absolute paths.

Real embedded FTP services (routers, cheap NAS) differ in how a directory may be
created.  Three personalities are covered here:

  A. absolute ``MKD /a/b/c`` is refused (550) but ``CWD /a/b`` + ``MKD c`` works
  B. ``MKD`` works, but ``CWD`` into the new folder is refused (550)
  C. the folder already exists and both ``MKD`` and ``CWD`` answer 550
     ("File exists" is reported as a permission error)

Run: python tools/test_mkdir_modes.py
"""
from __future__ import annotations

import ftplib
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

from app import i18n                                                  # noqa: E402
from app.config import Config, Options, ServerConfig                  # noqa: E402
from app.engine import SyncEngine                                     # noqa: E402
from app.models import Job                                            # noqa: E402
from app.state import StateDB                                         # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


class _NoMlsd:
    """Common: no MLSD / OPTS / MDTM / MFMT, like the user's router."""

    def ftp_OPTS(self, line):
        self.respond("501 Option not understood.")

    def ftp_MLSD(self, path):
        self.respond("500 Unknown command.")

    def ftp_MDTM(self, path):
        self.respond("500 Unknown command.")

    def ftp_MFMT(self, path, timeval):
        self.respond("500 Unknown command.")


class AbsoluteMkdDenied(_NoMlsd, FTPHandler):
    """A: the server resolves MKD against the cwd only, absolute paths fail.

    pyftpdlib converts the argument to a filesystem path before calling us, so the
    check is "is the parent of the target the current directory?" - which is true
    exactly when the client did CWD parent + MKD name.
    """

    def ftp_MKD(self, path):
        # compare in FTP space: ftp_MKD receives a filesystem path
        parent_ftp = self.fs.fs2ftp(os.path.dirname(os.path.normpath(path)))
        cwd = self.fs.cwd
        if os.path.normcase(parent_ftp) != os.path.normcase(cwd):
            self.respond("550 Permission denied.")
            return
        super().ftp_MKD(path)


class CwdIntoNewDirDenied(_NoMlsd, FTPHandler):
    """B: MKD is fine, but CWD into a freshly created folder is refused."""

    def ftp_CWD(self, path):
        # refuse CWD for anything created during this process lifetime
        target = self.fs.ftp2fs(path)
        if os.path.isdir(target) and not getattr(self, "_allowed", set()).__contains__(target):
            if target not in getattr(type(self), "_known", set()):
                self.respond("550 Permission denied.")
                return
        super().ftp_CWD(path)


class CwdOnlyWrites(_NoMlsd, FTPHandler):
    """TP-LINK style: STOR / DELE / RMD only work inside the current directory.

    Absolute paths are refused with 550 even when the folder exists and is
    writable - the session must CWD into the parent first.
    """

    def _inside_cwd(self, path: str) -> bool:
        try:
            parent = self.fs.fs2ftp(os.path.dirname(os.path.normpath(path)))
        except Exception:
            return False
        cwd = (self.fs.cwd or "/").rstrip("/") or "/"
        return parent.rstrip("/") == cwd

    def ftp_STOR(self, file, mode="w"):
        if not self._inside_cwd(file):
            self.respond("550 Permission denied.")
            return
        super().ftp_STOR(file, mode)

    def ftp_DELE(self, path):
        if not self._inside_cwd(path):
            self.respond("550 Permission denied.")
            return
        super().ftp_DELE(path)

    def ftp_RMD(self, path):
        if not self._inside_cwd(path):
            self.respond("550 Delete operation failed.")
            return
        super().ftp_RMD(path)


class ExistsIsDenied(_NoMlsd, FTPHandler):
    """C: MKD and CWD on an existing folder both answer 550."""

    def ftp_MKD(self, path):
        self.respond("550 Permission denied.")

    def ftp_CWD(self, path):
        try:
            target = self.fs.ftp2fs(path)
        except Exception:
            target = ""
        if target and os.path.isdir(target) and os.path.abspath(target) != os.path.abspath(self.fs.root):
            self.respond("550 Permission denied.")
            return
        super().ftp_CWD(path)


def serve(handler, root: Path, port: int):
    auth = DummyAuthorizer()
    auth.add_user("u", "p", str(root), perm="elradfmwMT")
    handler.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.7)
    return srv


def make_cfg(port: int, src: Path, remote: str) -> Config:
    cfg = Config()
    cfg.server = ServerConfig(host="127.0.0.1", port=port, username="u",
                              password_token="", protocol="ftp", timeout=20)
    cfg.server.set_password("p")
    cfg.server.concurrency = 1
    cfg.options = Options(retries=0)
    cfg.jobs = [Job(id="j", source=str(src), kind="dir", remote=remote)]
    return cfg


def run_sync(cfg: Config, state: StateDB):
    logs: list[str] = []

    def sink(ev):
        if ev["type"] == "log":
            logs.append(ev["text"])

    return SyncEngine(cfg, state, sink).run(), logs


def seed(src: Path) -> None:
    """Top level dirs whose names look like the report (Claw, Gold, JnJ, ...)."""
    for name in ("Claw", "Gold", "JnJ", "automation-2026-09-25-15-16-56"):
        (src / name / "sub").mkdir(parents=True)
        (src / name / "a.txt").write_text("a" * 100)
        (src / name / "sub" / "b.txt").write_text("b" * 100)
    (src / "root.txt").write_text("r" * 10)


def scenario_absolute_denied(tmp: Path) -> None:
    print("\n[A] 服务器只接受相对 MKD（绝对路径回 550）")
    root, src = tmp / "rA", tmp / "sA"
    root.mkdir()
    seed(src)
    srv = serve(AbsoluteMkdDenied, root, 2211)
    cfg = make_cfg(2211, src, "/volume(sda1)/Synctest")
    st = StateDB(str(tmp / "A.db"))
    try:
        s, logs = run_sync(cfg, st)
        check(s.failed == 0, f"无失败（{s.failed}）")
        check(s.uploaded_new == 9, f"9 个文件全部上传（{s.uploaded_new}）")
        for name in ("Claw", "Gold", "JnJ", "automation-2026-09-25-15-16-56"):
            check((root / "volume(sda1)" / "Synctest" / name / "sub" / "b.txt").exists(),
                  f"{name}/sub/b.txt 已上传")
        s2, _ = run_sync(cfg, st)
        check(any("建目录改用" in l for l in logs),
              "日志说明已自动改用其他建目录方式")
        s2, _ = run_sync(cfg, st)
        check(s2.uploaded_new == 0 and s2.uploaded_changed == 0,
              f"二次运行零传输（新{s2.uploaded_new}/改{s2.uploaded_changed}）")
    finally:
        st.close()
        srv.close_all()


def scenario_cwd_denied(tmp: Path) -> None:
    print("\n[B] MKD 正常，但 CWD 进入新目录被拒（不能靠 CWD 验证）")
    root, src = tmp / "rB", tmp / "sB"
    root.mkdir()
    (root / "volume(sda1)").mkdir()
    (root / "volume(sda1)" / "Synctest").mkdir()
    seed(src)
    CwdIntoNewDirDenied._known = set()
    srv = serve(CwdIntoNewDirDenied, root, 2212)
    cfg = make_cfg(2212, src, "/volume(sda1)/Synctest")
    st = StateDB(str(tmp / "B.db"))
    try:
        s, logs = run_sync(cfg, st)
        check(s.failed == 0, f"无失败（{s.failed}）")
        check(s.uploaded_new == 9, f"9 个文件全部上传（{s.uploaded_new}）")
    finally:
        st.close()
        srv.close_all()


def scenario_exists_denied(tmp: Path) -> None:
    print("\n[C] 目录已存在时 MKD 与 CWD 都回 550（应视为正常，等同用户现状）")
    root, src = tmp / "rC", tmp / "sC"
    root.mkdir()
    target = root / "volume(sda1)" / "Synctest"
    # every folder already exists (created by an earlier run) - but MKD and CWD
    # both answer 550, so existence can only be proven from the parent listing
    for name in ("Claw", "Gold", "JnJ", "automation-2026-09-25-15-16-56"):
        (target / name / "sub").mkdir(parents=True, exist_ok=True)
    seed(src)
    srv = serve(ExistsIsDenied, root, 2213)
    cfg = make_cfg(2213, src, "/volume(sda1)/Synctest")
    st = StateDB(str(tmp / "C.db"))
    try:
        s, logs = run_sync(cfg, st)
        check(s.failed == 0, f"无失败（{s.failed}）")
        check(s.uploaded_new == 9, f"9 个文件全部上传（{s.uploaded_new}）")
        check((target / "Claw" / "a.txt").exists(), "已存在的 Claw 目录内文件已上传")
        check((target / "Claw" / "sub" / "b.txt").exists(), "已存在的子目录也可上传")
        check((target / "root.txt").exists(), "根文件已上传")
    finally:
        st.close()
        srv.close_all()


def scenario_cwd_only(tmp: Path) -> None:
    print("\n[D] TP-LINK 型：只有 CWD 进目标目录后才能 STOR/DELE（用户服务器）")
    root, src = tmp / "rD", tmp / "sD"
    root.mkdir()
    (root / "volume(sda1)" / "Synctest").mkdir(parents=True)
    seed(src)
    srv = serve(CwdOnlyWrites, root, 2214)
    cfg = make_cfg(2214, src, "/volume(sda1)/Synctest")
    st = StateDB(str(tmp / "D.db"))
    try:
        s, logs = run_sync(cfg, st)
        check(s.failed == 0, f"无失败（{s.failed}）")
        check(s.uploaded_new == 9, f"9 个文件全部上传（{s.uploaded_new}）")
        base = root / "volume(sda1)" / "Synctest"
        check((base / "Claw" / "sub" / "b.txt").exists(), "嵌套文件已上传")
        check((base / "root.txt").exists(), "根文件已上传")

        s2, _ = run_sync(cfg, st)
        check(s2.uploaded_new == 0 and s2.uploaded_changed == 0 and s2.skipped == 9,
              f"二次运行零传输（跳过 {s2.skipped}）")

        # mirror deletion must work too (DELE / RMD need the same treatment)
        (src / "root.txt").unlink()
        for f in (src / "Claw" / "sub").iterdir():
            f.unlink()
        (src / "Claw" / "sub").rmdir()
        s3, _ = run_sync(cfg, st)
        check(s3.deleted_files >= 1, f"文件已删除（{s3.deleted_files}）")
        check(s3.deleted_dirs >= 1, f"目录已删除（{s3.deleted_dirs}）")
        check(not (base / "root.txt").exists(), "远端 root.txt 已删除")
        check(not (base / "Claw" / "sub").exists(), "远端 sub 目录已删除")
    finally:
        st.close()
        srv.close_all()


def main() -> int:
    i18n.set_language("zh")
    tmp = Path(tempfile.mkdtemp(prefix="ftpsync_mkdir_"))
    try:
        scenario_absolute_denied(tmp)
        scenario_cwd_denied(tmp)
        scenario_exists_denied(tmp)
        scenario_cwd_only(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 62)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for item in FAILS:
            print(" -", item)
        return 1
    print("建目录模式测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
