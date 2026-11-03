## FTP One-Way mirror v1.8.2

Single-file Windows build (x64). Download `FtpSync.exe` below and run it — nothing to install,
no `_internal` folder, no administrator rights, no registry writes.

**Start-up:** ~2–4 s from a local disk. Keep it on a local disk — a one-file build unpacks
~28 MB on every launch, so running it from a network share takes 30 s or more.

### Changes since v1.8.1

**Fixed**

* **Help → About did nothing.** The dialog code concatenated `data_dir()` (a `pathlib.Path`)
  to a string, raising `TypeError`; the slot guard swallowed it into the crash log, so the UI
  stayed silent. Now formatted with an f-string.
* **Failures inside UI slots are no longer silent.** A guarded slot that raises now shows
  *刚才的操作出错了，程序已继续运行* together with the traceback, rate-limited to once per
  slot per 20 s — instead of only writing a log line.

**Added**

* `FtpSync.exe --about [file]` prints version / owner / contact (writes to a file when no
  console is attached).
* `FtpSync.exe --selftest out.png --about` opens the About dialog and saves it, so packaged
  builds can be verified end to end.
* `tools/test_about.py` clicks the real menu action and asserts the dialog appears.

### What it does

One-way mirror from Windows folders/files to FTP or FTPS. Incremental transfers (SQLite state
cache — unchanged files cost nothing), mirrored deletions with a bulk-delete guard, timestamp
preservation via `MFMT`, zh/en UI, per-server diagnostics, crash guards.

Tolerant of cheap FTP servers: `OPTS MLST` → 501, no `MLSD`, no `MFMT`/`MDTM`,
absolute-path `MKD` refused, concurrency limits (505/421), and servers that only accept writes
inside the current directory (TP-LINK).

### Integrity

```
SHA-256 70b36002925eb527de429ea32a054fe31c1348d03fd72b2ae990f495641f4aca
```

Verify with `certutil -hashfile FtpSync.exe SHA256`.

Full history: [CHANGELOG.md](https://github.com/fanjx000/FTP-One-Way-mirror/blob/main/CHANGELOG.md).
Licence: MIT. Owner: Justin Fan J.X. — fanjunxin@gmail.com
