"""Thin, robust FTP / FTPS wrapper used by the sync engine.

Only the standard library is used.  This module is deliberately defensive because
real servers differ wildly.  Design notes:

  * ``MLSD`` (RFC 3659) is preferred for listing: one recursive pass returns
    type/size/modify for every entry, far cheaper than per-file SIZE+MDTM.
  * ``OPTS MLST`` is *optional*.  Many embedded servers (routers, NAS boxes,
    BusyBox / minimal vsftpd builds) answer ``501 Option not understood``; we then
    retry ``MLSD`` without the OPTS step, and if ``MLSD`` itself is unsupported we
    fall back to parsing ``LIST``.
  * ``MDTM`` fills in timestamps that ``LIST`` cannot express, ``MFMT`` writes the
    local timestamp back after upload so the next run is pure metadata comparison.
  * Paths are sent *unquoted* by default (the argument of an FTP command is "the
    rest of the line", which is what virtually every server expects).  If a server
    rejects a spaced path with 500/501 we retry with double quotes once and
    remember the convention for the rest of the session.
"""
from __future__ import annotations

import calendar
import ftplib
import posixpath
import re
import socket
import ssl
import time
from typing import Callable, Dict, List, Optional, Tuple

from .config import ServerConfig
from .i18n import tr, trf
from .models import RemoteEntry

CHUNK = 256 * 1024

# Reply codes meaning "I don't implement that command/option" - safe to downgrade.
UNSUPPORTED = ("500", "501", "502", "504")
MISSING = ("550", "450", "521")

# Facts we would like MLSD to report (RFC 3659 section 7.5.5).
MLST_FACTS = ["type", "size", "modify"]

def _reply(text: str, fallback: str) -> str:
    """Normalise an FTP reply so it always starts with a 3-digit code."""
    t = (text or "").strip()
    if not t:
        return f"550 {fallback}"
    return t if t[:3].isdigit() else f"550 {t}"


# How a directory can be created; see FtpSession._mkdir_one.
MKD_MODE_NAMES = {"abs": "MKD 绝对路径", "rel": "CWD + 相对名", "q": "MKD 引号路径"}


# --------------------------------------------------------------------------- utils
def norm_remote(path: str) -> str:
    """Normalise to an absolute POSIX path without trailing slash (root = '/')."""
    if not path:
        return "/"
    p = path.replace("\\", "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    p = posixpath.normpath(p)
    return "/" if p in ("", ".", "//") else p


def join_remote(base: str, rel: str) -> str:
    base = norm_remote(base)
    if not rel:
        return base
    return posixpath.join(base, rel) if base != "/" else "/" + rel.lstrip("/")


def quote(path: str) -> str:
    """Wrap a path in double quotes (only useful for the rare strict server)."""
    return '"' + str(path).replace('"', "") + '"'


def parse_ftp_time(value: str) -> float:
    """MLSD/MDTM timestamp (UTC, YYYYMMDDHHMMSS[.sss]) -> epoch seconds."""
    if not value:
        return 0.0
    v = str(value).strip().split(".")[0]
    try:
        return float(calendar.timegm(time.strptime(v, "%Y%m%d%H%M%S")))
    except Exception:
        return 0.0


class FtpError(Exception):
    """User friendly FTP failure."""


class _ImplicitFTPTLS(ftplib.FTP_TLS):
    """FTP_TLS that negotiates TLS immediately (implicit FTPS, port 990)."""

    def connect(self, host="", port=0, timeout=-999, source_address=None):
        if host:
            self.host = host
        if port > 0:
            self.port = port
        if timeout != -999:
            self.timeout = timeout
        self.sock = socket.create_connection(
            (self.host, self.port), self.timeout, source_address=source_address)
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock, server_hostname=self.host)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome


