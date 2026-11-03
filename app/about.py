"""Single source of truth for the content of Help -> About.

Keeping the text here (instead of inline in the window) means the GUI and the
``--about`` command line switch can never drift apart, and the owner details
only have to be edited in one place.
"""
from __future__ import annotations

from . import __author__, __dev_date__, __email__, __version__

# Feature bullets, translated through the caller's ``tr``.
FEATURE_KEYS = (
    "本地 Windows 文件夹 → FTP 服务器的单向镜像工具。",
    "· 只传输新增与修改的文件，未变化的文件零传输",
    "· 本地删除的内容会同步删除到 FTP",
    "· 保留完整目录结构，自动创建远端目录",
)

# "label" keys carry their own punctuation so English reads naturally.
OWNER_KEYS = ("开发者：", "开发日期：", "联系邮箱：")


def details() -> dict:
    """Owner / build details, untranslated values."""
    return {
        "author": __author__,
        "date": __dev_date__,
        "email": __email__,
        "version": __version__,
    }


def _owner_items(tr) -> list:
    """[(label, value)] for owner / date / e-mail, labels already translated."""
    labels = [tr(k) for k in OWNER_KEYS]
    return [
        (labels[0], __author__),
        (labels[1], __dev_date__),
        (labels[2], __email__),
    ]


def html(tr, trailing: str = "") -> str:
    """Rich text for the About box.  *trailing* is appended as a last paragraph."""
    body = "<br>".join(tr(k) for k in FEATURE_KEYS)
    *others, (mail_label, mail) = _owner_items(tr)
    owner = [f"{label}{value}" for label, value in others]
    owner.append(f'{mail_label}<a href="mailto:{mail}">{mail}</a>')   # clickable
    text = (f"<b>{tr('FTP 单向同步')}</b>  v{__version__}<br><br>"
            f"{body}<br><br>" + "<br>".join(owner))
    if trailing:
        text += f"<br><br>{trailing}"
    return text


def plain(tr, trailing: str = "") -> str:
    """Plain text version, used by ``FtpSync.exe --about``."""
    lines = [f"{tr('FTP 单向同步')}  v{__version__}", ""]
    lines += [tr(k) for k in FEATURE_KEYS]
    lines.append("")
    lines += [f"{label}{value}" for label, value in _owner_items(tr)]
    if trailing:
        lines += ["", trailing]
    return "\n".join(lines)
