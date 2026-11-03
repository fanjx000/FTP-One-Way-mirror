"""Server capability diagnostics.

When a sync fails in a way that is not obvious from the log, this module probes
the server step by step and produces a report: which listing commands work,
whether a folder can be created (and by which method), whether files can be
written, which timestamp commands exist, and whether paths need quoting.

Robustness rules:
  * :func:`run` never raises - every section is wrapped, and the partially built
    report is always returned, so a broken server can never produce an empty
    result like "error 550" with no context.
  * Each probe records the server's own reply, so the report can be copied and
    understood without access to the machine.
"""
from __future__ import annotations

import ftplib
import io
import posixpath
import time
from typing import List, NamedTuple, Optional

from .config import ServerConfig
from .ftpclient import FtpError, FtpSession, quote, norm_remote
from .i18n import tr, trf


class TargetState(NamedTuple):
    """Outcome of probing one remote folder the app writes to."""
    path: str
    exists: bool
    writable: bool

OK = "ok"
WARN = "warn"
FAIL = "fail"
_MARK = {OK: "  ✔", WARN: "  !", FAIL: "  ✘"}


class Report:
    def __init__(self) -> None:
        self.lines: List[str] = []
        self.fails = 0
        # Problems that actually prevent a sync from working.  A read-only FTP
        # root, for example, is normal and must not count as blocking.
        self.blocking = 0

    def head(self, text: str) -> None:
        self.lines.append("")
        self.lines.append(f"── {text} " + "─" * max(3, 46 - len(text)))

    def add(self, status: str, label: str, detail: str = "") -> None:
        if status == FAIL:
            self.fails += 1
        self.lines.append(_MARK[status] + " " + label + (f"  —  {detail}" if detail else ""))

    def note(self, text: str) -> None:
        self.lines.append("     " + text)

    def text(self) -> str:
        return "\n".join(self.lines).strip("\n")

    def problems(self) -> int:
        """Number of failed checks (informational)."""
        return self.fails

    def is_blocking(self) -> bool:
        """True when the sync itself cannot succeed."""
        return self.blocking > 0


def _probe(report: Report, label: str, fn, *, missing_is_warn: bool = True):
    """Run one probe; record the outcome.  Never raises."""
    try:
        value = fn()
    except ftplib.error_perm as exc:
        code = str(exc)[:3]
        soft = missing_is_warn and code in ("500", "501", "502", "504", "550")
        report.add(WARN if soft else FAIL, label, str(exc).strip())
        return None
    except (ftplib.Error, OSError, EOFError) as exc:
        report.add(FAIL, label, str(exc).strip() or exc.__class__.__name__)
        return None
    except FtpError as exc:
        report.add(FAIL, label, str(exc))
        return None
    except Exception as exc:  # noqa: BLE001 - a probe must never break the report
        report.add(FAIL, label, f"{exc.__class__.__name__}: {exc}")
        return None

    if value is True or value is None:
        report.add(OK, label)
    elif value is False:
        report.add(WARN, label, tr("不支持"))
    else:
        report.add(OK, label, str(value))
    return value


def _section(report: Report, title: str, body) -> None:
    """Run one report section; an unexpected failure is recorded, not raised."""
    report.head(title)
    try:
        body()
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, title, f"{exc.__class__.__name__}: {exc}")


def run(cfg: ServerConfig, logger=None, targets=None) -> Report:
    """Probe the configured server.  Always returns a report, never raises.

    *targets* are the remote folders the app actually writes to (the jobs'
    destinations).  They matter because on router/NAS FTP services the root
    folder is often read-only while the real volumes are writable, so probing
    only "/" gives a misleading answer.
    """
    report = Report()
    sess = FtpSession(cfg, logger)
    try:
        _run_into(report, sess, cfg, targets or [])
    except Exception as exc:  # noqa: BLE001 - last line of defence
        report.add(FAIL, tr("诊断中断"), f"{exc.__class__.__name__}: {exc}")
    finally:
        try:
            sess.close()
        except Exception:
            pass
    if not report.lines:
        report.add(FAIL, tr("诊断没有产生任何结果"), "")
    return report


