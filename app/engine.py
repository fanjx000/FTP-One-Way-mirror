"""Sync engine: diff local vs. remote, then mirror local -> FTP.

Guarantees / behaviour:
  * One-way.  Local is always the truth: new/changed files are uploaded, entries
    that disappeared locally are deleted remotely (opt-out via options).
  * Cheap re-runs.  A recursive MLSD listing plus a local state cache means an
    unchanged tree costs a single listing and zero transfers.
  * Safe deletes.  Deletion only ever happens *below* the configured remote
    folder, never on the folder itself, and a mass-delete guard stops an empty or
    disconnected source from wiping the server.
  * Parallel uploads on separate control connections (configurable).
"""
from __future__ import annotations

import ftplib
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple

from .config import Config, Options
from .i18n import tr, trf
from .ftpclient import FtpError, FtpSession, join_remote, norm_remote
from .models import (
    A_DELETE, A_MKDIR, A_SKIP, A_UPLOAD_MOD, A_UPLOAD_NEW,
    S_DONE, S_FAILED, S_PENDING, S_SKIPPED,
    Job, LocalEntry, RemoteEntry, Row, Summary,
)
from .scanner import ScanError, scan_job
from .state import StateDB, StateRow

MTIME_TOLERANCE = 2.0     # seconds; FTP timestamps have 1s resolution
SHOW_LIMIT = 60000        # cap on rows pushed to the UI for gigantic trees

# Reply codes worth aborting a job for: they are never about a single file.
ABORT_CODES = ("421", "425", "426", "530", "532", "505", "550")

# Plain-language hints for the replies that actually show up in the field.
ERROR_HINTS = {
    "421": "服务器连接数已满或服务超时，请把“同时上传的文件数”设为 1 后重试",
    "425": "数据连接无法建立，检查被动模式 / 防火墙",
    "426": "传输中断，网络或服务器限制带宽",
    "450": "目标文件被占用或暂时不可用",
    "451": "服务器内部错误",
    "452": "服务器磁盘空间不足",
    "500": "服务器不认识该命令（可能是极简 FTP 服务）",
    "501": "服务器不支持该命令的参数",
    "502": "服务器未实现该命令",
    "504": "服务器不支持该命令的参数",
    "505": "服务器拒绝该文件名或路径（常见原因：名称含特殊字符、路径过长、"
           "目录不可写、或连接数受限）",
    "530": "登录失败或会话已失效，请检查用户名 / 密码",
    "532": "需要存储权限",
    "550": "服务器拒绝访问：目录不存在、没有写权限，或文件名不被允许",
    "552": "超出服务器配额",
    "553": "文件名不被服务器接受（多为特殊字符或过长）",
}


def _code_of(message: str) -> str:
    """Extract the 3-digit FTP reply code from an error message."""
    head = str(message or "").strip()[:3]
    return head if head.isdigit() else ""


def _depth(rel: str) -> int:
    return rel.count("/")


