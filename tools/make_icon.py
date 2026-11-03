"""Renders the application icon to docs/app.ico (multi-size, PNG compressed)."""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QIODevice                    # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from app.ui.icon import _draw                                    # noqa: E402

SIZES = [256, 128, 64, 48, 32, 16]


def png_bytes(size: int) -> bytes:
    pixmap = _draw(size)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = pixmap.save(buf, "PNG")
    buf.close()
    if not ok:
        raise RuntimeError(f"failed to encode {size}px PNG")
    return bytes(buf.data())


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841  (QPixmap needs a running app)
    images = [(s, png_bytes(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    offset = 6 + 16 * len(images)
    payload = b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data
    out = ROOT / "docs" / "app.ico"
    atomic_write(out, header + entries + payload)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    atomic_write(ROOT / "docs" / "icon.png", png_bytes(256))
    return 0


if __name__ == "__main__":
    sys.exit(main())
