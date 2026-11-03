"""Diagnostics must never crash, and must always explain what failed.

Servers covered:
  A. read-only account: STOR / MKD / DELE all answer 550  (the reported case)
  B. normal server: everything works
  C. server that drops the control connection in the middle

Run: python tools/test_diagnose.py
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

from pyftpdlib.authorizers import DummyAuthorizer                      # noqa: E402
from pyftpdlib.handlers import FTPHandler                             # noqa: E402
from pyftpdlib.servers import ThreadedFTPServer                       # noqa: E402

from app import diagnose, i18n                                        # noqa: E402
from app.config import ServerConfig                                   # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


class NoMlsd:
    def ftp_OPTS(self, line):
        self.respond("501 Option not understood.")

    def ftp_MLSD(self, path):
        self.respond("500 Unknown command.")

    def ftp_MDTM(self, path):
        self.respond("500 Unknown command.")

    def ftp_MFMT(self, path, timeval):
        self.respond("500 Unknown command.")


class ReadOnly(NoMlsd, FTPHandler):
    """Everything that writes answers 550."""

    def ftp_MKD(self, path):
        self.respond("550 Permission denied.")

    def ftp_STOR(self, file, mode="w"):
        self.respond("550 Permission denied.")

    def ftp_DELE(self, path):
        self.respond("550 Permission denied.")

    def ftp_RMD(self, path):
        self.respond("550 Permission denied.")


class Normal(NoMlsd, FTPHandler):
    """A well behaved server, just without the optional commands."""


class RootReadOnly(NoMlsd, FTPHandler):
    """The FTP root is read-only, real volumes are writable (typical router)."""

    def _target_in_root(self, path: str) -> bool:
        """True when the *target's parent* is the FTP root (root is read-only)."""
        try:
            parent = self.fs.fs2ftp(os.path.dirname(os.path.normpath(path)))
        except Exception:
            return True
        return parent in ("/", "")

    def ftp_MKD(self, path):
        if self._target_in_root(path):
            self.respond("550 Permission denied.")
            return
        super().ftp_MKD(path)

    def ftp_STOR(self, file, mode="w"):
        if self._target_in_root(file):
            self.respond("550 Permission denied.")
            return
        super().ftp_STOR(file, mode)


class LockedFolder(NoMlsd, FTPHandler):
    """A specific folder rejects writes."""

    def _locked(self, path: str) -> bool:
        try:
            ftp_path = self.fs.fs2ftp(os.path.dirname(os.path.normpath(path)))
        except Exception:
            return False
        return ftp_path.rstrip("/") == "/locked"

    def ftp_STOR(self, file, mode="w"):
        if self._locked(file):
            self.respond("550 Permission denied.")
            return
        super().ftp_STOR(file, mode)

    def ftp_MKD(self, path):
        if self._locked(path):
            self.respond("550 Permission denied.")
            return
        super().ftp_MKD(path)


class Hangs(NoMlsd, FTPHandler):
    """Closes the control connection when asked to store."""

    def ftp_STOR(self, file, mode="w"):
        try:
            self.close()
        except Exception:
            pass


def serve(handler, root: Path, port: int):
    auth = DummyAuthorizer()
    auth.add_user("u", "p", str(root), perm="elradfmwMT")
    handler.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.7)
    return srv


def cfg_for(port: int) -> ServerConfig:
    cfg = ServerConfig(host="127.0.0.1", port=port, username="u",
                       password_token="", protocol="ftp", timeout=10)
    cfg.set_password("p")
    return cfg


def scenario_readonly(tmp: Path) -> None:
    print("\n[A] 只读账号：STOR / MKD / DELE 全回 550（用户当前情况）")
    root = tmp / "rA"
    root.mkdir()
    (root / "keep").mkdir()
    srv = serve(ReadOnly, root, 2401)
    try:
        rep = diagnose.run(cfg_for(2401))
        text = rep.text()
        check(bool(text), "有报告输出（不再是空的 error）")
        check("── " in text, "报告包含分节标题")
        check("550" in text, "报告里带服务器的原始回复")
        check(any(k in text for k in ("无法创建", "Cannot create")),
              "明确指出无法创建目录")
        check(any(k in text for k in ("写入与删除文件", "Writing and deleting")),
              "报告覆盖写入检测")
        check(rep.problems() >= 1, f"记录了失败项（{rep.problems()}）")
        check(rep.is_blocking(), "只读账号被判定为会阻塞同步")
    finally:
        srv.close_all()