class SyncEngine:
    def __init__(self, cfg: Config, state: StateDB, sink: Callable[[dict], None],
                 dry_run: bool = False, allow_mass_delete: bool = False,
                 cancel: Optional[threading.Event] = None):
        self.cfg = cfg
        self.opts: Options = cfg.options
        self.state = state
        self._sink = sink
        self.dry_run = dry_run
        self.allow_mass_delete = allow_mass_delete
        self.cancel = cancel or threading.Event()
        self._tls = threading.local()
        self._sess_lock = threading.Lock()
        self._sessions: set = set()
        self._bytes_lock = threading.Lock()
        self._bytes = 0
        self._last_emit = 0.0
        self._progress_done = 0
        self._progress_total = 0
        self.mfmt_ok = True

    # ------------------------------------------------------------------ events
    def _emit(self, kind: str, **payload) -> None:
        payload["type"] = kind
        try:
            self._sink(payload)
        except Exception:
            pass

    def log(self, text: str) -> None:
        self._emit("log", text=text)

    def _phase(self, text: str) -> None:
        self._emit("phase", text=text)
        self.log(text)

    def _progress(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_emit < 0.12:
            return
        self._last_emit = now
        with self._bytes_lock:
            sent = self._bytes
        self._emit("progress", done=self._progress_done,
                   total=max(self._progress_total, 1), bytes=sent)

    def _bump(self, nbytes: int) -> None:
        with self._bytes_lock:
            self._bytes += nbytes

    def _row(self, row: Row, status: str, message: str = "", synced_at: float = 0.0) -> None:
        row.status = status
        if message:
            row.message = message
        if synced_at:
            row.synced_at = synced_at
        self._emit("row", key=row.key, status=status, message=row.message,
                   synced_at=row.synced_at)

    # ------------------------------------------------------------------ public
    def run(self) -> Summary:
        t0 = time.time()
        summary = Summary()
        jobs = [j for j in self.cfg.jobs if j.enabled]
        summary.jobs = len(jobs)
        if not jobs:
            self.log(tr("没有启用的同步任务，请先添加源文件夹。"))
            summary.elapsed = time.time() - t0
            self._emit("summary", summary=summary)
            return summary

        from . import __version__
        self.log(trf("程序版本 v{ver}", ver=__version__))
        mode = tr("预览（不写入 FTP）") if self.dry_run else tr("实际同步")
        self.log(trf("开始{p0} · 共 {p1} 个任务", p0=mode, p1=len(jobs)))
        for job in jobs:
            if self.cancel.is_set():
                summary.aborted = True
                break
            try:
                self._run_job(job, summary)
            except (FtpError, ScanError) as exc:
                summary.failed += 1
                summary.messages.append(f"{job.label}: {exc}")
                self.log(trf("[失败] {p0}：{p1}", p0=job.label, p1=exc))
                self.state.mark_run(job.id, tr("失败") + f": {exc}")
            except Exception as exc:  # noqa: BLE001 - a broken job must not stop the run
                summary.failed += 1
                summary.messages.append(f"{job.label}: {exc}")
                self.log(trf("[错误] {p0}：{p1}", p0=job.label, p1=exc))
                self.log(traceback.format_exc(limit=4))
        if self.cancel.is_set():
            summary.aborted = True
            self.log(tr("已取消。"))
        if not self.dry_run:
            with self._bytes_lock:
                summary.bytes_sent = self._bytes
        summary.elapsed = time.time() - t0
        self._progress(force=True)
        tail = (trf(" · 传输 {mb} MB", mb=f"{summary.bytes_sent / 1048576:.1f}")
                if summary.bytes_sent else "")
        self.log(trf("结束 · {summary} · 用时 {secs}s", summary=summary.short(),
                     secs=f"{summary.elapsed:.1f}") + tail)
        self._emit("summary", summary=summary)
        return summary

    # ------------------------------------------------------------------ one job
    def _run_job(self, job: Job, summary: Summary) -> None:
        base = norm_remote(job.remote)
        self.log(trf("── 任务：{p0}  →  {p1}", p0=job.source, p1=base))

        # 1) local scan -----------------------------------------------------
        local, warnings = scan_job(job, self.opts)
        for w in warnings:
            self.log(trf("[警告] {p0}", p0=w))
        files = {r: e for r, e in local.items() if not e.is_dir}
        dirs = {r: e for r, e in local.items() if e.is_dir}
        summary.scanned_files += len(files)
        if not local:
            self.log(tr("源为空（0 个条目）"))

        # 2) remote listing -------------------------------------------------
        sess = FtpSession(self.cfg.server, self.log)
        sess.connect()
        try:
            self._phase(trf("读取远端目录 {p0} …", p0=base))
            base_exists = sess.dir_exists(base)
            if base_exists:
                remote = sess.list_tree(base)
                self.log(trf("[信息] 远端列举方式：{p0}", p0=sess.mode))
                if any(not e.is_dir and not e.mtime for e in remote.values()):
                    resolved = sess.fill_missing_mtimes(base, remote)
                    if resolved:
                        self.log(trf("[提示] 已通过 MDTM 补齐 {p0} 个远端时间戳", p0=resolved))
            else:
                remote = {}
                self.log(trf("[提示] 远端目录不存在，将自动创建：{p0}", p0=base))
            if base == "/":
                self.log(tr("目标为 FTP 根目录，删除会作用在服务器根目录下"))

            # 3) plan -------------------------------------------------------
            plan = self._plan(job, base, local, files, dirs, remote)
            self._emit_rows(job, plan)
            self._progress_total = (len(plan["mkdir"]) + len(plan["pre_delete"])
                                    + len(plan["upload"]) + len(plan["delete"]))
            summary.dirs_created += len(plan["mkdir"])
            summary.skipped += len(plan["skip"])
            upload_bytes = sum(files[r].size for r in plan["new"] + plan["update"])

            if self.dry_run:
                summary.uploaded_new += len(plan["new"])
                summary.uploaded_changed += len(plan["update"])
                summary.deleted_files += sum(1 for e in plan["delete"] if not e.is_dir)
                summary.deleted_dirs += sum(1 for e in plan["delete"] if e.is_dir)
                summary.bytes_sent += upload_bytes
                self.log(trf("[预览] 待上传 {up} 个文件（{mb} MB）、待删除 {d} 项、待建目录 {mk} 个",
                             up=len(plan["upload"]), mb=f"{upload_bytes / 1048576:.1f}",
                             d=len(plan["delete"]) + len(plan["pre_delete"]),
                             mk=len(plan["mkdir"])))
                self._progress(force=True)
                return

            # 4) execute ----------------------------------------------------
            dir_errors: Dict[str, str] = {}
            if plan["mkdir"] or not base_exists:
                self._phase(trf("创建远端目录（{p0} 个）…", p0=len(plan["mkdir"])))
                made, dir_errors = self._make_dirs(sess, job, base, plan["mkdir"])
                summary.dirs_created = made

            for ent in plan["pre_delete"]:
                self._delete_entry(sess, job, base, ent, summary)

            if plan["upload"]:
                self._phase(trf("上传 {p0} 个文件…", p0=len(plan["upload"])))
                self._upload_all(job, base, files, plan, summary, dir_errors)

            if plan["delete"]:
                self._phase(trf("删除远端多余项（{p0} 个）…", p0=len(plan["delete"])))
                for ent in plan["delete"]:
                    if self.cancel.is_set():
                        break
                    self._delete_entry(sess, job, base, ent, summary)

            # 5) persist state ----------------------------------------------
            records = []
            for rel in plan["skip"]:
                e = files[rel]
                rent = remote.get(rel)
                records.append((job.id, rel, e.size, e.mtime,
                                rent.size if rent else 0,
                                rent.mtime if rent else 0.0))
            self.state.record_many(records)
            gone = [e.rel for e in plan["delete"]] + [e.rel for e in plan["pre_delete"]]
            self.state.forget(job.id, gone)
            self.state.mark_run(job.id, summary.short())
            self.log(trf("任务完成：{p0} → {p1}", p0=job.label, p1=base))
        finally:
            sess.close()

    # ------------------------------------------------------------------ planning
    def _plan(self, job: Job, base: str, local: Dict[str, LocalEntry],
              files: Dict[str, LocalEntry], dirs: Dict[str, LocalEntry],
              remote: Dict[str, RemoteEntry]) -> dict:
        self._phase(tr("对比本地与远端 …"))
        state = self.state.load(job.id)
        plan = {"mkdir": [], "upload": [], "skip": [], "delete": [],
                "pre_delete": [], "new": [], "update": [], "rows": []}
        rows: List[Row] = []

        # file<->directory type clashes must be removed before anything else
        conflicts: Dict[str, RemoteEntry] = {}
        for rel, loc in local.items():
            rent = remote.get(rel)
            if rent is not None and rent.is_dir != loc.is_dir:
                conflicts[rel] = rent

        conflict_rels = set(conflicts)
        for rel in list(conflicts):
            prefix = rel + "/"
            for rrel, rent in remote.items():
                if rrel.startswith(prefix) and rrel not in local:
                    conflict_rels.add(rrel)
        pre = [remote[r] for r in conflict_rels if r in remote]
        pre.sort(key=lambda e: (e.is_dir, -_depth(e.rel)))
        plan["pre_delete"] = pre
        for ent in pre:
            rows.append(Row(job.id, job.label, ent.rel, join_remote(base, ent.rel), ent.is_dir,
                            A_DELETE, ent.size, ent.mtime))

        # directories to create
        for rel, loc in dirs.items():
            rent = remote.get(rel)
            if rent is None:
                plan["mkdir"].append(rel)
                rows.append(Row(job.id, job.label, rel, join_remote(base, rel), True,
                                A_MKDIR, 0, loc.mtime))

        # files: new / changed / unchanged
        for rel, loc in files.items():
            rent = remote.get(rel)
            if rent is not None and rent.is_dir:
                action = A_UPLOAD_MOD
            elif rent is None:
                action = A_UPLOAD_NEW
            elif self._changed(loc, rent, state.get(rel)):
                action = A_UPLOAD_MOD
            else:
                action = A_SKIP
            st = state.get(rel)
            rows.append(Row(
                job.id, job.label, rel, join_remote(base, rel), False, action,
                loc.size, loc.mtime,
                remote_size=rent.size if (rent and not rent.is_dir) else 0,
                remote_mtime=rent.mtime if rent else 0.0,
                synced_at=st.last_sync if st else 0.0,
                status=S_SKIPPED if action == A_SKIP else S_PENDING))
            if action == A_SKIP:
                plan["skip"].append(rel)
            else:
                plan["upload"].append((rel, rows[-1]))
                (plan["new"] if action == A_UPLOAD_NEW else plan["update"]).append(rel)

        # remote entries that no longer exist locally
        extras = [rent for rel, rent in remote.items()
                  if rel not in conflict_rels and rel not in local]
        if extras and not self.opts.delete_remote_extras:
            self.log(trf("[提示] 远端有 {p0} 项本地已不存在，但“删除远端多余项”未启用", p0=len(extras)))
            for ent in extras:
                rows.append(Row(job.id, job.label, ent.rel, join_remote(base, ent.rel),
                                ent.is_dir, A_SKIP, ent.size, ent.mtime, status=S_SKIPPED,
                                message=tr("远端多余项（已禁用删除）")))
        elif extras:
            total_remote = max(1, len(remote))
            guarded = (self.opts.mass_delete_guard
                       and len(extras) >= self.opts.mass_delete_min
                       and len(extras) * 100.0 / total_remote > self.opts.mass_delete_percent
                       and not self.allow_mass_delete)
            if guarded:
                self.log(trf("需删除 {n}/{total} 项，超过安全阈值 {pct}%，已跳过删除。"
                             "请先用“仅预览”确认，再勾选“允许大批量删除”后重试。",
                             n=len(extras), total=total_remote,
                             pct=self.opts.mass_delete_percent))
            else:
                extras = sorted(extras, key=lambda e: (e.is_dir, -_depth(e.rel)))
                plan["delete"].extend(extras)
            for ent in extras:
                rows.append(Row(job.id, job.label, ent.rel, join_remote(base, ent.rel),
                                ent.is_dir, A_DELETE, ent.size, ent.mtime,
                                message=tr("受保护，未删除") if guarded else ""))
        rows.sort(key=lambda r: (r.rel.count("/"), r.rel))
        plan["rows"] = rows
        self.log(trf("对比结果：新增 {new} · 更新 {upd} · 删除 {d} · 跳过 {skip} · 建目录 {mk}",
                     new=len(plan["new"]), upd=len(plan["update"]),
                     d=len(plan["delete"]) + len(plan["pre_delete"]),
                     skip=len(plan["skip"]), mk=len(plan["mkdir"])))
        return plan

    def _changed(self, loc: LocalEntry, rent: RemoteEntry, st: Optional[StateRow]) -> bool:
        """Decide whether the local file must be (re)uploaded.

        Trust order: our own upload history first, then remote size, then remote
        timestamp.  Servers without MFMT/MDTM report no usable timestamp, so when
        the local file is known to have changed since the last successful upload
        we upload without asking the server anything - otherwise a same-size edit
        would be missed forever.
        """
        if st is not None:
            local_same = (st.local_size == loc.size
                          and abs(st.local_mtime - loc.mtime) < 1.0)
            if not local_same:
                return True                     # changed since our last upload
            remote_same = (st.remote_size == rent.size
                           and (st.remote_mtime <= 0 or rent.mtime <= 0
                                or abs(st.remote_mtime - rent.mtime) <= MTIME_TOLERANCE))
            return not remote_same              # only re-send if the remote drifted
        # no history: compare whatever the server gave us
        if rent.size != loc.size:
            return True
        if rent.mtime > 0 and abs(rent.mtime - loc.mtime) > MTIME_TOLERANCE:
            return True
        return False

    def _emit_rows(self, job: Job, plan: dict) -> None:
        rows: List[Row] = plan["rows"]
        shown = rows
        if len(rows) > SHOW_LIMIT:
            shown = [r for r in rows if r.action != A_SKIP][:SHOW_LIMIT]
            self.log(trf("[提示] 条目过多（{p0}），明细仅显示 {p1} 条变更", p0=len(rows), p1=len(shown)))
        self._emit("rows", rows=shown, job_id=job.id)

    # ------------------------------------------------------------------ actions
    def _make_dirs(self, sess: FtpSession, job: Job, base: str,
                   rels: List[str]) -> Tuple[int, Dict[str, str]]:
        """Create the remote directories and *verify* each one really exists.

        A silently failed MKD used to be reported as success, after which every
        file below it failed with the server's own "permission" reply - hundreds
        of pointless uploads.  Now the failure is caught once, reported once, and
        the affected files are skipped with a clear reason.
        """
        made = 0
        errors: Dict[str, str] = {}
        try:
            made += sess.ensure_dir_checked(base)
        except FtpError as exc:
            errors[""] = str(exc)
            self.log(trf("[错误] 无法创建目标目录 {p0}：{p1}", p0=base, p1=exc))
            return made, errors

        for rel in sorted(rels, key=_depth):
            if self.cancel.is_set():
                break
            try:
                made += sess.ensure_dir_checked(join_remote(base, rel))
            except FtpError as exc:
                msg = str(exc)
                errors[rel] = msg
                self.log(trf("[错误] 创建目录失败 {p0}：{p1}", p0=rel, p1=msg))
                self._emit("row", key=f"{job.id}:{rel}", status=S_FAILED, message=msg)
            except ftplib.all_errors as exc:
                errors[rel] = str(exc)
                self.log(trf("[错误] 创建目录失败 {p0}：{p1}", p0=rel, p1=exc))
            self._progress_done += 1
            self._progress()
        if errors:
            self.log(trf("{n} 个远端目录创建失败，其下的文件将无法上传"
                     "（常见原因：名称含服务器不支持的字符、路径过长、或该目录没有写权限）",
                     n=len(errors)))
        return made, errors

    @staticmethod
    def _blocked_reason(rel: str, dir_errors: Dict[str, str]) -> str:
        """Return the parent-directory error for *rel*, if any parent failed."""
        if not dir_errors:
            return ""
        parts = rel.split("/")[:-1]
        while parts:
            candidate = "/".join(parts)
            if candidate in dir_errors:
                return dir_errors[candidate]
            parts.pop()
        return dir_errors.get("", "")

    def _delete_entry(self, sess: FtpSession, job: Job, base: str,
                      ent: RemoteEntry, summary: Summary) -> None:
        path = join_remote(base, ent.rel)
        key = f"{job.id}:{ent.rel}"
        try:
            if ent.is_dir:
                sess.delete_dir(path)
                summary.deleted_dirs += 1
            else:
                sess.delete_file(path)
                summary.deleted_files += 1
            self._emit("row", key=key, status=S_DONE, message=tr("已删除"),
                       synced_at=time.time())
        except ftplib.error_perm as exc:
            if ent.is_dir and str(exc)[:3] == "550":
                self.log(trf("[警告] 目录未删除 {p0}（可能非空）", p0=ent.rel))
                self._emit("row", key=key, status=S_FAILED, message=tr("目录非空，未删除"))
            else:
                summary.failed += 1
                self.log(trf("[失败] 删除 {rel}：{err}", rel=ent.rel, err=exc))
                self._emit("row", key=key, status=S_FAILED, message=str(exc))
        except ftplib.all_errors as exc:
            summary.failed += 1
            self.log(trf("[失败] 删除 {rel}：{err}", rel=ent.rel, err=exc))
            self._emit("row", key=key, status=S_FAILED, message=str(exc))
        self._progress_done += 1
        self._progress()

    def _worker_session(self) -> FtpSession:
        sess = getattr(self._tls, "session", None)
        if sess is None:
            sess = FtpSession(self.cfg.server, self.log)
            sess.connect()
            self._tls.session = sess
            with self._sess_lock:
                self._sessions.add(sess)
        return sess

    def _reset_session(self) -> None:
        sess = getattr(self._tls, "session", None)
        if sess is not None:
            sess.close()
            with self._sess_lock:
                self._sessions.discard(sess)
        self._tls.session = None

    def _close_all_sessions(self) -> None:
        """Close every worker connection.

        Essential on servers with a small connection limit: leaving the parallel
        sessions open makes even the sequential retry fail with "permission denied".
        """
        with self._sess_lock:
            sessions = list(self._sessions)
            self._sessions.clear()
        for sess in sessions:
            try:
                sess.close()
            except Exception:
                pass
        self._tls.session = None

    def _upload_all(self, job: Job, base: str, files: Dict[str, LocalEntry],
                    plan: dict, summary: Summary,
                    dir_errors: Dict[str, str] | None = None) -> None:
        todo: List[Tuple[LocalEntry, Row]] = [(files[rel], row) for rel, row in plan["upload"]]
        dir_errors = dir_errors or {}

        # files whose parent folder could not be created: fail them once, clearly,
        # instead of letting the server reject every single one
        runnable: List[Tuple[LocalEntry, Row]] = []
        blocked = 0
        for loc, row in todo:
            reason = self._blocked_reason(loc.rel, dir_errors)
            if reason:
                blocked += 1
                self._row(row, S_FAILED, tr("父目录创建失败：") + f"{reason}")
            else:
                runnable.append((loc, row))
        if blocked:
            self.log(trf("[警告] {p0} 个文件因父目录创建失败而跳过，未逐个尝试上传", p0=blocked))

        workers = max(1, min(8, int(self.cfg.server.concurrency or 3)))
        self._run_batch(job, base, runnable, workers)

        # Some embedded servers cannot handle two transfers at once and answer the
        # second one with "permission denied".  Retry the failures one by one on a
        # single fresh connection before giving up.
        failed = [it for it in runnable if it[1].status == S_FAILED]
        if failed and workers > 1 and not self.cancel.is_set():
            self.log(trf("{n} 个文件上传失败，正在改用单连接依次重试"
                     "（部分服务器不支持并发上传，或限制了同时连接数）", n=len(failed)))
            self._close_all_sessions()     # free the parallel slots first
            self._run_batch(job, base, failed, 1, retry=True)
            if all(it[1].status == S_DONE for it in failed):
                self.log(tr("单连接重试全部成功：该服务器不支持并发上传，后续任务已自动改为单连接"
                         "（建议在设置里把“同时上传的文件数”设为 1）"))
                self.cfg.server.concurrency = 1   # in memory, for the remaining jobs
                summary.messages.append(tr("服务器不支持并发上传，已自动改为单连接"))

        counters = {"new": 0, "mod": 0, "fail": 0}
        records = []
        for loc, row in todo:
            if row.status == S_DONE:
                if row.action == A_UPLOAD_NEW:
                    counters["new"] += 1
                else:
                    counters["mod"] += 1
                records.append((job.id, loc.rel, loc.size, loc.mtime, loc.size,
                                loc.mtime if self.mfmt_ok else 0.0))
            elif row.status == S_FAILED:
                counters["fail"] += 1

        summary.uploaded_new += counters["new"]
        summary.uploaded_changed += counters["mod"]
        summary.failed += counters["fail"]
        self.state.record_many(records)
        self._report_failures(todo, summary)
        self._reset_session()

    def _run_batch(self, job: Job, base: str, items: List[Tuple[LocalEntry, Row]],
                   workers: int, retry: bool = False) -> None:
        """Upload *items* with *workers* parallel connections."""
        if not items:
            return
        lock = threading.Lock()
        state = {"consecutive": 0, "last_msg": "", "aborted": False}

        def work(item: Tuple[LocalEntry, Row]) -> None:
            loc, row = item
            if self.cancel.is_set() or state["aborted"]:
                if row.status != S_DONE:
                    self._row(row, S_PENDING, tr("已取消"))
                return
            if retry:
                row.status = S_PENDING
                row.message = ""
            try:
                ok, err, nbytes = self._upload_one(job, base, loc)
            except Exception as exc:  # noqa: BLE001
                ok, err, nbytes = False, str(exc), 0
            if ok:
                self._bump(nbytes)
                with lock:
                    state["consecutive"] = 0
                self._row(row, S_DONE, "", time.time())
            else:
                self._row(row, S_FAILED, err)
                with lock:
                    if err == state["last_msg"]:
                        state["consecutive"] += 1
                    else:
                        state["last_msg"] = err
                        state["consecutive"] = 1
                    if (workers == 1 and state["consecutive"] >= 5
                            and _code_of(err) in ABORT_CODES):
                        state["aborted"] = True
                        self.log(trf("连续 {n} 个文件都返回同一个错误，已停止本次上传以免浪费时间：{err}",
                                 n=state["consecutive"], err=err))
            self._progress_done += 1
            self._progress()

        if workers <= 1 or len(items) <= 1:
            for item in items:
                if self.cancel.is_set() or state["aborted"]:
                    break
                work(item)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(work, items))

    def _report_failures(self, todo: List[Tuple[LocalEntry, Row]], summary: Summary) -> None:
        """Group the failures by message so the cause is obvious in the log."""
        groups: Dict[str, List[str]] = {}
        for loc, row in todo:
            if row.status == S_FAILED:
                groups.setdefault(row.message or tr("未知错误"), []).append(loc.rel)
        if not groups:
            return
        self.log(tr("失败明细") + " " + "─" * 40)
        for msg, rels in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:6]:
            samples = "，".join(rels[:3])
            more = trf(" 等 {n} 个", n=len(rels)) if len(rels) > 3 else ""
            self.log(f"  · {msg}  ——  {samples}{more}")
            hint = ERROR_HINTS.get(_code_of(msg))
            if hint:
                self.log(trf("    可能原因：{p0}", p0=hint))
            summary.messages.append(trf("{msg}（{n} 个文件）", msg=msg, n=len(rels)))

    def _upload_one(self, job: Job, base: str, loc: LocalEntry) -> Tuple[bool, str, int]:
        rel = loc.rel
        remote_path = join_remote(base, rel)
        local_path = job.source if job.kind == "file" else os.path.join(
            job.source, *rel.split("/"))
        parent_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
        attempts = max(0, int(self.opts.retries or 0)) + 1
        last_err = ""
        for attempt in range(attempts):
            if self.cancel.is_set():
                return False, tr("已取消"), 0
            total = {"n": 0}
            try:
                sess = self._worker_session()
                if parent_rel:
                    sess.ensure_dir(join_remote(base, parent_rel))

                def cb(chunk: int) -> None:
                    total["n"] += chunk
                    self._bump(chunk)
                    self._progress()

                sess.upload(local_path, remote_path, progress=cb)
                if self.opts.preserve_mtime:
                    if not sess.set_mtime(remote_path, loc.mtime):
                        self.mfmt_ok = False
                return True, "", total["n"]
            except FileNotFoundError:
                return False, tr("本地文件已消失"), 0
            except (ftplib.Error, OSError, EOFError, FtpError) as exc:
                last_err = str(exc) or exc.__class__.__name__
                self._reset_session()
            if attempt + 1 < attempts:
                time.sleep(min(3.0, 0.5 * (attempt + 1)))
        return False, last_err or tr("上传失败"), 0

    def close(self) -> None:
        self._reset_session()
