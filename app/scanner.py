"""Local (Windows) side scanning: enumerate a job's source into relative entries."""
from __future__ import annotations

import fnmatch
import os
import stat
from typing import Dict, List, Tuple

from .config import Options
from .models import Job, LocalEntry

# Windows file attribute bits we care about.  Python's `stat` module does not
# expose all of them, so they are spelled out here.
ATTR_DIRECTORY = 0x10
ATTR_ARCHIVE = 0x20
ATTR_REPARSE_POINT = 0x400
ATTR_OFFLINE = 0x1000
ATTR_RECALL_ON_OPEN = 0x40000
ATTR_RECALL_ON_DATA_ACCESS = 0x400000

# Bits Windows sets on a OneDrive / "Files On-Demand" placeholder.  Such an entry
# is a normal file to us: opening it hydrates the content, which is exactly what a
# backup tool must do - it must never be skipped as if it were a symlink.
CLOUD_ATTRS = ATTR_OFFLINE | ATTR_RECALL_ON_OPEN | ATTR_RECALL_ON_DATA_ACCESS


class ScanError(Exception):
    pass


def is_excluded(rel: str, name: str, patterns: List[str]) -> bool:
    if not patterns:
        return False
    low_name = name.lower()
    low_rel = rel.lower()
    for pat in patterns:
        p = pat.strip().lower()
        if not p:
            continue
        if fnmatch.fnmatch(low_name, p) or fnmatch.fnmatch(low_rel, p):
            return True
    return False


def _attrs(entry: os.DirEntry) -> int:
    try:
        return int(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) or 0)
    except (OSError, AttributeError):
        return 0


def _is_reparse(entry: os.DirEntry) -> bool:
    """True for symlinks / junctions / other reparse points."""
    try:
        if entry.is_symlink():
            return True
        if hasattr(entry, "is_junction") and entry.is_junction():
            return True
    except OSError:
        pass
    return bool(_attrs(entry) & ATTR_REPARSE_POINT)


def _is_cloud_file(attrs: int) -> bool:
    """True for a OneDrive-style placeholder (a real file, just not downloaded yet)."""
    if attrs & ATTR_DIRECTORY:
        return False
    return bool(attrs & CLOUD_ATTRS)


def scan_job(job: Job, options: Options) -> Tuple[Dict[str, LocalEntry], List[str]]:
    """Return ({rel: LocalEntry}, warnings).  Raises ScanError when the source is unusable."""
    warnings: List[str] = []
    entries: Dict[str, LocalEntry] = {}
    cloud_files = 0
    cloud_skipped = 0
    src = job.source

    if not src:
        raise ScanError("未设置源路径")
    if not os.path.exists(src):
        raise ScanError(f"源路径不存在：{src}")

    if os.path.isfile(src):
        name = os.path.basename(src)
        if is_excluded(name, name, options.excludes):
            return {}, [f"文件被排除规则跳过：{name}"]
        st = os.stat(src)
        entries[name] = LocalEntry(name, st.st_size, st.st_mtime, False)
        return entries, warnings

    if not os.path.isdir(src):
        raise ScanError(f"源路径既不是文件也不是文件夹：{src}")

    stack: List[Tuple[str, str]] = [(src, "")]
    while stack:
        path, prefix = stack.pop()
        try:
            with os.scandir(path) as it:
                children = list(it)
        except PermissionError:
            warnings.append(f"无权限访问，已跳过：{path}")
            continue
        except OSError as exc:
            warnings.append(f"读取失败，已跳过：{path}（{exc}）")
            continue
        for entry in children:
            name = entry.name
            rel = prefix + name
            if is_excluded(rel, name, options.excludes):
                continue
            attrs = _attrs(entry)
            if options.skip_hidden and attrs & stat.FILE_ATTRIBUTE_HIDDEN:
                continue
            reparse = _is_reparse(entry)
            try:
                is_dir = entry.is_dir(follow_symlinks=options.follow_reparse)
                if is_dir:
                    if reparse and not options.follow_reparse:
                        # junctions / symlinks can loop or point outside the tree
                        continue
                    st = entry.stat(follow_symlinks=False)
                    entries[rel] = LocalEntry(rel, 0, st.st_mtime, True)
                    stack.append((entry.path, rel + "/"))
                    continue
                if not entry.is_file(follow_symlinks=options.follow_reparse):
                    continue
                if reparse and not options.follow_reparse and not _is_cloud_file(attrs):
                    continue          # a plain symlink to a file
                if _is_cloud_file(attrs):
                    if options.skip_cloud_only:
                        cloud_skipped += 1
                        continue
                    cloud_files += 1
                st = entry.stat(follow_symlinks=False)
                entries[rel] = LocalEntry(rel, st.st_size, st.st_mtime, False)
            except OSError as exc:
                warnings.append(f"无法读取：{entry.path}（{exc}）")

    if cloud_files:
        warnings.append(
            f"{cloud_files} 个 OneDrive/云端占位文件尚未下载到本地，上传时会自动下载（首次会比较慢）")
    if cloud_skipped:
        warnings.append(
            f"已按设置跳过 {cloud_skipped} 个未下载的云端占位文件（它们不会上传）")
    return entries, warnings