# --------------------------------------------------------------------------- session
class FtpSession:
    """One FTP control connection.  Not thread safe - use one per thread."""

    def __init__(self, cfg: ServerConfig, logger: Optional[Callable[[str], None]] = None):
        self.cfg = cfg
        self.log = logger or (lambda msg: None)
        self.ftp: Optional[ftplib.FTP] = None
        self._dir_cache: set = set()
        self._mfmt_ok: Optional[bool] = None
        self._mlsd_ok: Optional[bool] = None
        self._mlsd_facts: Optional[bool] = None    # does OPTS MLST work?
        self._quote_paths: Optional[bool] = None   # None = not decided yet
        self._mkdir_mode: Optional[str] = None     # "abs" | "rel" | "q"
        self._cwd: Optional[str] = None            # last known server working dir
        self._needs_cwd = False                    # server only writes inside the cwd
        self._home = "/"
        self.mode = tr("未知")                          # human readable listing mode

    # -- connection -------------------------------------------------------
    def connect(self) -> None:
        cfg = self.cfg
        if not cfg.host:
            raise FtpError(tr("未配置 FTP 服务器地址"))
        timeout = max(5, int(cfg.timeout or 30))
        try:
            if cfg.protocol == "ftpsi":
                ctx = ssl._create_unverified_context() if not cfg.verify_tls else ssl.create_default_context()
                ftp = _ImplicitFTPTLS(context=ctx, timeout=timeout, encoding=cfg.encoding or "utf-8")
                ftp.connect(cfg.host, int(cfg.port or 990))
                ftp.login(cfg.username or "anonymous", cfg.password or "")
                ftp.prot_p()
            elif cfg.protocol == "ftps":
                ctx = ssl._create_unverified_context() if not cfg.verify_tls else ssl.create_default_context()
                ftp = ftplib.FTP_TLS(context=ctx, timeout=timeout, encoding=cfg.encoding or "utf-8")
                ftp.connect(cfg.host, int(cfg.port or 21))
                ftp.auth()
                ftp.login(cfg.username or "anonymous", cfg.password or "")
                ftp.prot_p()
            else:
                ftp = ftplib.FTP(timeout=timeout, encoding=cfg.encoding or "utf-8")
                ftp.connect(cfg.host, int(cfg.port or 21))
                ftp.login(cfg.username or "anonymous", cfg.password or "")
            ftp.set_pasv(bool(cfg.passive))
            ftp.voidcmd("TYPE I")
            self.ftp = ftp
            try:
                self._home = norm_remote(ftp.pwd())
            except Exception:
                self._home = "/"
            self._dir_cache = {"/", self._home}
        except socket.gaierror:
            raise FtpError(tr("无法解析主机名：") + f"{cfg.host}")
        except (socket.timeout, TimeoutError):
            raise FtpError(tr("连接超时：") + f"{cfg.host}:{cfg.port}")
        except ConnectionRefusedError:
            raise FtpError(tr("服务器拒绝连接：") + f"{cfg.host}:{cfg.port}")
        except ftplib.error_perm as exc:
            raise FtpError(tr("登录失败：") + f"{exc}")
        except ssl.SSLError as exc:
            raise FtpError(tr("TLS 握手失败：") + f"{exc}")
        except OSError as exc:
            raise FtpError(tr("网络错误：") + f"{exc}")

    def close(self) -> None:
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:
                try:
                    self.ftp.close()
                except Exception:
                    pass
            self.ftp = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    @property
    def connected(self) -> bool:
        return self.ftp is not None

    def alive(self) -> bool:
        if self.ftp is None:
            return False
        try:
            self.ftp.voidcmd("NOOP")
            return True
        except Exception:
            return False

    # -- path conventions -------------------------------------------------
    def _qp(self, path: str) -> str:
        return quote(path) if self._quote_paths else str(path)

    def _remember(self, quoted: bool) -> None:
        if self._quote_paths is not quoted:
            if quoted and self._quote_paths is not None:
                self.log(tr("该服务器要求路径加引号，已自动切换"))
            self._quote_paths = quoted

    def _retry_quoted(self, exc: Exception, path: str) -> bool:
        """Should we retry this failed command with the path quoted?"""
        return (str(exc)[:3] in ("500", "501")
                and " " in str(path)
                and self._quote_paths is not True)

    def cmd(self, verb: str, path: str) -> str:
        """Send ``VERB path``, adapting to the server's quoting convention."""
        attempts = (self._quote_paths,) if self._quote_paths is not None else (False, True)
        last: Optional[Exception] = None
        for use_quotes in attempts:
            arg = quote(path) if use_quotes else str(path)
            try:
                resp = self.ftp.sendcmd(f"{verb} {arg}")
                self._remember(use_quotes)
                return resp
            except ftplib.error_perm as exc:
                last = exc
                if not use_quotes and self._retry_quoted(exc, path):
                    continue
                raise
        raise last if last else ftplib.error_perm("500 command failed")

    # -- directories ------------------------------------------------------
    def ensure_dir(self, path: str) -> int:
        """Create *path* (and parents) if missing.  Returns number of MKD calls.

        Failures are swallowed on purpose (the caller may not care); use
        :meth:`ensure_dir_checked` when the directory really has to exist.
        """
        path = norm_remote(path)
        if path in ("/", ""):
            return 0
        made = 0
        cur = ""
        for part in [p for p in path.split("/") if p]:
            cur += "/" + part
            if cur in self._dir_cache:
                continue
            try:
                if self._mkdir_one(cur):
                    made += 1
                self._dir_cache.add(cur)
            except ftplib.all_errors:
                pass  # caller verifies by listing
        return made

    def ensure_dir_checked(self, path: str) -> int:
        """Create *path* and verify every level really exists.

        Raises :class:`FtpError` with the server's own reply as soon as a level
        cannot be created, so the caller can report the real cause instead of
        letting every child upload fail one by one.
        """
        path = norm_remote(path)
        if path in ("/", ""):
            return 0
        made = 0
        cur = ""
        for part in [p for p in path.split("/") if p]:
            cur += "/" + part
            if cur in self._dir_cache:
                continue
            try:
                if self._mkdir_one(cur):
                    made += 1
                self._dir_cache.add(cur)
            except FtpError:
                raise
            except ftplib.error_perm as exc:
                raise FtpError(f"{cur} → {str(exc).strip()}")
            except ftplib.all_errors as exc:
                raise FtpError(f"{cur} → {str(exc).strip() or 'MKD failed'}")
        return made

    def _mkdir_one(self, path: str) -> bool:
        """Create a single directory level.  Returns True when it was created.

        Cheap FTP services disagree about how a directory may be created, so up to
        three strategies are tried (the first one that works is remembered):

        ``abs``  ``MKD /full/path``            - works on most servers
        ``rel``  ``CWD /parent`` + ``MKD name`` - routers that ignore absolute args
        ``q``    ``MKD "/full/path"``          - servers that want the path quoted

        When every attempt is refused the directory is looked up in its parent
        listing; an already existing folder is not an error.  Verification by
        listing (instead of ``CWD``) matters because some servers refuse ``CWD``
        into folders the client just created, or into folders that already exist.
        """
        path = norm_remote(path)
        if path in ("/", ""):
            return False
        parent, name = posixpath.split(path)

        order = ["abs", "rel", "q"]
        if self._mkdir_mode in order:
            order.remove(self._mkdir_mode)
            order.insert(0, self._mkdir_mode)

        last = ""
        for mode in order:
            try:
                self._mkdir_attempt(mode, path, parent, name)
                if self._mkdir_mode != mode:
                    if self._mkdir_mode is not None and mode != "abs":
                        self.log(trf("建目录改用 {mode} 方式（该服务器不接受标准写法）",
                                     mode=MKD_MODE_NAMES.get(mode, mode)))
                    self._mkdir_mode = mode
                return True
            except ftplib.error_perm as exc:
                last = str(exc).strip()
            except ftplib.all_errors as exc:
                last = str(exc).strip()
            # refused - maybe it simply already exists
            if self._dir_exists_listing(path):
                self._mkdir_mode = mode
                return False

        raise ftplib.error_perm(_reply(last, "MKD failed"))

    def _mkdir_attempt(self, mode: str, path: str, parent: str, name: str) -> None:
        if mode == "abs":
            self.cmd("MKD", path)
        elif mode == "q":
            self.ftp.sendcmd(f"MKD {quote(path)}")
        else:  # "rel"
            cwd = None
            try:
                cwd = self.ftp.pwd()
            except ftplib.all_errors:
                cwd = None
            try:
                if parent and parent != "/":
                    self.cmd("CWD", parent)
                self.ftp.sendcmd(f"MKD {name}")
            finally:
                self._cwd = None
                if cwd:
                    try:
                        self.ftp.cwd(self._qp(cwd))
                    except ftplib.all_errors:
                        pass

    def _dir_exists_listing(self, path: str) -> bool:
        """Is *path* an existing directory?  Decided from the parent listing."""
        path = norm_remote(path)
        if path in ("/", ""):
            return True
        parent, name = posixpath.split(path)
        parent = parent or "/"
        try:
            names = {n for n in self._list_names(parent) if n == name}
            if names:
                return True
        except ftplib.all_errors:
            pass
        # last resort: try to change into it
        return self._is_dir(path)

    def _list_names(self, path: str) -> List[str]:
        """All entry names of *path* (files and directories)."""
        out: List[str] = []
        try:
            for name, _facts in self._mlsd_fetch(path):
                if name not in (".", ".."):
                    out.append(name)
            return out
        except ftplib.all_errors:
            pass
        lines: List[str] = []
        try:
            self._list_lines(path, lines)
        except ftplib.all_errors:
            return out
        for line in lines:
            info = _parse_list_line(line)
            if info and info[3] not in (".", ".."):
                out.append(info[3])
        return out

    def _is_dir(self, path: str) -> bool:
        """True when *path* is an existing directory (restores the cwd)."""
        try:
            cur = self.ftp.pwd()
        except Exception:
            cur = None
        try:
            self.ftp.cwd(self._qp(path))
            self._cwd = norm_remote(path)
            return True
        except ftplib.error_perm:
            return False
        except ftplib.all_errors:
            return False
        finally:
            self._cwd = None
            if cur:
                try:
                    self.ftp.cwd(self._qp(cur))
                except ftplib.all_errors:
                    pass


    def dir_exists(self, path: str) -> bool:
        path = norm_remote(path)
        if path == "/":
            return True
        try:
            cur = self._home or "/"
            self.cmd("CWD", path)
            self.cmd("CWD", cur)
            self._cwd = None
            return True
        except ftplib.error_perm:
            return False
        except Exception:
            return False

    def list_dirs(self, path: str) -> List[str]:
        """Immediate sub-directory names of *path* (for the remote folder picker)."""
        path = norm_remote(path)
        out: List[str] = []
        try:
            for name, facts in self._mlsd_fetch(path):
                if name in (".", ".."):
                    continue
                if (facts.get("type") or "").lower() in ("dir", "cdir", "pdir"):
                    out.append(name)
            self._mlsd_ok = True
        except Exception:
            lines: List[str] = []
            try:
                self._list_lines(path, lines)
            except Exception:
                return out
            for line in lines:
                info = _parse_list_line(line)
                if info and info[0]:
                    out.append(info[3])
        return sorted(out, key=str.lower)

    # -- listing ----------------------------------------------------------
    def list_tree(self, base: str, max_depth: int = 64) -> Dict[str, RemoteEntry]:
        """Recursively list *base*.  Keys are POSIX relative paths."""
        base = norm_remote(base)
        entries: Dict[str, RemoteEntry] = {}

        if self._mlsd_ok is not False:
            try:
                have_sizes = self._mlsd_walk(base, entries, max_depth)
                if have_sizes or not any(not e.is_dir for e in entries.values()):
                    self._mlsd_ok = True
                    self.mode = "MLSD"
                    return entries
                self.log(tr("服务器的 MLSD 未返回文件大小，改用 LIST 解析"))
                entries.clear()
                self._mlsd_ok = False
            except ftplib.error_perm as exc:
                code = str(exc)[:3]
                if code in UNSUPPORTED and not entries:
                    self.log(trf("服务器不支持 MLSD（{p0}），改用 LIST 解析", p0=str(exc).strip()))
                    self._mlsd_ok = False
                else:
                    raise
            except ftplib.error_temp:
                if not entries:
                    self._mlsd_ok = False
                    self.log(tr("MLSD 临时失败，改用 LIST 解析"))
                else:
                    raise

        self.mode = "LIST"
        self._list_walk(base, entries, max_depth)
        return entries

    def _probe_opts(self) -> bool:
        """Ask once whether ``OPTS MLST`` is supported.

        Probed separately so a rejected OPTS is never mistaken for a path or
        quoting problem: it is a capability question, not a failed file command.
        """
        try:
            self.ftp.sendcmd("OPTS MLST " + ";".join(MLST_FACTS) + ";")
            return True
        except ftplib.error_perm:
            self.log(tr("服务器不支持 OPTS MLST，改用 MLSD 默认属性"))
            return False
        except ftplib.all_errors:
            return False

    def _mlsd_fetch(self, path: str) -> List[Tuple[str, dict]]:
        """MLSD with graceful degradation when ``OPTS MLST`` is rejected."""
        if self._mlsd_facts is None:
            self._mlsd_facts = self._probe_opts()
        attempts = (self._quote_paths,) if self._quote_paths is not None else (False, True)
        last: Optional[Exception] = None
        for use_quotes in attempts:
            arg = quote(path) if use_quotes else str(path)
            try:
                if self._mlsd_facts:
                    data = list(self.ftp.mlsd(arg, facts=MLST_FACTS))
                else:
                    data = list(self.ftp.mlsd(arg))
                self._remember(use_quotes)
                return data
            except ftplib.error_perm as exc:
                last = exc
                if not use_quotes and self._retry_quoted(exc, path):
                    continue
                raise
        raise last if last else ftplib.error_perm("500 MLSD failed")

    def _mlsd_walk(self, base: str, out: Dict[str, RemoteEntry],
                   max_depth: int) -> bool:
        """Walk with MLSD.  Returns True when file sizes were actually reported."""
        have_size = False
        stack = [(base, "", 0)]
        while stack:
            path, prefix, depth = stack.pop()
            children = []
            for name, facts in self._mlsd_fetch(path):
                if name in (".", ".."):
                    continue
                typ = (facts.get("type") or "").lower()
                rel = prefix + name
                mtime = parse_ftp_time(facts.get("modify", ""))
                raw_size = facts.get("size")
                try:
                    size = int(raw_size) if raw_size not in (None, "") else -1
                except (TypeError, ValueError):
                    size = -1
                if typ in ("dir", "cdir", "pdir"):
                    out[rel] = RemoteEntry(rel, 0, mtime, True)
                    if depth < max_depth:
                        children.append((join_remote(path, name), rel + "/", depth + 1))
                elif typ == "file":
                    if size >= 0:
                        have_size = True
                    out[rel] = RemoteEntry(rel, max(size, 0), mtime, False)
                elif not typ and size >= 0:
                    have_size = True
                    out[rel] = RemoteEntry(rel, size, mtime, False)
                # symlinks / devices are ignored on purpose
            stack.extend(reversed(children))
        return have_size

    def _list_lines(self, path: str, sink: List[str]) -> None:
        try:
            self.ftp.retrlines(f"LIST {self._qp(path)}", sink.append)
            self._remember(bool(self._quote_paths))
        except ftplib.error_perm as exc:
            if sink or not self._retry_quoted(exc, path):
                raise
            self._quote_paths = True
            self.log(tr("该服务器要求路径加引号，已自动切换"))
            self.ftp.retrlines(f"LIST {quote(path)}", sink.append)

    def _list_walk(self, base: str, out: Dict[str, RemoteEntry], max_depth: int) -> None:
        stack = [(base, "", 0)]
        while stack:
            path, prefix, depth = stack.pop()
            lines: List[str] = []
            try:
                self._list_lines(path, lines)
            except ftplib.error_perm as exc:
                if str(exc)[:3] in MISSING:
                    continue
                raise
            for line in lines:
                info = _parse_list_line(line)
                if not info:
                    continue
                is_dir, size, mtime, name = info
                if name in (".", ".."):
                    continue
                rel = prefix + name
                if is_dir:
                    out[rel] = RemoteEntry(rel, 0, 0.0, True)
                    if depth < max_depth:
                        stack.append((join_remote(path, name), rel + "/", depth + 1))
                else:
                    out[rel] = RemoteEntry(rel, size, mtime, False)

    def fill_missing_mtimes(self, base: str, entries: Dict[str, RemoteEntry],
                            limit: int = 2000) -> int:
        """Resolve unknown timestamps via MDTM (only used for LIST-only servers)."""
        files = [e for e in entries.values() if not e.is_dir and not e.mtime]
        if not files or len(files) > limit:
            return 0
        done = 0
        for e in files:
            try:
                resp = self.cmd("MDTM", join_remote(base, e.rel))
                parts = resp.split()
                if len(parts) >= 2:
                    stamp = parse_ftp_time(parts[1])
                    if stamp:
                        e.mtime = stamp
                        done += 1
            except ftplib.error_perm:
                return done      # MDTM not supported here - stop asking
            except ftplib.all_errors:
                return done
        return done

    # -- working directory -------------------------------------------------
    def _enter(self, directory: str) -> bool:
        """CWD into *directory* (cached).  Returns True on success.

        Some servers (TP-LINK among them) accept ``STOR``/``DELE``/``RMD`` only
        for names inside the *current* working directory and answer ``550
        Permission denied`` for anything else - even for an absolute path.  So
        every file command first moves the session to the parent folder.
        """
        directory = norm_remote(directory)
        if self._cwd == directory:
            return True
        try:
            self.cmd("CWD", directory)
            self._cwd = directory
            return True
        except ftplib.all_errors:
            self._cwd = None
            return False

    def _prep(self, remote_path: str) -> str:
        """Move to the file's parent folder and return the bare file name.

        Falls back to the absolute path when the parent cannot be entered, so a
        normal server keeps working exactly as before.
        """
        path = norm_remote(remote_path)
        parent, name = posixpath.split(path)
        parent = parent or "/"
        if not name:
            return path
        if self._enter(parent):
            if self._needs_cwd is False:
                self._needs_cwd = True     # remember that CWD-first works
            return name
        return path

    # -- transfer ---------------------------------------------------------
    def upload(self, local_path: str, remote_path: str,
               progress: Optional[Callable[[int], None]] = None) -> None:
        remote_path = norm_remote(remote_path)

        def _cb(block) -> None:
            if progress is None:
                return
            # ftplib hands the raw block to the callback (an int on some versions)
            progress(len(block) if isinstance(block, (bytes, bytearray)) else int(block))

        target = self._prep(remote_path)
        attempts = (self._quote_paths,) if self._quote_paths is not None else (False, True)
        last: Optional[Exception] = None
        for use_quotes in attempts:
            arg = quote(target) if use_quotes else target
            try:
                with open(local_path, "rb") as fh:
                    self.ftp.storbinary(f"STOR {arg}", fh, blocksize=CHUNK,
                                        callback=_cb if progress else None)
                self._remember(use_quotes)
                return
            except ftplib.error_perm as exc:
                last = exc
                if not use_quotes and self._retry_quoted(exc, target):
                    continue
                raise
        raise last if last else ftplib.error_perm("550 upload failed")

    def set_mtime(self, remote_path: str, epoch: float) -> bool:
        """MFMT the remote file so timestamps match the local source."""
        if self._mfmt_ok is False or epoch <= 0:
            return False
        stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime(epoch))
        path = self._prep(remote_path)
        try:
            arg = quote(path) if self._quote_paths else path
            self.ftp.sendcmd(f"MFMT {stamp} {arg}")
            self._mfmt_ok = True
            return True
        except ftplib.error_perm as exc:
            if str(exc)[:3] in UNSUPPORTED and self._mfmt_ok is None:
                self.log(tr("服务器不支持 MFMT，远端时间戳将保持为上传时间"))
                self._mfmt_ok = False
            return False
        except ftplib.all_errors:
            return False

    def delete_file(self, remote_path: str) -> None:
        self.cmd("DELE", self._prep(remote_path))

    def delete_dir(self, remote_path: str) -> None:
        self.cmd("RMD", self._prep(remote_path))

    def size(self, remote_path: str) -> int:
        try:
            return int(self.cmd("SIZE", self._prep(remote_path)).split()[1])
        except Exception:
            return -1

    # -- diagnostics ------------------------------------------------------
    def info(self) -> str:
        if not self.ftp:
            return tr("未连接")
        try:
            return f"{self.ftp.getwelcome()}"
        except Exception:
            return tr("已连接")