def scenario_ok(tmp: Path) -> None:
    print("\n[B] 正常服务器：全部能力可用")
    root = tmp / "rB"
    root.mkdir()
    srv = serve(Normal, root, 2402)
    try:
        rep = diagnose.run(cfg_for(2402))
        text = rep.text()
        check(rep.problems() == 0, f"没有失败项（{rep.problems()}）")
        check(not rep.is_blocking(), "正常服务器不阻塞同步")
        check("✔" in text, "报告里有通过标记")
        check(any(k in text for k in ("关键能力", "key capabilities")),
              "给出总体结论")
        leftovers = [p.name for p in root.iterdir()]
        check(not [n for n in leftovers if n.startswith("ftpsync-test")],
              f"测试用临时文件已清理（{leftovers}）")
    finally:
        srv.close_all()


def scenario_dropped(tmp: Path) -> None:
    print("\n[C] 服务器在上传时直接断开连接")
    root = tmp / "rC"
    root.mkdir()
    srv = serve(Hangs, root, 2403)
    try:
        rep = diagnose.run(cfg_for(2403))
        text = rep.text()
        check(bool(text), "有报告输出")
        check(len(text) > 80, f"报告不是空壳（{len(text)} 字符）")
    finally:
        srv.close_all()


def scenario_target_folder(tmp: Path) -> None:
    print("\n[E] 根目录只读、目标目录可写（路由器常见）")
    root = tmp / "rE"
    (root / "volume(sda1)" / "Synctest").mkdir(parents=True)
    srv = serve(RootReadOnly, root, 2404)
    try:
        rep = diagnose.run(cfg_for(2404), targets=["/volume(sda1)/Synctest"])
        text = rep.text()
        check("/volume(sda1)/Synctest" in text, "报告检查了实际目标目录")
        check(text.count("── ") >= 6, "报告分节完整")
        mkd_lines = [l for l in text.splitlines() if "MKD" in l]
        check(bool(mkd_lines), "列出建目录尝试结果")
        check(not rep.is_blocking(),
              "根目录只读但目标目录可写 → 不阻塞同步")
    finally:
        srv.close_all()


def scenario_bad_target(tmp: Path) -> None:
    print("\n[F] 目标目录本身不可写")
    root = tmp / "rF"
    (root / "locked").mkdir(parents=True)
    srv = serve(LockedFolder, root, 2405)
    try:
        rep = diagnose.run(cfg_for(2405), targets=["/locked"])
        check(rep.is_blocking(), "目标不可写被判定为阻塞同步")
        check(any(k in rep.text() for k in ("不可写", "not writable")),
              "报告指出目标目录不可写")
    finally:
        srv.close_all()


def scenario_unreachable() -> None:
    print("\n[D] 服务器不可达")
    cfg = ServerConfig(host="127.0.0.1", port=2499, username="u",
                       password_token="", protocol="ftp", timeout=3)
    cfg.set_password("p")
    rep = diagnose.run(cfg)
    check(bool(rep.text()), "有报告输出")
    check(any(k in rep.text() for k in ("连接失败", "Cannot", "refused", "拒绝")),
          "报告说明连接失败")


def main() -> int:
    i18n.set_language("zh")
    tmp = Path(tempfile.mkdtemp(prefix="ftpsync_diag_"))
    try:
        scenario_readonly(tmp)
        scenario_ok(tmp)
        scenario_dropped(tmp)
        scenario_target_folder(tmp)
        scenario_bad_target(tmp)
        scenario_unreachable()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 62)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for item in FAILS:
            print(" -", item)
        return 1
    print("诊断健壮性测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
