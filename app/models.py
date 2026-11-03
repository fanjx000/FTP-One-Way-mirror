"""Shared data structures used by the sync engine (no Qt / no GUI imports)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---- action codes (kept as plain strings so they can cross thread/UI boundary) ----
A_UPLOAD_NEW = "upload_new"      # new file on FTP
A_UPLOAD_MOD = "upload_update"   # file exists but differs -> overwrite
A_DELETE = "delete"              # exists on FTP but not on Windows
A_MKDIR = "mkdir"                # remote directory to create
A_SKIP = "skip"                  # already in sync
A_ERROR = "error"

ACTION_LABELS = {
    A_UPLOAD_NEW: "新增上传",
    A_UPLOAD_MOD: "更新上传",
    A_DELETE: "删除",
    A_MKDIR: "创建目录",
    A_SKIP: "已同步",
    A_ERROR: "错误",
}


def action_label(code: str) -> str:
    """Translated label for an action code."""
    from .i18n import tr
    return tr(ACTION_LABELS.get(code, code))

# ---- runtime status of a row ----
S_PENDING = "pending"
S_RUNNING = "running"
S_DONE = "done"
S_SKIPPED = "skipped"
S_FAILED = "failed"

STATUS_LABELS = {
    S_PENDING: "待处理",
    S_RUNNING: "进行中",
    S_DONE: "完成",
    S_SKIPPED: "已跳过",
    S_FAILED: "失败",
}


def status_label(code: str) -> str:
    """Translated label for a status code."""
    from .i18n import tr
    return tr(STATUS_LABELS.get(code, code))


@dataclass
class Job:
    """One configured sync source (a folder or a single file)."""
    id: str
    source: str            # absolute Windows path
    kind: str              # "dir" | "file"
    remote: str            # absolute remote dir, POSIX style, e.g. /backup/Docs
    enabled: bool = True
    name: str = ""

    @property
    def label(self) -> str:
        return self.name or self.source

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source, "kind": self.kind,
            "remote": self.remote, "enabled": self.enabled, "name": self.name,
        }

    @staticmethod
    def from_dict(d: dict) -> "Job":
        return Job(
            id=str(d.get("id") or ""),
            source=str(d.get("source") or ""),
            kind=str(d.get("kind") or "dir"),
            remote=str(d.get("remote") or "/"),
            enabled=bool(d.get("enabled", True)),
            name=str(d.get("name") or ""),
        )


@dataclass
class LocalEntry:
    rel: str        # relative path, POSIX separators ("" never used for files)
    size: int
    mtime: float    # epoch seconds (UTC based)
    is_dir: bool


@dataclass
class RemoteEntry:
    rel: str
    size: int
    mtime: float    # 0.0 when the server did not report it
    is_dir: bool


@dataclass
class Row:
    """A single line shown in the file table."""
    job_id: str
    job_label: str
    rel: str
    remote_path: str
    is_dir: bool = False
    action: str = A_SKIP
    size: int = 0
    mtime: float = 0.0
    remote_size: int = 0
    remote_mtime: float = 0.0
    synced_at: float = 0.0
    status: str = S_PENDING
    message: str = ""

    @property
    def key(self) -> str:
        return f"{self.job_id}:{self.rel}"


@dataclass
class Summary:
    jobs: int = 0
    scanned_files: int = 0
    dirs_created: int = 0
    uploaded_new: int = 0
    uploaded_changed: int = 0
    deleted_files: int = 0
    deleted_dirs: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_sent: int = 0
    elapsed: float = 0.0
    aborted: bool = False
    messages: list = field(default_factory=list)

    @property
    def changed(self) -> int:
        return self.uploaded_new + self.uploaded_changed + self.deleted_files + self.deleted_dirs

    def short(self) -> str:
        from .i18n import trf, tr
        parts = []
        if self.uploaded_new:
            parts.append(trf("新增 {n}", n=self.uploaded_new))
        if self.uploaded_changed:
            parts.append(trf("更新 {n}", n=self.uploaded_changed))
        if self.deleted_files:
            parts.append(trf("删除文件 {n}", n=self.deleted_files))
        if self.deleted_dirs:
            parts.append(trf("删除目录 {n}", n=self.deleted_dirs))
        if self.dirs_created:
            parts.append(trf("新建目录 {n}", n=self.dirs_created))
        if self.skipped:
            parts.append(trf("跳过 {n}", n=self.skipped))
        if self.failed:
            parts.append(trf("失败 {n}", n=self.failed))
        if not parts:
            parts.append(tr("无变化"))
        return " · ".join(parts)