_UNIX_RE = re.compile(
    r"^([\-dlbcps])([rwxstST\-]{9})\S*\s+\d+\s+(\S+)\s+(\S+)\s+(\d+)\s+"
    r"([A-Za-z]{3})\s+(\d{1,2})\s+(\d{1,2}:\d{2}|\d{4})\s+(.+)$"
)
_DOS_RE = re.compile(
    r"^(\d{2})-(\d{2})-(\d{2,4})\s+(\d{2}):(\d{2})\s*([AaPp][Mm])?\s+"
    r"(<DIR>|[\d,]+)\s+(.+)$"
)
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _parse_list_line(line: str):
    """Return (is_dir, size, mtime, name) or None.

    ``mtime`` stays 0.0 because a LIST timestamp carries no timezone and is
    normally rendered in the server's local time - MDTM is asked for the real value.
    """
    line = line.rstrip("\r\n")
    if not line:
        return None
    m = _UNIX_RE.match(line)
    if m:
        return (m.group(1) == "d", int(m.group(5)), 0.0, m.group(9).strip())
    m = _DOS_RE.match(line)
    if m:
        raw = m.group(7)
        size = 0 if raw.upper() == "<DIR>" else int(raw.replace(",", ""))
        return (raw.upper() == "<DIR>", size, 0.0, m.group(8).strip())
    parts = line.split(None, 1)
    if len(parts) == 1 and "/" not in line:
        return (False, 0, 0.0, line.strip())
    return None


def test_connection(cfg: ServerConfig, logger=None) -> str:
    """Connect, login and return a short description (raises FtpError)."""
    with FtpSession(cfg, logger) as s:
        home = s._home
        try:
            count = len(s.list_tree(home, max_depth=1))
            mode = s.mode
        except Exception:
            count = -1
            mode = tr("未知")
        extra = trf("，首页 {p0} 个条目", p0=count) if count >= 0 else ""
        return trf("连接成功（列举方式 {p0}）· 当前目录 {p1}", p0=mode, p1=home) + extra