def _run_into(report: Report, sess: FtpSession, cfg: ServerConfig,
              targets: List[str]) -> None:
    # -- connect ---------------------------------------------------------
    report.head(tr("连接与登录"))
    try:
        sess.connect()
    except FtpError as exc:
        report.add(FAIL, tr("连接失败"), str(exc))
        report.blocking = 1
        return
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, tr("连接失败"), f"{exc.__class__.__name__}: {exc}")
        report.blocking = 1
        return
    report.add(OK, trf("{host}:{port} 连接成功", host=cfg.host, port=cfg.port))

    home = sess._home or "/"
    _probe(report, tr("登录成功 / 当前目录"), lambda: f"PWD = {sess.ftp.pwd()}")
    _probe(report, tr("CWD 到当前目录"), lambda: bool(sess.ftp.cwd(sess._qp(home))))
    if " " in home:
        report.note(tr("当前目录含空格，路径需要正确引用"))

    # -- listing ---------------------------------------------------------
    def listing() -> None:
        root = "/"

        def _mlsd():
            data = list(sess.ftp.mlsd(root))[:1]
            return tr("可用") if data else tr("可用（目录为空）")

        _probe(report, tr("MLSD（RFC 3659）"), _mlsd)

        def _list():
            lines: List[str] = []
            sess.ftp.retrlines(f"LIST {sess._qp(root)}", lines.append)
            first = lines[0][:70] if lines else tr("空")
            return trf("可用，首行：{line}", line=first)

        _probe(report, tr("LIST"), _list)

        def _nlst():
            return trf("可用，{n} 个条目", n=len(sess.ftp.nlst(root)))

        _probe(report, tr("NLST"), _nlst)

        report.note(tr("MLSD 不可用时，程序会自动改用 LIST 解析"))

    _section(report, tr("目录列举"), listing)

    # -- folder creation -------------------------------------------------
    created: Optional[str] = None
    target_state: List[TargetState] = []

    def mkdir_probe() -> None:
        nonlocal created
        stamp = time.strftime("ftpsync-test-%Y%m%d%H%M%S")
        base = norm_remote(posixpath.join(home, stamp, "nested"))
        for mode in ("abs", "rel", "q"):
            target = base if created is None else f"{base}-{mode}"
            if _make_deep(sess, target, mode):
                report.add(OK, trf("MKD {mode}", mode=mode), target)
                created = target
                sess._mkdir_mode = mode
                return
            report.add(WARN, trf("MKD {mode}", mode=mode), _last_reply.get(mode, ""))
        report.add(FAIL, tr("三种写法都无法创建目录"),
                   tr("该 FTP 账号可能没有写权限，或服务器禁止 MKD"))

    _section(report, tr("创建目录"), mkdir_probe)

    def verify_created() -> None:
        if not created:
            return
        _probe(report, tr("CWD 进入刚创建的目录"),
               lambda: bool(sess.ftp.cwd(created)))
        _probe(report, tr("父目录列表可验证新建目录"),
               lambda: _listed(sess, created))
        _probe(report, tr("清理测试目录"), lambda: _cleanup_deep(sess, created), )

    if created:
        _section(report, tr("新建目录的可用性"), verify_created)

    # -- files -----------------------------------------------------------
    def files() -> None:
        stamp = time.strftime("ftpsync-test-%Y%m%d%H%M%S")
        name = norm_remote(posixpath.join(home, stamp + ".txt"))

        def upload():
            with io.BytesIO(b"diagnostic") as buf:
                sess.ftp.storbinary(f"STOR {sess._qp(name)}", buf)
            return tr("可用")

        up = _probe(report, tr("上传一个测试文件"), upload, missing_is_warn=False)
        if up is None:
            report.add(FAIL, tr("无法写入文件"),
                       tr("同步一定失败：请确认该 FTP 账号对此目录有写权限，且磁盘未满"))
            return
        _probe(report, tr("删除测试文件"),
               lambda: sess.ftp.delete(sess._qp(name)) or tr("可用"),
               missing_is_warn=False)

    _section(report, tr("写入与删除文件"), files)

    # -- timestamps ------------------------------------------------------
    def stamps() -> None:
        stamp = time.strftime("ftpsync-test-%Y%m%d%H%M%S")
        name = norm_remote(posixpath.join(home, stamp + "-t.txt"))

        def make() -> bool:
            with io.BytesIO(b"x") as buf:
                sess.ftp.storbinary(f"STOR {sess._qp(name)}", buf)
            return True

        if _probe(report, tr("准备测试文件"), make, missing_is_warn=False) is None:
            report.note(tr("没有测试文件，跳过时间戳检测"))
            return

        def mfmt():
            value = time.strftime("%Y%m%d%H%M%S", time.gmtime())
            sess.ftp.sendcmd(f"MFMT {value} {sess._qp(name)}")
            return tr("可用")

        _probe(report, tr("MFMT（写入修改时间）"), mfmt)
        _probe(report, tr("MDTM（读取修改时间）"),
               lambda: sess.ftp.sendcmd(f"MDTM {sess._qp(name)}"))

        def cleanup():
            try:
                sess.ftp.delete(sess._qp(name))
            except ftplib.all_errors:
                pass
            return tr("已删除")

        _probe(report, tr("清理测试文件"), cleanup)

    _section(report, tr("时间戳命令"), stamps)

    # -- the folders the app really writes to -----------------------------
    folders: List[str] = []
    for raw in list(targets) + [home]:
        path = norm_remote(raw)
        if path not in folders:
            folders.append(path)

    def target_sections() -> None:
        for path in folders[:4]:

            def one(path: str = path) -> None:
                exists = _reachable(sess, path)
                if exists:
                    report.add(OK, tr("目录存在"))
                else:
                    report.add(WARN, tr("目录不存在"),
                               tr("同步时会先自动创建"))

                def mk_sub():
                    stamp = time.strftime("ftpsync-%H%M%S")
                    sub = norm_remote(posixpath.join(path, stamp))
                    sess.ensure_dir_checked(sub)      # same code path as a sync
                    try:
                        sess.delete_dir(sub)
                    except (ftplib.Error, OSError, EOFError):
                        pass
                    return tr("可以在该目录下建子目录")

                _probe(report, tr("建子目录"), mk_sub, missing_is_warn=False)

                def put():
                    name = norm_remote(posixpath.join(
                        path, time.strftime("ftpsync-%H%M%S.txt")))
                    target = sess._prep(name)         # same code path as a sync
                    with io.BytesIO(b"diag") as buf:
                        sess.ftp.storbinary(f"STOR {target}", buf)
                    try:
                        sess.delete_file(name)
                    except (ftplib.Error, OSError, EOFError):
                        pass
                    return tr("可以写入文件")

                def put_abs():
                    """Absolute path without CWD - some servers (TP-LINK) refuse it."""
                    name = norm_remote(posixpath.join(
                        path, time.strftime("ftpsync-abs-%H%M%S.txt")))
                    saved = sess._cwd
                    sess._cwd = None
                    try:
                        with io.BytesIO(b"diag") as buf:
                            sess.ftp.storbinary(f"STOR {name}", buf)
                    finally:
                        sess._cwd = saved
                    try:
                        sess.delete_file(name)
                    except (ftplib.Error, OSError, EOFError):
                        pass
                    return tr("绝对路径可直接写入")

                direct = _probe(report, tr("不切换目录直接写绝对路径"), put_abs)

                up = _probe(report, tr("写入文件"), put, missing_is_warn=False)
                if up is not None and direct is None:
                    report.add(OK, tr("写入方式"),
                               tr("该服务器要求在写入前先切换到目标目录（已自动处理）"))
                target_state.append(TargetState(path, exists, up is not None))
                if up is None:
                    report.add(FAIL, tr("该目录不可写"),
                               tr("同步到这里的文件都会失败，请给该账号写权限或换个目录"))

            _section(report, trf("目标目录：{path}", path=path), one)

    target_sections()

    # -- summary ---------------------------------------------------------
    report.head(tr("结论"))
    job_targets = [t for t in target_state if t.path in
                   {norm_remote(x) for x in targets}]
    bad_targets = [t for t in job_targets if not t.writable]

    if job_targets and not bad_targets:
        report.add(OK, tr("同步目标可用"),
                   tr("任务的目标目录都能正常写入，同步应可正常工作"))
        report.blocking = 0
    elif bad_targets:
        for t in bad_targets:
            report.add(FAIL, trf("目标目录不可写：{path}", path=t.path),
                       tr("请给该 FTP 账号写权限，或改用其它目录"))
        report.blocking = len(bad_targets)
    elif report.problems():
        report.add(WARN, tr("有项目失败"),
                   trf("{n} 项失败，详见上方的 ✘ 标记", n=report.problems()))
        report.blocking = report.fails
    else:
        report.add(OK, tr("关键能力全部可用"))

    root_only = [t for t in target_state
                 if t.path == "/" and not t.writable]
    if root_only and not bad_targets:
        report.add(WARN, tr("FTP 根目录只读"),
                   tr("这不影响同步：程序只往目标目录写，不会用根目录"))

    if sess._mkdir_mode and sess._mkdir_mode != "abs":
        report.add(OK, tr("建目录方式"),
                   trf("需要改用 {mode}（程序会自动使用）",
                       mode=sess._mkdir_mode))
    elif sess._mkdir_mode == "abs":
        report.add(OK, tr("建目录方式"), tr("标准写法可用"))
    if sess._mlsd_ok is False:
        report.add(OK, tr("列举方式"), tr("已自动改用 LIST 解析"))
    if sess._mlsd_ok:
        report.add(OK, tr("列举方式"), "MLSD")
    if sess._quote_paths:
        report.add(OK, tr("路径写法"), tr("该服务器要求路径加引号（已自动处理）"))
    if getattr(sess, "_needs_cwd", False):
        report.add(OK, tr("写入方式"),
                   tr("该服务器只允许写入当前目录内的文件（程序已自动先切换目录）"))
    report.add(OK, tr("同时上传的文件数建议"), tr("若出现 505/421，请设为 1"))


