# Publishing this project to GitHub

Target project: **FTP One-Way mirror** → `https://github.com/fanjx000/FTP-One-Way-mirror`

The working copy in this folder is already a git repository with one commit, so publishing is
two commands. Pick one of the two paths below.

## Path A — empty repository already created on GitHub (recommended)

1. On GitHub: **New repository** → name `FTP-One-Way-mirror` → **do not** add a README,
   .gitignore or licence (this folder already has them) → Create.
2. In this folder:

```powershell
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

## After the first push

| Step | How |
| --- | --- |
| Make it public | Settings → General → Danger zone → Change visibility |
| Publish the exe | Releases → Draft a new release → tag `v1.8.2` → attach `dist/FtpSync.exe` |
| Turn on CI | Actions tab → enable workflows. `.github/workflows/tests.yml` runs the whole test suite on Windows and attaches a built exe |
| Topics | Settings → Topics: `ftp`, `synchronization`, `pyside6`, `windows`, `backup`, `mirror` |

## What is intentionally not committed

| Path | Why |
| --- | --- |
| `dist/`, `build*/` | build output; rebuild with `build.bat` or download from Releases |
| `data/`, `*.db`, `crash.log`, `config.json` | runtime state of a local install |
| `.workbuddy-ai/` | local assistant session data |
| `__pycache__/`, `.venv/` | caches |
