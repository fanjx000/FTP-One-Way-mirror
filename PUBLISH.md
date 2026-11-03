# Publishing this project to GitHub

Target project: **FTP One-Way mirror** → `https://github.com/fanjx000/FTP-One-Way-mirror`

The working copy in this folder is already a git repository with one commit, so publishing is
two commands. Pick one of the two paths below.

## Path A — empty repository already created on GitHub (recommended)

1. On GitHub: **New repository** → name `FTP-One-Way-mirror` → **do not** add a README,
   .gitignore or licence (this folder already has them) → Create.
2. Double-click **`publish.bat`** in this folder, or run the same commands by hand:

```
git remote add origin https://github.com/fanjx000/FTP-One-Way-mirror.git
git push -u origin main
```

`git push` asks for credentials the first time. Use a **personal access token** as the password
(Settings → Developer settings → Personal access tokens → Fine-grained, scope *Contents:
Read and write* on this repository), or sign in through Git Credential Manager if it is installed.

## Path B — everything from the browser / API

If git credentials are not available, the text files can be uploaded on the GitHub web UI
(*Add file → Upload files*, drag the folder). Keep `dist/`, `build*/` and `.workbuddy-ai/` out —
they are build output and local session data.

## Publishing the exe as a release (keeps the repo small)

The binary is deliberately **not** committed. Attach it to a release instead:

1. `build.bat` → produces `dist\FtpSync.exe` (~27.7 MB).
2. GitHub → **Releases** → *Draft a new release*.
3. Tag `v1.8.2`, target `main`, title `FTP One-Way mirror v1.8.2`.
4. Attach `dist\FtpSync.exe`.
5. Paste the notes below (or copy the top section of `CHANGELOG.md`).

```
Single-file Windows build (x64). Download FtpSync.exe and run it — nothing to install,
no _internal folder, no administrator rights.

Start-up: ~2-4 s from a local disk. Keep it on a local disk, not on a network share
(a one-file build unpacks ~28 MB on every launch, which over SMB takes 30 s+).

Changes since v1.8.1:
- Help -> About now opens (fixed a TypeError that the slot guard silently swallowed)
- failures inside UI slots are reported with a dialog instead of only being logged
- --about and --selftest --about switches for support and packaging checks

SHA-256: run  certutil -hashfile FtpSync.exe SHA256  before uploading and paste it here.
```

## After the first push

| Step | How |
| --- | --- |
| Make it public | Settings → General → Danger zone → Change visibility |
| Publish the exe | Releases → Draft a new release → tag `v1.8.2` → attach `dist/FtpSync.exe` |
| Turn on CI | Actions tab → enable workflows. `.github/workflows/tests.yml` runs the whole test suite on Windows and attaches a built exe |
| Topics | Settings → Topics: `ftp`, `synchronization`, `pyside6`, `windows`, `backup`, `mirror` |

## Notes

* The commit already exists (`Initial import: FTP One-Way mirror v1.8.2`), authored as
  `Justin Fan J.X. <fanjunxin@gmail.com>`.
* Git needs one permission first when the folder lives on a network share:

```
git config --global --add safe.directory 'R:/RouterStorage/ftpSnyc'
```

* `publish.bat` never force-pushes and never rewrites history; it only sets `origin` and pushes
  `main`.

* commit messages are made with `python tools/commit.py "subject"` — on this SMB share
  `git commit -m` leaves the tail of the previous message in `.git/COMMIT_EDITMSG`, so
  subjects end up containing fragments of older commits.

## What is intentionally not committed

| Path | Why |
| --- | --- |
| `dist/`, `build*/` | build output; rebuild with `build.bat` or download from Releases |
| `data/`, `*.db`, `crash.log`, `config.json` | runtime state of a local install |
| `.workbuddy-ai/` | local assistant session data |
| `__pycache__/`, `.venv/` | caches |
