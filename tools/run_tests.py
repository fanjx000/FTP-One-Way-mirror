"""Run every test suite and print one readable report.

Locally:

    python tools/run_tests.py             # all suites
    python tools/run_tests.py server      # only the non-GUI ones (fast)
    python tools/run_tests.py ui          # only the widget ones
    python tools/run_tests.py -k 505 i18n # name filter

In CI it also writes a Markdown table + the tail of every failing suite to
``$GITHUB_STEP_SUMMARY``, so the reason for a red run is visible on the run page
without downloading logs.  Nothing else in the project needs to know about CI.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

# name -> (script, needs_a_window)
SUITES = {
    "sync":          ("test_sync.py", False),
    "505":           ("test_505.py", False),
    "quirky_server": ("test_quirky_server.py", False),
    "variants":      ("test_variants.py", False),
    "mkdir_modes":   ("test_mkdir_modes.py", False),
    "diagnose":      ("test_diagnose.py", False),
    "about":         ("test_about.py", True),
    "crash_safety":  ("test_crash_safety.py", True),
    "ui_response":   ("test_ui_response.py", True),
    "i18n":          ("test_i18n.py", True),
    "ui_audit":      ("ui_audit.py", True),
}

NOISE = ("[I ", "[W ", "DeprecationWarning", "  cert", "  key", "  kpath",
         "CRLF will be replaced")


def clean(lines: list, limit: int) -> list:
    """Drop library noise, keep the assertions and the traceback."""
    kept = [l for l in lines if not any(l.startswith(n) or n in l for n in NOISE)]
    return kept[-limit:]


def run_one(script: str, env: dict, timeout: int = 900) -> tuple:
    started = time.monotonic()
    try:
        # -X utf8: on an English Windows runner the console is cp1252 and the
        # default encoding for open() follows the locale, so printing Chinese or
        # writing a Chinese-named file raises UnicodeEncodeError.  UTF-8 mode
        # fixes both without touching the suites.
        proc = subprocess.run([sys.executable, "-X", "utf8", "-u", str(TOOLS / script)],
                             cwd=str(ROOT), capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             env=env, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out, time.monotonic() - started
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return "timeout", out if isinstance(out, str) else "", time.monotonic() - started


def main(argv: list) -> int:
    wanted = [a for a in argv if not a.startswith("-")]
    only = None
    if "-k" in argv:
        only = argv[argv.index("-k") + 1:]

    if "server" in wanted:
        chosen = {k: v for k, v in SUITES.items() if not v[1]}
    elif "ui" in wanted:
        chosen = {k: v for k, v in SUITES.items() if v[1]}
    elif any(w in SUITES for w in wanted):
        chosen = {k: SUITES[k] for k in wanted if k in SUITES}
    else:
        chosen = dict(SUITES)

    if only:
        chosen = {k: v for k, v in chosen.items()
                  if any(o.lower() in k.lower() for o in only)}

    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    results = {}
    for name, (script, _gui) in chosen.items():
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::group::{name} ({script})", flush=True)
        else:
            print(f"\n=== {name} ({script}) ".ljust(78, "="), flush=True)
        code, output, seconds = run_one(script, env)
        ok = code == 0
        results[name] = (ok, seconds, output)
        print(output.rstrip(), flush=True)
        print(f"--- {name}: {'PASS' if ok else f'FAIL (exit {code})'} "
              f"in {seconds:.1f}s", flush=True)
        if os.environ.get("GITHUB_ACTIONS"):
            print("::endgroup::", flush=True)

    failed = [n for n, (ok, _, _) in results.items() if not ok]

    # ---- report -------------------------------------------------------
    print("\n" + "=" * 78)
    print(f"{'suite':<16}{'result':<10}{'time':>8}")
    print("-" * 78)
    for name, (ok, seconds, _) in results.items():
        print(f"{name:<16}{'PASS' if ok else 'FAIL':<10}{seconds:>7.1f}s")
    print("=" * 78)
    print(f"{len(results) - len(failed)}/{len(results)} suites passed")

    # Workflow annotations: these show up in the run page's "Annotations" box, so a
    # failure is readable without opening the raw log.
    if os.environ.get("GITHUB_ACTIONS"):
        for name in failed:
            _, _, output = results[name]
            lines_out = [l.rstrip() for l in clean(output.splitlines(), 60)]
            fails = [l for l in lines_out if l.lstrip().startswith("[FAIL]")]
            if fails:
                detail = fails[0]
            else:
                detail = " / ".join(l.strip() for l in lines_out[-6:] if l.strip())
            detail = detail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
            print(f"::error title={name} failed::{detail[:900]}", flush=True)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = ["## Test results", "", "| suite | result | time |",
                 "| --- | --- | --- |"]
        for name, (ok, seconds, _) in results.items():
            lines.append(f"| `{name}` | {'PASS' if ok else '**FAIL**'} | {seconds:.1f}s |")
        lines += ["", f"**{len(results) - len(failed)}/{len(results)} suites passed**", ""]
        for name in failed:
            _, _, output = results[name]
            tail = clean(output.splitlines(), 40)
            lines += [f"### {name} — failing output", "", "```",
                      "\n".join(tail).replace("```", "'''"), "```", ""]
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
