#!/usr/bin/env python3
"""Independent pre-submission check for the evm.fast `lean` track.

Runs before `yukon submit`, never instead of the official verifier. It checks:
  scope    every changed path is inside the track's editablePaths
  tokens   editable Lean files contain no proof escapes or build-time code
  claim    claim.json K agrees with the literal claimedScore in Solution.lean
  axioms   (optional) a build log's `#print axioms` lists only the permitted three
and writes a receipt with the base commit and sha256 of every editable file.
A failing check is FAIL; checks after a failed prerequisite are NOT_EVALUATED.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EDITABLE = ("submission/Solution.lean", "submission/claim.json", "submission/InitECandidate/Solver/")
PERMITTED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
# Each pattern either skips the kernel, adds trust, or runs code during the build.
FORBIDDEN = {
    "sorry": r"\bsorry\b",
    "admit": r"\badmit\b",
    "native_decide": r"\bnative_decide\b",
    "ofReduceBool": r"\bofReduce(Bool|Nat)\b",
    "axiom": r"^\s*(private\s+|protected\s+)?axiom\b",
    "implemented_by": r"\bimplemented_by\b",
    "extern": r"@\[\s*extern\b",
    "unsafe": r"\bunsafe\b",
    "debug option": r"set_option\s+debug\.",
    "run_cmd/eval": r"^\s*(#eval|run_cmd|run_elab|run_meta)\b",
    "elab/macro": r"^\s*(elab|macro|syntax|macro_rules|elab_rules)\b",
    "initialize": r"^\s*(builtin_)?initialize\b",
    "IO": r"\bIO\.(FS|Process|getEnv)\b",
}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def editable(path):
    return any(path == e or (e.endswith("/") and path.startswith(e)) for e in EDITABLE)


def strip_comments(text):
    text = re.sub(r"/-.*?-/", lambda m: "\n" * m.group().count("\n"), text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def check_scope(repo, base):
    changed = set(git(repo, "diff", "--name-only", base).split())
    changed |= set(git(repo, "ls-files", "--others", "--exclude-standard").split())
    outside = sorted(p for p in changed if not editable(p))
    return ("FAIL" if outside else "PASS"), {"changed": sorted(changed), "outside": outside}


def lean_files(repo):
    yield repo / "submission/Solution.lean"
    yield from sorted((repo / "submission/InitECandidate/Solver").rglob("*.lean"))


def check_tokens(repo):
    hits = []
    for path in lean_files(repo):
        if not path.is_file():
            continue
        lines = strip_comments(path.read_text(encoding="utf-8")).splitlines()
        for name, pattern in FORBIDDEN.items():
            for n, line in enumerate(lines, 1):
                if re.search(pattern, line):
                    hits.append({"file": path.relative_to(repo).as_posix(), "line": n, "rule": name})
    return ("FAIL" if hits else "PASS"), {"hits": hits}


def check_claim(repo):
    k = json.loads((repo / "submission/claim.json").read_text())["K"]
    text = strip_comments((repo / "submission/Solution.lean").read_text(encoding="utf-8"))
    m = re.search(r"def\s+claimedScore\s*:\s*InitE\.NatE\s*:=\s*(\.infinity|\.finite\s+(\d+)|(\d+))", text)
    if not m:
        return "FAIL", {"claim": k, "lean": None, "reason": "no literal claimedScore"}
    lean = "infinity" if m.group(1) == ".infinity" else int(m.group(2) or m.group(3))
    ok = (k == lean) and (k == "infinity" or (isinstance(k, int) and 0 <= k < 10**295))
    return ("PASS" if ok else "FAIL"), {"claim": k, "lean": lean}


def check_axioms(log_path):
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"'InitE\.Challenge\.certificate' depends on axioms: \[([^\]]*)\]", text)
    if not m:
        clean = "'InitE.Challenge.certificate' does not depend on any axioms" in text
        return ("PASS" if clean else "FAIL"), {"axioms": [] if clean else None}
    axioms = {a.strip() for a in m.group(1).split(",") if a.strip()}
    extra = sorted(axioms - PERMITTED_AXIOMS)
    return ("FAIL" if extra else "PASS"), {"axioms": sorted(axioms), "extra": extra}


def file_hashes(repo):
    out = {}
    for rel in ("submission/Solution.lean", "submission/claim.json"):
        out[rel] = hashlib.sha256((repo / rel).read_bytes()).hexdigest()
    for path in sorted((repo / "submission/InitECandidate/Solver").rglob("*")):
        if path.is_file():
            out[str(path.relative_to(repo).as_posix())] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--base", required=True, help="commit the challenge was cloned at")
    ap.add_argument("--axioms-log", help="build output containing `#print axioms`")
    ap.add_argument("--receipt", type=Path, help="write the JSON receipt here")
    args = ap.parse_args()
    repo = args.repo.resolve()

    checks = {}
    checks["scope"] = check_scope(repo, args.base)
    if checks["scope"][0] == "PASS":
        checks["tokens"] = check_tokens(repo)
        checks["claim"] = check_claim(repo)
    else:
        checks["tokens"] = checks["claim"] = ("NOT_EVALUATED", {})
    if args.axioms_log and checks["tokens"][0] == "PASS":
        checks["axioms"] = check_axioms(args.axioms_log)
    else:
        checks["axioms"] = ("NOT_EVALUATED", {"reason": "no build log" if not args.axioms_log else "tokens failed"})

    states = [s for s, _ in checks.values()]
    verdict = "FAIL" if "FAIL" in states else ("PARTIAL" if "NOT_EVALUATED" in states else "PASS")
    receipt = {
        "tool": "arkhe_precheck/1",
        "benchmark": "eigenlabs/evm-fast/lean",
        "base": args.base,
        "head": git(repo, "rev-parse", "HEAD").strip(),
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict,
        "evidence_level": "static" if checks["axioms"][0] == "NOT_EVALUATED" else "static+build-log",
        "official_verification": "not run by this tool",
        "checks": {k: {"state": s, **d} for k, (s, d) in checks.items()},
        "files": file_hashes(repo) if checks["scope"][0] == "PASS" else {},
    }
    text = json.dumps(receipt, indent=2)
    if args.receipt:
        args.receipt.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
