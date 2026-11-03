"""Variant tests: explicit FTPS, and servers without MLSD (LIST fallback).

Run: python tools/test_variants.py
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
from pyftpdlib.handlers import FTPHandler, TLS_FTPHandler            # noqa: E402
from pyftpdlib.servers import ThreadedFTPServer                      # noqa: E402

from app import ftpclient                                            # noqa: E402
from app.config import Config, ServerConfig                          # noqa: E402
from app.engine import SyncEngine                                    # noqa: E402
from app.models import Job                                           # noqa: E402
from app.state import StateDB                                        # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def make_cert(folder: Path) -> tuple[str, str]:
    from OpenSSL import crypto
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)
    cert = crypto.X509()
    cert.get_subject().CN = "127.0.0.1"
    cert.set_serial_number(1)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(86400)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.sign(key, "sha256")
    cpath = folder / "cert.pem"
    kpath = folder / "key.pem"
    cpath.write_bytes(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    kpath.write_bytes(crypto.dump_privatekey(crypto.FILETYPE_PEM, key))
    return str(cpath), str(kpath)


def serve(handler, root: Path, port: int):
    auth = DummyAuthorizer()
    auth.add_user("u", "p", str(root), perm="elradfmwMT")
    handler.authorizer = auth
    srv = ThreadedFTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, kwargs={"timeout": 0.2}, daemon=True).start()
    time.sleep(0.7)
    return srv


def run_sync(cfg: Config, state: StateDB):
    logs: list[str] = []

    def sink(ev):
        if ev["type"] == "log":
            logs.append(ev["text"])

    return SyncEngine(cfg, state, sink).run(), logs


def scenario_ftps(tmp: Path) -> None:
    print("\n[A] FTPS（显式 TLS，自签名证书）")
    root = tmp / "ftps_root"
    src = tmp / "ftps_src"
    root.mkdir()
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("A" * 800)
    (src / "sub" / "b.txt").write_text("B" * 400)
    cert, key = make_cert(tmp)
    TLS_FTPHandler.certfile = cert
    TLS_FTPHandler.keyfile = key
    TLS_FTPHandler.tls_control_required = True
    TLS_FTPHandler.tls_data_required = True
    srv = serve(TLS_FTPHandler, root, 2141)

    cfg = Config()
    cfg.server = ServerConfig(host="127.0.0.1", port=2141, username="u",
                              password_token="", protocol="ftps", verify_tls=False)
    cfg.server.set_password("p")
    cfg.jobs = [Job(id="t1", source=str(src), kind="dir", remote="/secure/bk")]
    st = StateDB(str(tmp / "st_ftps.db"))
    s, logs = run_sync(cfg, st)
    check(s.failed == 0, f"FTPS 同步无失败（{s.failed}）")
    check((root / "secure" / "bk" / "a.txt").exists(), "文件已通过 FTPS 上传")
    check((root / "secure" / "bk" / "sub" / "b.txt").exists(), "子目录结构正确")
    s2, _ = run_sync(cfg, st)
    check(s2.uploaded_new == 0 and s2.uploaded_changed == 0, "FTPS 二次运行零传输")
    if s.failed:
        print("     logs:", "\n     ".join(logs[-6:]))
    st.close()
    srv.close_all()


def scenario_no_mlsd(tmp: Path) -> None:
    print("\n[B] 服务器不支持 MLSD（回落 LIST 解析 + MDTM 补时间）")
    root = tmp / "list_root"
    src = tmp / "list_src"
    root.mkdir()
    (src / "x" / "y").mkdir(parents=True)
    for i in range(5):
        (src / f"f{i}.txt").write_text(f"data {i}\n" * 30)
    (src / "x" / "y" / "deep.txt").write_text("deep\n" * 20)
    srv = serve(FTPHandler, root, 2142)

    original = ftpclient.FtpSession._mlsd_walk

    def no_mlsd(self, *a, **kw):
        raise ftplib.error_perm("500 MLSD not understood")

    ftpclient.FtpSession._mlsd_walk = no_mlsd
    try:
        cfg = Config()
        cfg.server = ServerConfig(host="127.0.0.1", port=2142, username="u",
                                  password_token="", protocol="ftp")
        cfg.server.set_password("p")
        cfg.jobs = [Job(id="t2", source=str(src), kind="dir", remote="/plain/bk")]
        st = StateDB(str(tmp / "st_list.db"))
        s, logs = run_sync(cfg, st)
        check(s.failed == 0, f"无 MLSD 时同步无失败（{s.failed}）")
        check(s.uploaded_new == 6, f"上传 6 个文件（{s.uploaded_new}）")
        check((root / "plain" / "bk" / "x" / "y" / "deep.txt").exists(), "嵌套结构正确")

        s2, logs2 = run_sync(cfg, st)
        check(s2.uploaded_new == 0 and s2.uploaded_changed == 0,
              f"二次运行零传输（新{s2.uploaded_new}/改{s2.uploaded_changed}）")
        check(any("MLSD" in l for l in logs2), "日志提示已降级为 LIST 解析")
        (src / "f0.txt").write_text("changed\n" * 40)
        (src / "new.txt").write_text("new\n")
        s3, _ = run_sync(cfg, st)
        check(s3.uploaded_changed == 1 and s3.uploaded_new == 1,
              f"LIST 模式下也能识别变更（改{s3.uploaded_changed}/新{s3.uploaded_new}）")
        st.close()
    finally:
        ftpclient.FtpSession._mlsd_walk = original
        srv.close_all()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ftpsync_var_"))
    try:
        scenario_ftps(tmp)
        scenario_no_mlsd(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 60)
    if FAILS:
        print(f"失败 {len(FAILS)} 项")
        return 1
    print("变体测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
