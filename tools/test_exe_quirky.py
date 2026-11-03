"""Full-stack test of the frozen exe against a *quirky* server (the reported bug).

Server behaviour mimics a router: OPTS MLST -> 501, no MLSD, no MFMT, no MDTM,
and the remote folder contains spaces.

Run:  python tools/test_exe_quirky.py
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
sys.path.insert(0, str(ROOT / "tools"))

from pyftpdlib.authorizers import DummyAuthorizer            # noqa: E402
from pyftpdlib.servers import ThreadedFTPServer              # noqa: E402

from test_quirky_server import AncientHandler                # noqa: E402
from app import dpapi                                        # noqa: E402

_default = ROOT / "dist" / "FtpSync.exe"            # single-file build (default)
if not _default.exists():
    _default = ROOT / "dist" / "FtpSync" / "FtpSync.exe"
if not _default.exists():
    _default = ROOT / "dist_build" / "FtpSync" / "FtpSync.exe"
EXE = Path(sys.argv[1]) if len(sys.argv) > 1 else _default


def _local_copy(path: Path) -> Path:
    """Run a copy on the local disk (a one-file exe on SMB unpacks on every start)."""
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
PORT = 2181
FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    if not EXE.exists():
        print("exe not found:", EXE)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="ftpsync_exe_quirky_"))
    ftp_root = tmp / "ftproot"
    local = tmp / "local"
    appdata = tmp / "appdata"
    ftp_root.mkdir(parents=True)
    appdata.mkdir()

    (local / "Tools" / "sub 目录").mkdir(parents=True)
    (local / "Tools" / "config 文件.json").write_text('{"a": 1}\n' * 30)
    (local / "Tools" / "说明 文档.txt").write_text("中文 内容\n" * 20)
    (local / "Tools" / "sub 目录" / "nested.log").write_text("nested\n" * 10)

    auth = DummyAuthorizer()
    auth.add_user("router", "router", str(ftp_root), perm="elradfmwMT")
    AncientHandler.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", PORT), AncientHandler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.7)

    cfg_dir = appdata / "FtpSync"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({
        "version": 1,
        "server": {"protocol": "ftp", "host": "127.0.0.1", "port": PORT,
                   "username": "router", "password_token": dpapi.protect("router"),
                   "passive": True, "encoding": "utf-8", "timeout": 20,
                   "concurrency": 2, "verify_tls": False, "remote_root": "/"},
        "options": {"delete_remote_extras": True, "preserve_mtime": True,
                    "excludes": ["Thumbs.db"], "mass_delete_guard": True,
                    "mass_delete_percent": 20, "mass_delete_min": 10,
                    "follow_reparse": False, "skip_hidden": False,
                    "skip_cloud_only": False, "retries": 2},
        "jobs": [{"id": "q1", "source": str(local / "Tools"), "kind": "dir",
                  "remote": "/volume(sda1)/Sync test", "enabled": True, "name": "Tools"}],
    }, ensure_ascii=False), encoding="utf-8")

    env = dict(os.environ, APPDATA=str(appdata))
    base = ftp_root / "volume(sda1)" / "Sync test"

    t0 = time.time()
    p1 = subprocess.run([str(EXE), "--selftest", str(tmp / "shot1.png"), "--autosync"],
                        env=env, capture_output=True, timeout=180)
    print(f"run1 exit={p1.returncode} in {time.time() - t0:.1f}s")
    check(p1.returncode == 0, "首次同步正常退出（不再报 501）")
    files = sorted(str(x.relative_to(base)).replace("\\", "/")
                   for x in base.rglob("*") if x.is_file()) if base.exists() else []
    print("  remote:", files)
    check(len(files) == 3, f"3 个文件已上传（实际 {len(files)}）")
    check("config 文件.json" in files, "含空格的文件名正常")
    check("说明 文档.txt" in files, "中文 + 空格正常")
    check("sub 目录/nested.log" in files, "含空格目录结构保持")

    before = {x: (base / x).stat().st_mtime for x in files}
    p2 = subprocess.run([str(EXE), "--selftest", str(tmp / "shot2.png"), "--autosync"],
                        env=env, capture_output=True, timeout=180)
    after = {str(x.relative_to(base)).replace("\\", "/"): x.stat().st_mtime
             for x in base.rglob("*") if x.is_file()}
    check(p2.returncode == 0, "第二次运行正常退出")
    check(before == after, "第二次运行未重传（增量在无时间戳服务器上也生效）")

    # delete a local file -> mirror the deletion
    (local / "Tools" / "说明 文档.txt").unlink()
    p3 = subprocess.run([str(EXE), "--selftest", str(tmp / "shot3.png"), "--autosync"],
                        env=env, capture_output=True, timeout=180)
    left = sorted(str(x.relative_to(base)).replace("\\", "/")
                  for x in base.rglob("*") if x.is_file())
    check("说明 文档.txt" not in left, f"删除已镜像（剩 {left}）")

    srv.close_all()
    if FAILS:
        print(f"\n失败 {len(FAILS)} 项")
        for item in FAILS:
            print(" -", item)
        return 1
    print("\n打包版 × 怪异服务器 测试通过 ✔")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
