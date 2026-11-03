"""Configuration persistence (JSON) + sync state database location."""
from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from . import dpapi
from .models import Job

APP_NAME = "FtpSync"
CONFIG_VERSION = 1

DEFAULT_EXCLUDES = [
    "Thumbs.db", "desktop.ini", ".DS_Store", "~$*", "*.tmp", "*.crdownload",
]


def app_root() -> Path:
    """Directory that holds the executable (frozen) or the project (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Portable mode when a `portable.txt` sits next to the exe, else %APPDATA%."""
    if (app_root() / "portable.txt").exists():
        d = app_root() / "data"
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def state_db_path() -> Path:
    return data_dir() / "state.db"


@dataclass
class ServerConfig:
    protocol: str = "ftp"          # "ftp" | "ftps" (explicit TLS) | "ftpsi" (implicit TLS)
    host: str = ""
    port: int = 21
    username: str = "anonymous"
    password_token: str = ""       # DPAPI protected
    passive: bool = True
    encoding: str = "utf-8"        # utf-8 | gbk | latin-1
    timeout: int = 30
    concurrency: int = 3           # parallel upload connections
    verify_tls: bool = False       # self-signed certs are common on NAS boxes
    remote_root: str = "/"         # last browsed remote folder

    # -- password helpers -------------------------------------------------
    def set_password(self, plain: str) -> None:
        self.password_token = dpapi.protect(plain) if plain else ""

    @property
    def password(self) -> str:
        return dpapi.unprotect(self.password_token)

    @property
    def default_port(self) -> int:
        return 990 if self.protocol == "ftpsi" else (21 if self.protocol == "ftp" else 21)

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol, "host": self.host, "port": self.port,
            "username": self.username, "password_token": self.password_token,
            "passive": self.passive, "encoding": self.encoding,
            "timeout": self.timeout, "concurrency": self.concurrency,
            "verify_tls": self.verify_tls, "remote_root": self.remote_root,
        }

    @staticmethod
    def from_dict(d: dict) -> "ServerConfig":
        cfg = ServerConfig()
        for f in ("protocol", "host", "username", "password_token", "encoding"):
            if f in d and d[f] is not None:
                setattr(cfg, f, str(d[f]))
        for f in ("port", "timeout", "concurrency"):
            try:
                if d.get(f):
                    setattr(cfg, f, int(d[f]))
            except (TypeError, ValueError):
                pass
        for f in ("passive", "verify_tls"):
            if f in d:
                setattr(cfg, f, bool(d[f]))
        if d.get("remote_root"):
            cfg.remote_root = str(d["remote_root"])
        return cfg


@dataclass
class Options:
    delete_remote_extras: bool = True     # one-way mirror: delete on FTP what is gone locally
    preserve_mtime: bool = True           # use MFMT so the next run needs no re-upload
    excludes: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    mass_delete_guard: bool = True        # ask before deleting a large share of the remote tree
    mass_delete_percent: int = 20
    mass_delete_min: int = 10
    follow_reparse: bool = False          # follow junctions / symlinks (off = safer)
    skip_hidden: bool = False
    skip_cloud_only: bool = False         # do not hydrate OneDrive placeholders
    retries: int = 2

    def to_dict(self) -> dict:
        return {
            "delete_remote_extras": self.delete_remote_extras,
            "preserve_mtime": self.preserve_mtime,
            "excludes": list(self.excludes),
            "mass_delete_guard": self.mass_delete_guard,
            "mass_delete_percent": self.mass_delete_percent,
            "mass_delete_min": self.mass_delete_min,
            "follow_reparse": self.follow_reparse,
            "skip_hidden": self.skip_hidden,
            "skip_cloud_only": self.skip_cloud_only,
            "retries": self.retries,
        }

    @staticmethod
    def from_dict(d: dict) -> "Options":
        o = Options()
        if not d:
            return o
        for f in ("delete_remote_extras", "preserve_mtime", "mass_delete_guard",
                  "follow_reparse", "skip_hidden", "skip_cloud_only"):
            if f in d:
                setattr(o, f, bool(d[f]))
        for f in ("mass_delete_percent", "mass_delete_min", "retries"):
            try:
                if d.get(f) is not None:
                    setattr(o, f, int(d[f]))
            except (TypeError, ValueError):
                pass
        if isinstance(d.get("excludes"), list):
            o.excludes = [str(x) for x in d["excludes"]]
        return o


@dataclass
class Config:
    version: int = CONFIG_VERSION
    server: ServerConfig = field(default_factory=ServerConfig)
    options: Options = field(default_factory=Options)
    jobs: List[Job] = field(default_factory=list)
    window: str = "1280x820"
    language: str = "zh"                  # "zh" | "en"

    # -- persistence ------------------------------------------------------
    @staticmethod
    def load() -> "Config":
        p = config_path()
        cfg = Config()
        if not p.exists():
            return cfg
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cfg
        cfg.server = ServerConfig.from_dict(raw.get("server") or {})
        cfg.options = Options.from_dict(raw.get("options") or {})
        cfg.jobs = [Job.from_dict(j) for j in (raw.get("jobs") or []) if isinstance(j, dict)]
        for j in cfg.jobs:
            if not j.id:
                j.id = uuid.uuid4().hex[:12]
        cfg.window = str(raw.get("window") or cfg.window)
        cfg.language = str(raw.get("language") or cfg.language)
        return cfg

    def save(self) -> None:
        payload = {
            "version": CONFIG_VERSION,
            "server": self.server.to_dict(),
            "options": self.options.to_dict(),
            "jobs": [j.to_dict() for j in self.jobs],
            "window": self.window,
            "language": self.language,
        }
        p = config_path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
