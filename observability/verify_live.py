from __future__ import annotations

import argparse
import json
import math
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import metric_contract as mc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    def api(path, **params):
        url = "http://127.0.0.1:9090/api/v1/" + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as response:
            body = json.load(response)
        if body["status"] != "success":
            raise RuntimeError(body)
        return body["data"]
    targets = api("targets")["activeTargets"]
    report = {"targets": [], "contract": [], "queries": []}
    sources = {}
    for target in targets:
        job = target["labels"]["job"]
        report["targets"].append({"job": job, "health": target["health"], "error": target["lastError"]})
        if target["health"] != "up":
            continue
        text = subprocess.check_output(["docker", "compose", "-f", str(root / "compose.yaml"), "exec", "-T", "prometheus", "wget", "-q", "-O", "-", target["scrapeUrl"]], encoding="utf-8", timeout=30)
        sources[job] = mc.Exposition().add_text(text)
    union = mc.build_union(list(sources.values()))
    items = mc.collect_items(str(root / "observability/grafana/dashboards"), str(root / "observability/alerts.yml"))
    for filename, location, expr in items:
        issues = mc.check_expr(expr, sources, union)
        for level, message in issues:
            report["contract"].append({"file": filename, "location": location, "level": level, "message": message})
        try:
            data = api("query", query=expr)
            results = data["result"]
            values = [float(v["value"][1]) for v in results] if data["resultType"] == "vector" else []
            report["queries"].append({"file": filename, "location": location, "expr": expr, "series": len(results), "finite": sum(math.isfinite(v) for v in values), "nonfinite": sum(not math.isfinite(v) for v in values)})
        except Exception as exc:
            report["queries"].append({"file": filename, "location": location, "expr": expr, "error": str(exc)})
    report["rules"] = api("rules")
    report["errors"] = (
        sum(t["health"] != "up" for t in report["targets"])
        + sum(i["level"] in ("ERROR", "WARN", "SKIP") for i in report["contract"])
        + sum("error" in q for q in report["queries"])
        + sum(rule["health"] != "ok" for group in report["rules"]["groups"] for rule in group["rules"])
    )
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"targets": report["targets"], "contract": report["contract"], "errors": report["errors"], "expressions": len(items), "empty_or_nonfinite": [q for q in report["queries"] if q.get("series") == 0 or q.get("nonfinite", 0)]}, indent=2))
    raise SystemExit(bool(report["errors"]))


if __name__ == "__main__":
    main()
