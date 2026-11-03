"""End-to-end test of the sync engine against a real (local) FTP server.

Run:  python tools/test_sync.py
It spins up pyftpdlib on 127.0.0.1:2121, then walks through the scenarios the
application must handle: first sync, no-op re-run, modify / add / delete,
nested folders, mtime preservation and the mass-delete guard.
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

from pyftpdlib.authorizers import DummyAuthorizer          # noqa: E402
from pyftpdlib.handlers import FTPHandler                  # noqa: E402
from pyftpdlib.servers import ThreadedFTPServer            # noqa: E402

from app.config import Config, Options, ServerConfig       # noqa: E402
from app.engine import SyncEngine                          # noqa: E402
from app.models import Job                                 # noqa: E402
from app.state import StateDB                              # noqa: E402

HOST, PORT = "127.0.0.1", 2121
USER, PWD = "tester", "secret"
FAILS = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def start_server(home: str):
    auth = DummyAuthorizer()
    auth.add_user(USER, PWD, home, perm="elradfmwMT")
    handler = FTPHandler
    handler.authorizer = auth
    handler.banner = "test ftp ready"
    srv = ThreadedFTPServer((HOST, PORT), handler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.6)
    return srv


def write(path: Path, data: bytes, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime:
        os.utime(path, (mtime, mtime))


def run_engine(cfg: Config, state: StateDB, dry=False, allow_mass=False) -> tuple:
    logs = []
    summary = {}

    def sink(ev):
        if ev["type"] == "log":
            logs.append(ev["text"])
        elif ev["type"] == "summary":
            summary["s"] = ev["summary"]

    eng = SyncEngine(cfg, state, sink, dry_run=dry, allow_mass_delete=allow_mass)
    s = eng.run()
    return s, logs


def remote_listing(root: Path) -> dict:
    out = {}
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            p = Path(dirpath) / n
            out[str(p.relative_to(root)).replace("\\", "/")] = p.read_bytes()
    return out


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ftpsync_test_"))
    src = tmp / "local"
    remote = tmp / "remote"
    src.mkdir()
    remote.mkdir()
    srv = start_server(str(remote))
    state = StateDB(str(tmp / "state.db"))

    try:
        cfg = Config()
        cfg.server = ServerConfig(host=HOST, port=PORT, username=USER, password_token="")
        cfg.server.set_password(PWD)
        cfg.server.concurrency = 3
        cfg.options = Options(excludes=["Thumbs.db", "~$*"])
        cfg.jobs = [Job(id="job1", source=str(src), kind="dir", remote="/backup/docs")]

        now = time.time()
        write(src / "a.txt", b"hello A" * 100, now - 3600)
        write(src / "b.txt", b"hello B", now - 7200)
        write(src / "sub1" / "c.txt", b"nested C" * 500, now - 1800)
        write(src / "sub1" / "deep" / "d.bin", os.urandom(300000), now - 900)
        write(src / "sub2" / "e.txt", b"e", now - 60)
        write(src / "Thumbs.db", b"ignored")

        # ---- 1. dry run writes nothing -----------------------------------
        print("\n[1] 预览模式（不应写入 FTP）")
        s, logs = run_engine(cfg, state, dry=True)
        check(s.uploaded_new == 5, f"预览识别 5 个新增文件（实际 {s.uploaded_new}）")
        check(not (remote / "backup").exists(), "预览模式未创建远端目录")

        # ---- 2. first sync ----------------------------------------------
        print("\n[2] 首次同步")
        t0 = time.time()
        s, logs = run_engine(cfg, state)
        dt1 = time.time() - t0
        check(s.failed == 0, f"无失败（{s.failed}）")
        check(s.uploaded_new == 5, f"上传 5 个文件（实际 {s.uploaded_new}）")
        files = remote_listing(remote / "backup" / "docs")
        check(set(files) == {"a.txt", "b.txt", "sub1/c.txt", "sub1/deep/d.bin", "sub2/e.txt"},
              f"远端结构一致：{sorted(files)}")
        check("Thumbs.db" not in " ".join(files), "排除规则生效（Thumbs.db 未上传）")
        check(files.get("sub1/deep/d.bin") == (src / "sub1" / "deep" / "d.bin").read_bytes(),
              "二进制内容一致")
        rm = (remote / "backup/docs/a.txt").stat().st_mtime
        check(abs(rm - (now - 3600)) <= 2, f"远端修改时间与本地一致（差 {rm - (now - 3600):.1f}s）")

        # ---- 3. no-op re-run --------------------------------------------
        print("\n[3] 无变化再次运行（应零传输）")
        t0 = time.time()
        s, logs = run_engine(cfg, state)
        dt2 = time.time() - t0
        check(s.uploaded_new == 0 and s.uploaded_changed == 0 and s.deleted_files == 0,
              f"无任何传输（新增{s.uploaded_new}/更新{s.uploaded_changed}/删除{s.deleted_files}）")
        check(s.skipped == 5, f"5 个文件被跳过（{s.skipped}）")
        print(f"       首次耗时 {dt1:.2f}s，无变化耗时 {dt2:.2f}s")

        # ---- 4. modify / add / delete -----------------------------------
        print("\n[4] 修改 + 新增 + 删除")
        write(src / "a.txt", b"hello A modified" * 50)          # size change
        write(src / "new" / "f.txt", b"brand new")              # new nested folder+file
        os.remove(src / "b.txt")                                # delete file
        shutil.rmtree(src / "sub2")                             # delete folder
        s, logs = run_engine(cfg, state)
        check(s.uploaded_changed == 1, f"更新 1 个（{s.uploaded_changed}）")
        check(s.uploaded_new == 1, f"新增 1 个（{s.uploaded_new}）")
        check(s.deleted_files == 2, f"删除 2 个文件（{s.deleted_files}）")
        check(s.deleted_dirs == 1, f"删除 1 个目录（{s.deleted_dirs}）")
        files = remote_listing(remote / "backup" / "docs")
        check(set(files) == {"a.txt", "sub1/c.txt", "sub1/deep/d.bin", "new/f.txt"},
              f"远端已镜像：{sorted(files)}")
        check(files["a.txt"] == (src / "a.txt").read_bytes(), "修改内容同步正确")
        check(not (remote / "backup/docs/sub2").exists(), "空目录已从远端移除")

        # ---- 5. same size, different mtime ------------------------------
        print("\n[5] 同大小但修改时间变化（应按时间戳识别）")
        p = src / "sub1" / "c.txt"
        data = p.read_bytes()
        time.sleep(1.1)
        p.write_bytes(data)  # same length
        s, _ = run_engine(cfg, state)
        check(s.uploaded_changed == 1, f"识别为更新（{s.uploaded_changed}）")

        # ---- 6. remote tampering is corrected ---------------------------
        print("\n[6] 远端被外部改动（应重新上传）")
        (remote / "backup/docs/a.txt").write_bytes(b"tampered")
        s, _ = run_engine(cfg, state)
        check(s.uploaded_changed >= 1, f"修正远端差异（{s.uploaded_changed}）")
        check((remote / "backup/docs/a.txt").read_bytes() == (src / "a.txt").read_bytes(),
              "远端内容已恢复为本地版本")

        # ---- 7. mass delete guard ---------------------------------------
        print("\n[7] 大批量删除保护")
        for i in range(12):
            write(src / f"bulk{i}.txt", b"x" * 10)
        run_engine(cfg, state)
        for i in range(12):
            os.remove(src / f"bulk{i}.txt")
        s, logs = run_engine(cfg, state)
        check(s.deleted_files == 0, f"默认拒绝大批量删除（实际删除 {s.deleted_files}）")
        check(any("安全阈值" in l for l in logs), "日志中给出安全阈值告警")
        s, logs = run_engine(cfg, state, allow_mass=True)
        check(s.deleted_files == 12, f"允许后删除 12 个（{s.deleted_files}）")

        # ---- 8. single file job ----------------------------------------
        print("\n[8] 单文件任务")
        single = src / "single.txt"
        write(single, b"single file")
        cfg.jobs.append(Job(id="job2", source=str(single), kind="file", remote="/backup/single"))
        s, _ = run_engine(cfg, state)
        check((remote / "backup/single/single.txt").exists(), "单文件任务上传成功")
        s, _ = run_engine(cfg, state)
        check(s.uploaded_new == 0 and s.uploaded_changed == 0, "单文件任务二次运行零传输")

        # ---- 9. missing source must not wipe the server -----------------
        print("\n[9] 源目录不存在时不得删除远端")
        cfg.jobs = [Job(id="job1", source=str(src / "does_not_exist"), kind="dir",
                        remote="/backup/docs")]
        s, logs = run_engine(cfg, state)
        check(s.failed >= 1, "任务报错")
        check((remote / "backup/docs/a.txt").exists(), "远端文件未被误删")

    finally:
        srv.close_all()
        state.close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("=" * 60))
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print("  -", f)
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
