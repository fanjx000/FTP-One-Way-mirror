"""Regression tests for awkward real-world FTP servers and cloud-backed sources.

Covers what a router / NAS FTP service actually does:
  * rejects ``OPTS MLST`` with 501 but still answers ``MLSD``
  * has no ``MLSD`` at all -> LIST parsing
  * has no ``MFMT`` / ``MDTM`` -> no usable remote timestamps
  * remote paths that contain spaces (and Chinese names)

Also verifies that OneDrive-style cloud placeholders (reparse points that are
real files) are still synced instead of being skipped as junctions.

Run: python tools/test_quirky_server.py
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

from pyftpdlib.authorizers import DummyAuthorizer                    # noqa: E402
from pyftpdlib.handlers import FTPHandler                            # noqa: E402
from pyftpdlib.servers import ThreadedFTPServer                      # noqa: E402
from pyftpdlib.filesystems import AbstractedFS                       # noqa: E402

from app.config import Config, Options, ServerConfig                 # noqa: E402
from app.engine import SyncEngine                                    # noqa: E402
from app.models import Job                                           # noqa: E402
from app.scanner import scan_job                                     # noqa: E402
from app.state import StateDB                                        # noqa: E402
import app.scanner as scanner_mod                                    # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


# --------------------------------------------------------------------- handlers
class NoOptsHandler(FTPHandler):
    """Rejects OPTS MLST (like the router in the bug report) but keeps MLSD."""

    def ftp_OPTS(self, line):
        self.respond("501 Option not understood.")


class ListOnlyHandler(FTPHandler):
    """No OPTS, no MLSD - only LIST, like BusyBox / old IIS."""

    def ftp_OPTS(self, line):
        self.respond("501 Option not understood.")

    def ftp_MLSD(self, path):
        self.respond("500 MLSD not understood.")


class AncientHandler(ListOnlyHandler):
    """Also lacks MFMT and MDTM, so the server has no timestamps at all."""

    def ftp_MFMT(self, path, timeval):
        self.respond("500 MFMT not understood.")

    def ftp_MDTM(self, path):
        self.respond("500 MDTM not understood.")


def serve(handler_cls, root: Path, port: int):
    auth = DummyAuthorizer()
    auth.add_user("u", "p", str(root), perm="elradfmwMT")
    handler_cls.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", port), handler_cls)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.7)
    return srv


def run_sync(cfg: Config, state: StateDB, dry: bool = False):
    logs: list[str] = []

    def sink(ev):
        if ev["type"] == "log":
            logs.append(ev["text"])

    s = SyncEngine(cfg, state, sink, dry_run=dry).run()
    return s, logs


def make_cfg(port: int, source: Path, remote: str, concurrency: int = 2) -> Config:
    cfg = Config()
    cfg.server = ServerConfig(host="127.0.0.1", port=port, username="u",
                              password_token="", protocol="ftp", timeout=20)
    cfg.server.set_password("p")
    cfg.server.concurrency = concurrency
    cfg.options = Options(excludes=["Thumbs.db", "*.tmp"])
    cfg.jobs = [Job(id="q1", source=str(source), kind="dir", remote=remote)]
    return cfg


def seed(src: Path) -> None:
    (src / "sub dir" / "深层").mkdir(parents=True, exist_ok=True)
    (src / "a file with spaces.txt").write_text("A" * 500)
    (src / "中文文件名.txt").write_text("中文内容\n" * 20)
    (src / "sub dir" / "inner.txt").write_text("inner\n" * 40)
    (src / "sub dir" / "深层" / "deep.txt").write_text("deep\n" * 10)


# --------------------------------------------------------------------- scenarios
def scenario_no_opts(tmp: Path) -> None:
    print("\n[1] 服务器拒绝 OPTS MLST（返回 501），但支持 MLSD")
    root = tmp / "r1"
    src = tmp / "s1"
    root.mkdir()
    seed(src)
    srv = serve(NoOptsHandler, root, 2151)
    remote = "/volume(sda1)/Sync test"          # mimic the reported path + a space
    cfg = make_cfg(2151, src, remote)
    st = StateDB(str(tmp / "q1.db"))
    try:
        s, logs = run_sync(cfg, st, dry=True)
        check(s.failed == 0, f"预览不再报错（失败 {s.failed}）")
        check(all("501" not in m for m in s.messages), "没有 501 错误")
        check(s.uploaded_new == 4, f"识别 4 个待上传文件（{s.uploaded_new}）")

        s2, _ = run_sync(cfg, st)
        check(s2.failed == 0, f"实际同步无失败（{s2.failed}）")
        files = sorted(str(p.relative_to(root)).replace("\\", "/")
                       for p in root.rglob("*") if p.is_file())
        base = "volume(sda1)/Sync test"
        check(len(files) == 4, f"4 个文件已上传：{files}")
        check(f"{base}/a file with spaces.txt" in files, "含空格的文件名正常")
        check(f"{base}/中文文件名.txt" in files, "中文文件名正常")
        check(f"{base}/sub dir/深层/deep.txt" in files, "含空格/中文的目录结构正常")

        s3, logs3 = run_sync(cfg, st)
        check(s3.uploaded_new == 0 and s3.uploaded_changed == 0 and s3.skipped == 4,
              f"再次运行零传输（新{s3.uploaded_new}/改{s3.uploaded_changed}/跳过{s3.skipped}）")
        check(any("OPTS MLST" in l for l in logs3), "日志说明已降级（OPTS MLST）")
        check(any("MLSD" in l for l in logs3), "仍使用 MLSD 列举（不是退化为 LIST）")
    finally:
        st.close()
        srv.close_all()


def scenario_list_only(tmp: Path) -> None:
    print("\n[2] 服务器完全没有 MLSD（仅 LIST），但支持 MDTM/MFMT")
    root = tmp / "r2"
    src = tmp / "s2"
    root.mkdir()
    seed(src)
    srv = serve(ListOnlyHandler, root, 2152)
    cfg = make_cfg(2152, src, "/bak/list")
    st = StateDB(str(tmp / "q2.db"))
    try:
        s, logs = run_sync(cfg, st)
        check(s.failed == 0, f"同步无失败（{s.failed}）")
        check(s.uploaded_new == 4, f"上传 4 个文件（{s.uploaded_new}）")
        s2, logs2 = run_sync(cfg, st)
        check(any("LIST" in l for l in logs2), "日志说明改用 LIST 解析")
        check(s2.uploaded_new == 0 and s2.uploaded_changed == 0 and s2.skipped == 4,
              f"二次运行零传输（新{s2.uploaded_new}/改{s2.uploaded_changed}/跳过{s2.skipped}）")
    finally:
        st.close()
        srv.close_all()


def scenario_no_timestamps(tmp: Path) -> None:
    print("\n[3] 古老服务器：无 MLSD / MDTM / MFMT（远端没有时间戳）")
    root = tmp / "r3"
    src = tmp / "s3"
    root.mkdir()
    seed(src)
    srv = serve(AncientHandler, root, 2153)
    cfg = make_cfg(2153, src, "/ancient")
    st = StateDB(str(tmp / "q3.db"))
    try:
        s, _ = run_sync(cfg, st)
        check(s.failed == 0, f"首次同步无失败（{s.failed}）")
        check(s.uploaded_new == 4, f"上传 4 个文件（{s.uploaded_new}）")

        s2, _ = run_sync(cfg, st)
        check(s2.uploaded_new == 0 and s2.uploaded_changed == 0 and s2.skipped == 4,
              f"无变化时零传输（新{s2.uploaded_new}/改{s2.uploaded_changed}/跳过{s2.skipped}）")

        # same size, new content, new mtime -> must still be detected
        target = src / "a file with spaces.txt"
        time.sleep(1.1)
        target.write_text("B" * 500)
        s3, _ = run_sync(cfg, st)
        check(s3.uploaded_changed == 1,
              f"同大小的修改仍被识别（更新 {s3.uploaded_changed}）")
        check((root / "ancient" / "a file with spaces.txt").read_text() == "B" * 500,
              "远端内容已更新")

        # deleted locally -> removed remotely, on a server without timestamps
        os.remove(target)
        s4, _ = run_sync(cfg, st)
        check(s4.deleted_files == 1, f"删除已镜像（删除 {s4.deleted_files}）")
    finally:
        st.close()
        srv.close_all()


def scenario_cloud_files(tmp: Path) -> None:
    print("\n[4] OneDrive / 云端占位文件必须被同步（不能当作联接跳过）")
    src = tmp / "s4"
    (src / "sub").mkdir(parents=True)
    (src / "cloud1.jpg").write_bytes(b"x" * 100)
    (src / "sub" / "cloud2.pdf").write_bytes(b"y" * 200)
    (src / "normal.txt").write_text("normal\n")

    job = Job(id="c1", source=str(src), kind="dir", remote="/x")
    opts = Options()

    # the real decision function: OneDrive placeholder attribute bits
    class _Attr:
        def __init__(self, attrs):
            self.st_file_attributes = attrs

    check(scanner_mod._is_cloud_file(0x400020) is True,
          "0x400020（ARCHIVE|RECALL_ON_DATA_ACCESS）判定为云端占位文件")
    check(scanner_mod._is_cloud_file(0x20) is False, "普通文件不判定为占位文件")
    check(scanner_mod._is_cloud_file(0x420) is False, "纯 REPARSE 文件不当作云端文件")

    original_reparse, original_cloud = scanner_mod._is_reparse, scanner_mod._is_cloud_file
    scanner_mod._is_reparse = lambda entry: not entry.is_dir()   # files look like reparse pts
    scanner_mod._is_cloud_file = lambda attrs: True              # ...that are cloud placeholders
    try:
        entries, _warn = scan_job(job, opts)
        names = {r for r, e in entries.items() if not e.is_dir}
        check(names == {"cloud1.jpg", "sub/cloud2.pdf", "normal.txt"},
              f"云端占位文件全部保留（{sorted(names)}）")
        check("sub" in entries and entries["sub"].is_dir, "子目录仍在列表中")
    finally:
        scanner_mod._is_reparse, scanner_mod._is_cloud_file = original_reparse, original_cloud

    # opt-in: do not hydrate cloud placeholders at all
    opts_skip = Options(skip_cloud_only=True)
    scanner_mod._is_reparse = lambda entry: not entry.is_dir()
    scanner_mod._is_cloud_file = lambda attrs: True
    try:
        entries3, warn3 = scan_job(job, opts_skip)
        check(not [e for e in entries3.values() if not e.is_dir],
              "勾选后不下载云端文件（本地一个都不上传）")
        check(any("跳过" in w for w in warn3), "日志提示已跳过云端文件")
    finally:
        scanner_mod._is_reparse, scanner_mod._is_cloud_file = original_reparse, original_cloud

    # a real junction inside the tree must still be skipped
    link = src / "junction_to_sub"
    try:
        import _winapi
        _winapi.CreateJunction(str(src / "sub"), str(link))
        entries2, _ = scan_job(job, opts)
        check("junction_to_sub" not in entries2, "目录联接被跳过（防止循环）")
    except Exception as exc:  # pragma: no cover - only on Windows
        print(f"     (跳过联接测试：{exc})")


def scenario_single_file_space(tmp: Path) -> None:
    print("\n[5] 单文件任务 + 含空格的远端目录，且服务器不认 OPTS")
    root = tmp / "r5"
    src = tmp / "s5"
    root.mkdir()
    src.mkdir()
    f = src / "我的 报表.xlsx"
    f.write_bytes(b"PK\x03\x04" + b"0" * 2000)
    srv = serve(NoOptsHandler, root, 2155)
    cfg = Config()
    cfg.server = ServerConfig(host="127.0.0.1", port=2155, username="u",
                              password_token="", protocol="ftp", timeout=20)
    cfg.server.set_password("p")
    cfg.jobs = [Job(id="sf", source=str(f), kind="file", remote="/报表 备份")]
    st = StateDB(str(tmp / "q5.db"))
    try:
        s, _ = run_sync(cfg, st)
        check(s.failed == 0, f"单文件同步无失败（{s.failed}）")
        check((root / "报表 备份" / "我的 报表.xlsx").exists(), "文件已上传到含空格目录")
        s2, _ = run_sync(cfg, st)
        check(s2.uploaded_new == 0 and s2.uploaded_changed == 0, "二次运行零传输")
    finally:
        st.close()
        srv.close_all()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ftpsync_quirky_"))
    try:
        scenario_no_opts(tmp)
        scenario_list_only(tmp)
        scenario_no_timestamps(tmp)
        scenario_cloud_files(tmp)
        scenario_single_file_space(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 62)
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for item in FAILS:
            print(" -", item)
        return 1
    print("怪异服务器 / 云端文件测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