# --------------------------------------------------------------------- helpers
_last_reply: dict = {}


def _make_deep(sess: FtpSession, path: str, mode: str) -> bool:
    """Create every level of *path* with one strategy; True when reachable."""
    path = norm_remote(path)
    cur = ""
    for level in [l for l in path.split("/") if l]:
        cur += "/" + level
        parent, name = posixpath.split(cur)
        try:
            if mode == "abs":
                sess.ftp.sendcmd(f"MKD {sess._qp(cur)}")
            elif mode == "q":
                sess.ftp.sendcmd(f"MKD {quote(cur)}")
            else:
                _relative_mkd(sess, parent, name)
        except ftplib.error_perm as exc:
            _last_reply[mode] = str(exc).strip()
            if not _reachable(sess, cur):
                return False
        except (ftplib.Error, OSError, EOFError) as exc:
            _last_reply[mode] = str(exc).strip()
            return False
    try:
        return _reachable(sess, path)
    except Exception:  # noqa: BLE001
        return False


def _relative_mkd(sess: FtpSession, parent: str, name: str) -> None:
    cwd = None
    try:
        cwd = sess.ftp.pwd()
    except (ftplib.Error, OSError, EOFError):
        cwd = None
    try:
        if parent and parent != "/":
            sess.ftp.cwd(sess._qp(parent))
        sess.ftp.sendcmd(f"MKD {name}")
    finally:
        if cwd:
            try:
                sess.ftp.cwd(sess._qp(cwd))
            except (ftplib.Error, OSError, EOFError):
                pass


def _reachable(sess: FtpSession, path: str) -> bool:
    try:
        if _listed(sess, path):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        return sess._is_dir(path)
    except Exception:  # noqa: BLE001
        return False


def _listed(sess: FtpSession, path: str) -> bool:
    """Is *path* visible in its parent listing?"""
    parent, name = posixpath.split(norm_remote(path))
    return name in sess._list_names(parent or "/")


def _cleanup_deep(sess: FtpSession, path: str) -> str:
    path = norm_remote(path)
    parent, _ = posixpath.split(path)
    for target in (path, parent):
        if not target or target in ("/", sess._home):
            continue
        try:
            sess.ftp.rmd(sess._qp(target))
        except (ftplib.Error, OSError, EOFError):
            pass
    return tr("已删除")
