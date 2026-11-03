# Changelog

All notable changes to **FTP One-Way mirror** (app name: *FTP One-Way Sync* / *FTP 单向同步*).
Dates are the day the version was finished.

## [1.8.2] — 2026-11-02

### Fixed
- **Help → About did nothing.** The dialog code concatenated `data_dir()` (a `pathlib.Path`)
  to a string, raising `TypeError`; the slot guard swallowed it into the crash log, so the UI
  stayed silent. Now formatted with an f-string.
- **Failures in UI slots are no longer silent.** A guarded slot that raises now shows
  *刚才的操作出错了，程序已继续运行* with the traceback (rate-limited to once per slot per
  20 s) instead of only writing a log line.

### Added
- `FtpSync.exe --about [file]` prints the version / owner / contact block.
- `FtpSync.exe --selftest out.png --about` opens the About dialog and saves it, so packaged
  builds can be verified end to end.
- `tools/test_about.py` — clicks the real menu action and asserts the dialog appears.

## [1.8.1] — 2026-11-02

### Changed
- **Single-file build.** `FtpSync-onefile.spec` produces one self-contained `FtpSync.exe`
  (27.7 MB); no `_internal` folder, nothing to install. The folder build is kept as
  `FtpSync-folder.spec`. `build.bat` now emits `dist\FtpSync.exe`.
- `README.md` rewritten in English; the Chinese guide lives in `使用说明.md`.

### Added
- About box now shows **Owner**, **Development date** and a clickable **contact e-mail**
  (single source: `app/about.py`, values in `app/__init__.py`).
- exe file properties carry version 1.8.1.0, company and copyright.

## [1.8.0] — 2026-11-02

### Fixed
- **Preview could leave the window unresponsive.** Event draining had no time budget, so a
  burst of ~1200 row updates occupied the main thread for seconds; and completion depended on
  the event queue being empty, which never happened if one more event arrived after the worker
  stopped. Draining now uses a 30 ms budget per 70 ms tick, and completion follows the worker
  thread.
- Added a responsiveness watchdog: a 5 s stall is logged and the buttons are unlocked on
  recovery.

## [1.7.0] — 2026-11-02

### Fixed
- Four ways the process could vanish without a trace:
  - a `QThread` destroyed while running (closing the settings dialog during *Test connection*)
    made Qt abort the process — replaced with a plain thread plus a queued signal;
  - the window rebuilt by a language switch had no owner and died with the old window, closing
    the application — now kept alive by a module-level reference, and no rebuild during a sync;
  - the table model read rows without bounds checks, so a paint-time `IndexError` killed the app;
  - no exception hook existed at all in the windowed build.

### Added
- `app/safety.py`: exception hooks (main thread, worker threads, Qt messages, `faulthandler`),
  a rotating `crash.log`, guarded slots, and **Help → View crash log**.
- `tools/test_crash_safety.py`.

## [1.6.0] — 2026-11-02

### Added
- Version number in the window title, in *About*, in the first log line and in the diagnostics
  header — so a pasted log identifies its build.
- Only one executable is shipped; stale version folders are removed.

## [1.5.0] — 2026-11-02

### Fixed
- **TP-LINK routers (and some NAS FTP services) answered 550 Permission denied for every
  upload.** Such servers only accept `STOR`/`DELE`/`RMD` for names inside the *current*
  directory, even when given an absolute path. Every file command now switches into the file's
  parent folder first and then uses the bare name.
- `tools/test_mkdir_modes.py` gained a `CwdOnlyWrites` server to lock this behaviour in.

## [1.4.0] — 2026-11-02

### Fixed
- **Diagnostics crashed and printed a single `[error]` line.** The timestamp probe uploaded a
  test file without protection; its 550 aborted the whole report. Every probe and every section
  is now individually protected and a report is always returned.
- Diagnostics now probe **each job's target folder** (exists / sub-folder creatable / writable),
  because a router's FTP root is often read-only while `/volume(...)` is writable.

### Added
- `FtpSync.exe --diag report.txt` for headless diagnostics.
- `tools/test_diagnose.py` — read-only account, healthy server, dropped connection,
  unreachable host, read-only root, unwritable target.

## [1.3.0] — 2026-11-02

### Fixed
- Directory creation on servers that reject absolute `MKD` paths, that forbid `CWD`, or that
  answer 550 for folders that already exist. Existence is now decided from the parent listing.
- Three creation dialects are tried in turn (`MKD abs`, `CWD + MKD name`, `MKD "quoted"`) and
  the working one is remembered.

### Added
- **Server diagnostics** button (server bar and Tools menu) with ✔ / ! / ✘ markers and a
  conclusion, e.g. “folder creation must use rel”, “sync target is usable”.

## [1.2.0] — 2026-11-01

### Added
- Chinese / English UI with an instant switch (Settings → General → Language), persisted in the
  config file. Covers the main window, all dialogs, file-detail actions and statuses, the run log
  and FTP error messages.
- `tools/test_i18n.py`.

### Fixed
- `505 Permission denied` caused by concurrency limits: failures are retried one at a time on a
  single connection, and the run's concurrency drops to 1 when that succeeds.
- `505` caused by a rejected folder name: the offending folder is named in the log and its files
  are failed once instead of being retried one by one.
- Failure details are grouped by message with error code, sample files and a likely cause.

## [1.1.0] — 2026-11-01

### Fixed
- `501 Option not understood` on `OPTS MLST`: capability probing is separate from listing, so a
  server without `OPTS` keeps using `MLSD` with default attributes instead of failing.
- OneDrive placeholders are recognised (`RECALL_ON_DATA_ACCESS`), so files are no longer
  mistaken for junctions and skipped.
- Same-size content edits are re-uploaded when the server has no `MFMT`/`MDTM`.
- Quoted paths are only used after the server actually rejects a bare path.

### Added
- Option *不下载 OneDrive 未缓存的云端文件* for placeholder-heavy folders.

## [1.0.0] — 2026-11-01

### Added
- First release: one-way mirror from Windows folders/files to FTP/FTPS, incremental transfers
  backed by a SQLite state cache, mirrored deletions, timestamp preservation via `MFMT`,
  bulk-delete guard, exclusions, DPAPI-encrypted password, portable mode.
