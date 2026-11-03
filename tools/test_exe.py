"""Full-stack test of the frozen exe: real FTP server, real sync, real UI render.

Run:  python tools/test_exe.py [path\\to\\FtpSync.exe]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pyftpdlib.authorizers import DummyAuthorizer            # noqa: E402
from pyftpdlib.handlers import FTPHandler                    # noqa: E402
from pyftpdlib.servers import ThreadedFTPServer              # noqa: E402

from app import dpapi                                        # noqa: E402

def _default_exe() -> Path:
    """The shipped build is a single file; the folder layout is still supported."""
    single = ROOT / "dist" / "FtpSync.exe"
    if single.exists():
        return single
    return ROOT / "dist" / "FtpSync" / "FtpSync.exe"


EXE = Path(sys.argv[1]) if len(sys.argv) > 1 else _default_exe()


def _local_copy(path: Path) -> Path:
    """Run a copy on the local disk.

    A one-file build on a network share unpacks ~29 MB over SMB on every launch
    (~35 s); from %%LOCALAPPDATA%% it takes a couple of seconds.
    """
    import shutil
    import tempfile
    if str(path).upper().startswith(("C:", "D:")):
        return path
    dest = Path(tempfile.gettempdir()) / "ftpsync_test_bin" / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.stat().st_mtime < path.stat().st_mtime:
        shutil.copy2(path, dest)
    return dest


EXE = _local_copy(EXE)
PORT = 2131
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    if not EXE.exists():
        print("exe not found:", EXE)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="ftpsync_exe_"))
    ftp_root = tmp / "ftproot"
    local = tmp / "local"
    appdata = tmp / "appdata"
    ftp_root.mkdir(parents=True)
    (local / "docs" / "src").mkdir(parents=True)
    appdata.mkdir()

    for i in range(4):
        (local / "docs" / f"file{i}.txt").write_text(f"content {i}\n" * 40)
    (local / "docs" / "src" / "nested.log").write_text("nested\n" * 10)
    (local / "docs" / "图片说明.txt").write_text("中文文件名测试\n" * 5)   # unicode name

    auth = DummyAuthorizer()
    auth.add_user("exe", "exe", str(ftp_root), perm="elradfmwMT")
    handler = FTPHandler
    handler.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.6)

    cfg_dir = appdata / "FtpSync"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({
        "version": 1,
        "server": {"protocol": "ftp", "host": "127.0.0.1", "port": PORT,
                   "username": "exe", "password_token": dpapi.protect("exe"),
                   "passive": True, "encoding": "utf-8", "timeout": 20,
                   "concurrency": 3, "verify_tls": False, "remote_root": "/"},
        "options": {"delete_remote_extras": True, "preserve_mtime": True,
                    "excludes": ["Thumbs.db"], "mass_delete_guard": True,
                    "mass_delete_percent": 20, "mass_delete_min": 10,
                    "follow_reparse": False, "skip_hidden": False, "retries": 2},
        "jobs": [{"id": "e1", "source": str(local / "docs"), "kind": "dir",
                  "remote": "/upload/docs", "enabled": True, "name": "文档"}],
        "window": "1280x820",
    }, ensure_ascii=False), encoding="utf-8")

    shot = tmp / "exe-run.png"
    env = dict(os.environ)
    env["APPDATA"] = str(appdata)
    t0 = time.time()
    proc = subprocess.run([str(EXE), "--selftest", str(shot), "--autosync"],
                          env=env, capture_output=True, timeout=120)
    dt = time.time() - t0
    print(f"exe exit={proc.returncode} in {dt:.1f}s")
    check(proc.returncode == 0, f"exe 正常退出（{proc.returncode}）")
    check(shot.exists() and shot.stat().st_size > 10000, "界面已渲染并截图")

    files = sorted(str(p.relative_to(ftp_root)).replace("\\", "/")
                   for p in ftp_root.rglob("*") if p.is_file())
    print("  remote:", files)
    check(len([f for f in files if f.startswith("upload/docs/")]) == 6,
          f"6 个文件已上传（实际 {len(files)}）")
    check("upload/docs/图片说明.txt" in files, "中文文件名正常")
    check("upload/docs/src/nested.log" in files, "目录结构保持")

    # second run must be a no-op
    before = {f: (ftp_root / f).stat().st_mtime for f in files}
    proc2 = subprocess.run([str(EXE), "--selftest", str(tmp / "exe-run2.png"), "--autosync"],
                           env=env, capture_output=True, timeout=120)
    after = {str(p.relative_to(ftp_root)).replace("\\", "/"): p.stat().st_mtime
             for p in ftp_root.rglob("*") if p.is_file()}
    check(proc2.returncode == 0, "第二次运行正常退出")
    check(before == after, "第二次运行未重新写入任何文件（增量生效）")

    # delete local folder -> remote must mirror the deletion
    for f in (local / "docs" / "src").iterdir():
        f.unlink()
    (local / "docs" / "src").rmdir()
    proc3 = subprocess.run([str(EXE), "--selftest", str(tmp / "exe-run3.png"), "--autosync"],
                           env=env, capture_output=True, timeout=120)
    left = [str(p.relative_to(ftp_root)).replace("\\", "/")
            for p in ftp_root.rglob("*") if p.is_file()]
    check("upload/docs/src/nested.log" not in left, f"本地删除已镜像到 FTP（{left}）")

    srv.close_all()
    if FAILS:
        print(f"\n失败 {len(FAILS)} 项")
        return 1
    print("\n打包版全链路测试通过 ✔")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
