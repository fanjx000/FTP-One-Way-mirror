"""Commit with a clean message, even on a network share.

Why this exists: git writes the commit message into ``.git/COMMIT_EDITMSG`` and on
this project's SMB share that file is *not* truncated - a shorter message keeps the
tail of the previous one, so subjects end up containing fragments of earlier commits.
``git commit-tree`` (plumbing) never touches that file, so it is safe here.

Usage

    python tools/commit.py "Subject line"
    python tools/commit.py "Subject line" --body "paragraph 1" "paragraph 2"
    python tools/commit.py "Subject line" --amend        # rewrite the last commit
    python tools/commit.py --check                       # print + sanity-check it

It does not stage anything - run ``git add`` first, as usual.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def last_message() -> str:
    return git("log", "-1", "--format=%B").stdout.rstrip("\n")


def check() -> int:
    msg = last_message()
    if not msg:
        print("No commit found.")
        return 1
    print(f"--- last commit message ({len(msg)} chars) ---")
    print(msg)
    lines = msg.splitlines()
    dupes = {l for l in lines if lines.count(l) > 1 and len(l) > 12}
    if dupes:
        print("\nWARNING: repeated lines - the message may carry a stale tail:")
        for d in sorted(dupes):
            print("   ", d[:90])
        return 1
    print("\nLooks clean.")
    return 0


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--check":
        return check()

    subject = argv[0]
    body: list = []
    amend = False
    rest = argv[1:]
    i = 0
    while i < len(rest):
        if rest[i] == "--amend":
            amend = True
        elif rest[i] == "--body":
            i += 1
            while i < len(rest) and not rest[i].startswith("--"):
                body.append(rest[i])
                i += 1
            continue
        else:
            body.append(rest[i])
        i += 1

    message = subject + "\n"
    if body:
        message += "\n" + "\n\n".join(body) + "\n"

    if amend:
        if git("rev-parse", "--verify", "HEAD").returncode != 0:
            print("Nothing to amend.")
            return 1
    elif not git("diff", "--cached", "--name-only").stdout.strip():
        print("Nothing staged - run `git add <files>` first.")
        return 1

    # a private message file: os.replace() truncates properly on SMB
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="ftpsync_msg_"))
    msg_file = tmpdir / "message.txt"
    tmp = tmpdir / "message.tmp"
    tmp.write_text(message, encoding="utf-8")
    os.replace(tmp, msg_file)

    # The tree must come from the *index* (what `git add` staged), not from HEAD -
    # using HEAD^{tree} would silently drop the staged changes from the commit.
    tree = git("write-tree").stdout.strip()
    if not tree:
        print("git write-tree failed (empty index?).")
        return 1

    parents: list = []
    if amend:
        line = git("rev-list", "--parents", "-1", "HEAD").stdout.split()
        for p in line[1:]:
            parents += ["-p", p]
    elif git("rev-parse", "--verify", "HEAD").returncode == 0:
        parents = ["-p", git("rev-parse", "HEAD").stdout.strip()]

    made = git("commit-tree", tree, *parents, "-F", str(msg_file))
    if made.returncode != 0:
        print("commit-tree failed:", made.stderr.strip())
        msg_file.unlink(missing_ok=True)
        return 1

    sha = made.stdout.strip()
    branch = git("branch", "--show-current").stdout.strip() or "main"
    git("update-ref", f"refs/heads/{branch}", sha)

    ok = last_message() == message.rstrip("\n")
    print(f"{sha[:8]}  {subject}")
    print("message:", "ok" if ok else "CORRUPTED - run --check")
    msg_file.unlink(missing_ok=True)
    try:
        tmpdir.rmdir()
    except OSError:
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
