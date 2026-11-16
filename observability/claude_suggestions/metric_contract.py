#!/usr/bin/env python3
"""metric_contract.py - fail when a Grafana dashboard or Prometheus alert rule uses a metric
(or label) that the service does not actually expose.

Why: the Fraud-Gate dashboard queried fraud_gate_* while the app emits chimera_fraud_gate_*, so
every panel and alert was silently empty. This turns that class of bug into a failing command.

  # list what a service really exposes (use this to build a rename map)
  python metric_contract.py names --exposition fraud-gate=http://localhost:8001/metrics

  # check dashboards + alert rules against live endpoints (or saved .txt exposition files)
  python metric_contract.py check \
      --dashboards observability/grafana/dashboards --rules observability/alerts.yml \
      --exposition platform-api=http://localhost:8080/actuator/prometheus \
      --exposition fraud-gate=http://localhost:8001/metrics \
      --exposition fraud-gate-grpc=http://localhost:8082/metrics

  # apply a rename map {"old_metric": "new_metric", ...} (dry run unless --write)
  python metric_contract.py rewrite --map map.json observability/alerts.yml observability/grafana/dashboards/*.json

Rules: unknown metric or label name => ERROR (exit 1). A label value that was not observed yet =>
WARN (rare values appear only under traffic). A job with no --exposition supplied => SKIP.
Limitations: PromQL is scanned, not fully parsed; Grafana template-variable queries are not checked.
`job`, `instance`, `service`, `transport`, `app`, `environment` are target labels attached by
Prometheus (see prometheus.yml) and are never checked against the exposition.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

PROM_SYNTHETIC = {"up", "ALERTS", "ALERTS_FOR_STATE"}
PROM_SYNTHETIC_PREFIXES = ("scrape_",)
TARGET_LABELS = {"job", "instance", "service", "transport", "app", "environment"}
CLAUSE_KEYWORDS = {"by", "without", "on", "ignoring", "group_left", "group_right"}
KEYWORDS = {"and", "or", "unless", "bool", "offset", "inf", "nan", "start", "end"}

IDENT_RE = re.compile(r"[A-Za-z_:][A-Za-z0-9_:]*")
NUM_RE = re.compile(r"\d[\w.]*")
VAR_RE = re.compile(r"\$(\{[^}]*\}|[A-Za-z_][A-Za-z0-9_]*)")
MATCHER_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*)\s*(=~|!~|!=|=)\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`)')
SAMPLE_RE = re.compile(r'^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{(.*)\})?\s+\S+(?:\s+-?\d+)?\s*$')
LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"')


# ----------------------------------------------------------------------------- PromQL scanning
def _skip_string(s: str, i: int) -> int:
    quote = s[i]
    i += 1
    while i < len(s):
        if quote != "`" and s[i] == "\\":
            i += 2
            continue
        if s[i] == quote:
            return i + 1
        i += 1
    raise ValueError("unterminated string literal")


def _skip_balanced(s: str, i: int, open_c: str, close_c: str) -> int:
    """Index of the bracket matching s[i] (which must be open_c)."""
    depth = 0
    while i < len(s):
        c = s[i]
        if c in "\"'`":
            i = _skip_string(s, i)
            continue
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError(f"unbalanced {open_c}{close_c}")


def extract_selectors(expr: str):
    """Return [(metric_name, [(label, op, value), ...]), ...] for every vector selector."""
    out, i, n = [], 0, len(expr)
    while i < n:
        c = expr[i]
        if c in "\"'`":
            i = _skip_string(expr, i)
            continue
        if c == "$":
            m = VAR_RE.match(expr, i)
            i = m.end() if m else i + 1
            continue
        if c == "[":
            i = _skip_balanced(expr, i, "[", "]") + 1
            continue
        if c == "{":                       # selector without a metric name
            i = _skip_balanced(expr, i, "{", "}") + 1
            continue
        if c.isdigit():
            i = NUM_RE.match(expr, i).end()
            continue
        m = IDENT_RE.match(expr, i)
        if not m:
            i += 1
            continue
        tok, j = m.group(), m.end()
        k = j
        while k < n and expr[k].isspace():
            k += 1
        nxt = expr[k] if k < n else ""
        if tok in CLAUSE_KEYWORDS and nxt == "(":
            i = _skip_balanced(expr, k, "(", ")") + 1
            continue
        nxt_word = IDENT_RE.match(expr, k)
        is_agg_clause = bool(nxt_word) and nxt_word.group() in ("by", "without")   # sum by (x) (...)
        if tok in KEYWORDS or tok in CLAUSE_KEYWORDS or nxt == "(" or is_agg_clause:  # operator keyword, function or aggregation
            i = j
            continue
        matchers = []
        if nxt == "{":
            close = _skip_balanced(expr, k, "{", "}")
            for lab, op, raw in MATCHER_RE.findall(expr[k + 1:close]):
                matchers.append((lab, op, raw[1:-1]))
            j = close + 1
        out.append((tok, matchers))
        i = j
    return out


# ----------------------------------------------------------------------------- exposition
class Exposition:
    def __init__(self):
        self.series = defaultdict(lambda: defaultdict(set))   # sample name -> label -> values
        self.types = {}

    def add_text(self, text: str) -> "Exposition":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "TYPE":
                    self.types[parts[2]] = parts[3]
                continue
            m = SAMPLE_RE.match(line)
            if not m:
                continue
            name, labels = m.group(1), m.group(2) or ""
            entry = self.series[name]
            for lab, val in LABEL_RE.findall(labels):
                entry[lab].add(val)
        return self

    def names(self):
        return set(self.series)


def load_exposition(spec: str) -> Exposition:
    if spec.startswith(("http://", "https://")):
        with urllib.request.urlopen(spec, timeout=5) as resp:
            return Exposition().add_text(resp.read().decode("utf-8", "replace"))
    return Exposition().add_text(Path(spec).read_text(encoding="utf-8"))


def parse_sources(specs):
    sources = {}
    for s in specs:
        job, _, where = s.partition("=")
        if not where:
            raise SystemExit(f"--exposition expects JOB=URL_OR_FILE, got {s!r}")
        sources[job] = load_exposition(where)
    return sources, build_union(sources.values())


def build_union(expositions) -> Exposition:
    union = Exposition()
    for e in expositions:
        for name, labels in e.series.items():
            entry = union.series[name]          # creates the key even for label-less metrics
            for lab, vals in labels.items():
                entry[lab] |= vals
    return union


# ----------------------------------------------------------------------------- checking
def suggest(metric: str, expo: Exposition):
    names = expo.names()
    hits = [p + metric for p in ("chimera_", "") if (p + metric) in names and p]
    hits += difflib.get_close_matches(metric, sorted(names), n=3, cutoff=0.6)
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out[:3]


def check_expr(expr: str, sources, union, target_labels=TARGET_LABELS):
    issues = []
    try:
        selectors = extract_selectors(expr)
    except ValueError as exc:
        return [("ERROR", f"PromQL not scannable: {exc}")]
    for metric, matchers in selectors:
        if metric in PROM_SYNTHETIC or metric.startswith(PROM_SYNTHETIC_PREFIXES):
            continue
        jobs = [v for lab, op, v in matchers if lab == "job" and op == "="]
        if jobs:
            if jobs[0] not in sources:
                issues.append(("SKIP", f"{metric}: no exposition supplied for job '{jobs[0]}'"))
                continue
            expo = sources[jobs[0]]
        else:
            expo = union
        if metric not in expo.series:
            hint = suggest(metric, expo)
            issues.append(("ERROR", f"unknown metric {metric}" + (f"  (did you mean: {', '.join(hint)})" if hint else "")))
            continue
        labels = expo.series[metric]
        for lab, op, val in matchers:
            if lab in target_labels:
                continue
            if op in ("=", "=~") and val not in ("", ".*") and lab not in labels:
                issues.append(("ERROR", f"{metric}: unknown label '{lab}' (exposed labels: {sorted(labels) or 'none'})"))
            elif lab not in labels and ((op == "!=" and val == "") or (op == "=~" and val == ".+")):
                # series without the label have lab="" so this selector drops every series
                issues.append(("ERROR", f"{metric}: {lab}{op}\"{val}\" matches nothing - series have no '{lab}' label "
                                        f"(exposed labels: {sorted(labels) or 'none'})"))
            elif op == "=" and lab in labels and val not in labels[lab]:
                issues.append(("WARN", f"{metric}: {lab}=\"{val}\" not observed yet (seen: {sorted(labels[lab])[:6]})"))
    return issues


def _walk_panels(panels):
    for p in panels or []:
        yield p
        yield from _walk_panels(p.get("panels"))


def collect_items(dashboards: str | None, rules: str | None):
    items = []
    if dashboards:
        root = Path(dashboards)
        files = sorted(root.glob("*.json")) if root.is_dir() else [root]
        for f in files:
            dash = json.loads(f.read_text(encoding="utf-8"))
            for p in _walk_panels(dash.get("panels")):
                for t in p.get("targets", []) or []:
                    if t.get("expr"):
                        items.append((f.name, f"panel '{p.get('title')}' [{p.get('id')}] {t.get('refId', '')}", t["expr"]))
    if rules:
        import yaml
        doc = yaml.safe_load(Path(rules).read_text(encoding="utf-8"))
        for g in doc.get("groups", []):
            for r in g.get("rules", []):
                if r.get("expr"):
                    items.append((Path(rules).name, f"rule '{r.get('alert') or r.get('record')}'", str(r["expr"])))
    return items


def cmd_check(args) -> int:
    sources, union = parse_sources(args.exposition)
    target_labels = TARGET_LABELS | set(args.target_label or [])
    items = collect_items(args.dashboards, args.rules)
    if not items:
        raise SystemExit("nothing to check: pass --dashboards and/or --rules")
    counts = {"ERROR": 0, "WARN": 0, "SKIP": 0}
    for fname, loc, expr in items:
        for level, msg in check_expr(expr, sources, union, target_labels):
            counts[level] += 1
            print(f"{level:5} {fname} :: {loc}\n      {msg}")
    print(f"\nchecked {len(items)} expressions: {counts['ERROR']} error, {counts['WARN']} warn, {counts['SKIP']} skipped")
    return 1 if counts["ERROR"] or (args.strict and counts["WARN"]) else 0


def cmd_names(args) -> int:
    sources, _ = parse_sources(args.exposition)
    for job, expo in sources.items():
        print(f"# {job}")
        for name in sorted(expo.names()):
            labels = ",".join(sorted(expo.series[name])) or "-"
            print(f"{name}\t{expo.types.get(name, '')}\t{labels}")
    return 0


# ----------------------------------------------------------------------------- rewrite
def rewrite_text(text: str, mapping: dict):
    counts = {}
    for old in sorted(mapping, key=len, reverse=True):
        pat = re.compile(r"(?<![A-Za-z0-9_:])" + re.escape(old) + r"(?=(?:_bucket|_count|_sum|_total)?(?![A-Za-z0-9_:]))")
        text, n = pat.subn(mapping[old], text)
        if n:
            counts[old] = n
    return text, counts


def cmd_rewrite(args) -> int:
    mapping = json.loads(Path(args.map).read_text(encoding="utf-8"))
    total = 0
    for f in args.files:
        raw = Path(f).read_bytes().decode("utf-8")
        new, counts = rewrite_text(raw, mapping)
        for old, n in counts.items():
            print(f"{f}: {old} -> {mapping[old]}  x{n}")
            total += n
        if counts and args.write:
            Path(f).write_bytes(new.encode("utf-8"))   # bytes: keeps CRLF/LF untouched
    print(f"{total} replacement(s){'' if args.write else ' (dry run; pass --write to apply)'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--dashboards")
    c.add_argument("--rules")
    c.add_argument("--exposition", action="append", required=True, help="JOB=URL_OR_FILE (repeatable)")
    c.add_argument("--target-label", action="append", help="extra labels attached by Prometheus, not by the app")
    c.add_argument("--strict", action="store_true", help="treat WARN as failure")
    c.set_defaults(fn=cmd_check)
    n = sub.add_parser("names")
    n.add_argument("--exposition", action="append", required=True)
    n.set_defaults(fn=cmd_names)
    r = sub.add_parser("rewrite")
    r.add_argument("--map", required=True)
    r.add_argument("--write", action="store_true")
    r.add_argument("files", nargs="+")
    r.set_defaults(fn=cmd_rewrite)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
