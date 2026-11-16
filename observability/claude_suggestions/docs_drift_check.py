#!/usr/bin/env python3
"""docs_drift_check.py - fail when README claims contradict the artifact that is actually mounted.

  python docs_drift_check.py --readme README.md \
      --artifact-metadata fraud-gate/artifacts/creditcard_hgb.metadata.json   # adjust to the real sidecar name

Checks (exit 1 on any failure):
  1. no unfilled `<EVIDENCE: ...>` placeholder is left in the README;
  2. the README never says "CAPTURE is not possible";
  3. if the mounted artifact's metadata says synthetic=true, the README must not call the card gate "promoted";
     if it says synthetic=false (a real-data artifact), the README must not say "not promoted".
"""
import argparse
import json
import re
import sys
from pathlib import Path


def check(readme_text: str, metadata: dict) -> list:
    problems = []
    for m in re.finditer(r"<EVIDENCE:[^>]*>", readme_text):
        line = readme_text.count("\n", 0, m.start()) + 1
        problems.append(f"line {line}: unfilled placeholder {m.group(0)!r}")
    if re.search(r"CAPTURE is not possible", readme_text, re.I):
        problems.append("README says 'CAPTURE is not possible'")
    synthetic = metadata.get("synthetic")
    if synthetic is True and re.search(r"card gate[^\n]*\bpromoted\b|\*\*promoted\*\*", readme_text, re.I) \
            and not re.search(r"not promoted", readme_text, re.I):
        problems.append("artifact metadata says synthetic=true but README calls the card model promoted")
    if synthetic is False and re.search(r"not promoted", readme_text, re.I):
        problems.append("artifact metadata says synthetic=false (real data) but README still says 'not promoted'")
    if synthetic is None:
        problems.append("artifact metadata has no 'synthetic' key; cannot verify the promotion claim")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", required=True)
    ap.add_argument("--artifact-metadata", required=True)
    args = ap.parse_args(argv)
    problems = check(Path(args.readme).read_text(encoding="utf-8"), json.loads(Path(args.artifact_metadata).read_text(encoding="utf-8")))
    for p in problems:
        print("DRIFT", p)
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


def _selftest():
    ok = "The card model is **promoted** and CAPTURE works.\n"
    assert check(ok, {"synthetic": False}) == []
    assert any("placeholder" in p for p in check("see <EVIDENCE: log>\n", {"synthetic": False}))
    assert any("not possible" in p for p in check("CAPTURE is not possible until mounted", {"synthetic": False}))
    assert any("not promoted" in p for p in check("The card model is not promoted.", {"synthetic": False}))
    assert any("promoted" in p for p in check("Card gate: **promoted**", {"synthetic": True}))
    assert check("The card model is not promoted (synthetic toy mounted).", {"synthetic": True}) == []
    assert any("cannot verify" in p for p in check("x", {}))
    print("docs_drift_check selftest ok")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        _selftest()
    else:
        sys.exit(main())
