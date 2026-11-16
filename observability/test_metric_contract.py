"""Tests for metric_contract.py. Run: python test_metric_contract.py  (or pytest).
The fixtures encode the mismatches from the observability issue report."""
import json
import tempfile
from pathlib import Path

import metric_contract as mc

FRAUD_GATE_EXPO = """\
# fixture built from the issue report's "actually emitted" column, not scraped from a live service
# TYPE chimera_fraud_gate_model_loaded gauge
chimera_fraud_gate_model_loaded 1.0
# TYPE chimera_fraud_gate_scores_total counter
chimera_fraud_gate_scores_total{action="CHALLENGE",fallback="false"} 5.0
chimera_fraud_gate_scores_total{action="VOID",fallback="false"} 1.0
# TYPE chimera_fraud_gate_score_latency_ms histogram
chimera_fraud_gate_score_latency_ms_bucket{le="5.0"} 3.0
chimera_fraud_gate_score_latency_ms_bucket{le="+Inf"} 6.0
chimera_fraud_gate_score_latency_ms_sum 40.5
chimera_fraud_gate_score_latency_ms_count 6.0
"""
PLATFORM_EXPO = """\
cache_gets_total{cache="checkout-order",result="hit"} 9.0
cache_gets_total{cache="checkout-order",result="miss"} 1.0
http_server_requests_seconds_count{status="200",uri="/x"} 4.0
"""


def select(expr):
    return [(m, [(l, o, v) for l, o, v in ms]) for m, ms in mc.extract_selectors(expr)]


def test_extract_selectors_real_expressions():
    assert select('up{job="fraud-gate"} == 0') == [("up", [("job", "=", "fraud-gate")])]
    s = select('histogram_quantile(0.95, sum(rate(http_server_requests_seconds_bucket{job="platform-api"}[5m])) by (le, uri))')
    assert s == [("http_server_requests_seconds_bucket", [("job", "=", "platform-api")])]
    # the CPU expression from alerts.yml: three metrics, none of the label names leak in
    names = [m for m, _ in select("(rate(container_cpu_usage_seconds_total[5m]) / container_spec_cpu_quota / container_spec_cpu_period)")]
    assert names == ["container_cpu_usage_seconds_total", "container_spec_cpu_quota", "container_spec_cpu_period"]
    # clauses, offsets, variables and strings are not metrics
    assert [m for m, _ in select('sum by (le) (rate(a_total[$__rate_interval] offset 5m)) / on(instance) group_left b_bytes > bool 0')] == ["a_total", "b_bytes"]
    assert [m for m, _ in select('label_replace(x_gauge, "dst", "$1", "src", "(.*)")')] == ["x_gauge"]
    assert [m for m, _ in select("absent(up{job='x'})")] == ["up"]
    # aggregation with the clause BEFORE the parentheses must not read 'sum' as a metric
    assert [m for m, _ in select("sum by (action) (rate(x_total[1m])) / avg without (a) (y_gauge)")] == ["x_total", "y_gauge"]


def test_extract_selectors_rejects_unbalanced():
    for bad in ('foo{job="x"', "sum(rate(foo[5m])"):
        try:
            mc.extract_selectors(bad) if bad.startswith("foo") else mc._skip_balanced(bad, 3, "(", ")")
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should raise")


def test_exposition_parser():
    e = mc.Exposition().add_text(FRAUD_GATE_EXPO)
    assert "chimera_fraud_gate_score_latency_ms_bucket" in e.names()
    assert e.series["chimera_fraud_gate_scores_total"]["action"] == {"CHALLENGE", "VOID"}
    assert e.types["chimera_fraud_gate_model_loaded"] == "gauge"


def _sources():
    fg, pa = mc.Exposition().add_text(FRAUD_GATE_EXPO), mc.Exposition().add_text(PLATFORM_EXPO)
    return {"fraud-gate": fg, "platform-api": pa}, mc.build_union([fg, pa])


def test_the_reported_mismatches_are_caught_with_suggestions():
    sources, union = _sources()
    broken = {
        "fraud_gate_model_available": "chimera_fraud_gate_model_loaded",
        "sum(rate(fraud_gate_decisions_total[1m])) by (decision)": None,
        "histogram_quantile(0.95, sum(rate(fraud_gate_scoring_duration_seconds_bucket[5m])) by (le))": None,
        'sum(rate(cache_hits_total{job="platform-api"}[5m]))': "cache_gets_total",
    }
    for expr, want in broken.items():
        issues = mc.check_expr(expr, sources, union)
        assert any(level == "ERROR" and "unknown metric" in msg for level, msg in issues), expr
        if want:
            assert want in " ".join(m for _, m in issues), (expr, issues)


def test_corrected_queries_pass_and_label_checks_work():
    sources, union = _sources()
    good = [
        "chimera_fraud_gate_model_loaded == 0",
        'sum by (action) (rate(chimera_fraud_gate_scores_total[1m]))',
        'histogram_quantile(0.95, sum(rate(chimera_fraud_gate_score_latency_ms_bucket[5m])) by (le, transport))',
        'sum(rate(cache_gets_total{job="platform-api",result="hit"}[5m])) / sum(rate(cache_gets_total{job="platform-api"}[5m]))',
    ]
    for expr in good:
        assert mc.check_expr(expr, sources, union) == [], expr
    # the old label name (decision) must fail, an unseen value only warns
    wrong_label = mc.check_expr('chimera_fraud_gate_scores_total{decision="CHALLENGE"}', sources, union)
    assert wrong_label and wrong_label[0][0] == "ERROR" and "unknown label 'decision'" in wrong_label[0][1]
    unseen = mc.check_expr('chimera_fraud_gate_scores_total{action="REVIEW"}', sources, union)
    assert [lvl for lvl, _ in unseen] == ["WARN"]
    # label!="" on a label the series never carry drops everything (cAdvisor `container` vs `name` on Docker)
    cad = mc.Exposition().add_text('container_memory_usage_bytes{id="/docker/a",name="gate"} 1\n')
    u = mc.build_union([cad])
    bad = mc.check_expr('container_memory_usage_bytes{container!=""}', {"cadvisor": cad}, u)
    assert bad and bad[0][0] == "ERROR" and "matches nothing" in bad[0][1]
    assert mc.check_expr('container_memory_usage_bytes{name!=""}', {"cadvisor": cad}, u) == []
    # job without an exposition is skipped, never a false error
    assert [lvl for lvl, _ in mc.check_expr('pg_up{job="postgres"}', sources, union)] == ["SKIP"]
    # up/scrape_* are synthetic
    assert mc.check_expr('up{job="platform-api"} == 0 and scrape_duration_seconds > 1', sources, union) == []


def test_cli_exit_codes_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "fg.txt").write_text(FRAUD_GATE_EXPO, encoding="utf-8")
        dash = {"panels": [{"id": 1, "title": "row", "panels": [   # nested panel inside a row
            {"id": 2, "title": "Model", "targets": [{"refId": "A", "expr": "fraud_gate_model_available"}]}]}]}
        (tmp / "d.json").write_text(json.dumps(dash), encoding="utf-8")
        rules = "groups:\n- name: g\n  rules:\n  - alert: A\n    expr: |\n      chimera_fraud_gate_model_loaded == 0\n    for: 1m\n"
        (tmp / "r.yml").write_text(rules, encoding="utf-8")
        args = ["check", "--exposition", f"fraud-gate={tmp / 'fg.txt'}"]
        assert mc.main(args + ["--dashboards", str(tmp / "d.json")]) == 1
        assert mc.main(args + ["--rules", str(tmp / "r.yml")]) == 0
        dash["panels"][0]["panels"][0]["targets"][0]["expr"] = 'pg_up{job="postgres"}'
        (tmp / "d.json").write_text(json.dumps(dash), encoding="utf-8")
        assert mc.main(args + ["--dashboards", str(tmp / "d.json"), "--strict"]) == 1


def test_rewrite_maps_names_not_prefixes_and_keeps_crlf():
    mapping = {"fraud_gate_scoring_duration_seconds": "chimera_fraud_gate_score_latency_ms",
               "fraud_gate_decisions_total": "chimera_fraud_gate_scores_total"}
    text = ("rate(fraud_gate_scoring_duration_seconds_bucket[5m])\r\n"
            "fraud_gate_decisions_total{x}\r\n"
            "fraud_gate_decisions_total_extra\r\n"          # different metric: untouched
            "my_fraud_gate_decisions_total\r\n")            # longer name: untouched
    new, counts = mc.rewrite_text(text, mapping)
    assert "chimera_fraud_gate_score_latency_ms_bucket[5m]" in new
    assert "chimera_fraud_gate_scores_total{x}" in new
    assert "fraud_gate_decisions_total_extra" in new and "my_fraud_gate_decisions_total" in new
    assert new.count("\r\n") == 4 and counts == {"fraud_gate_scoring_duration_seconds": 1, "fraud_gate_decisions_total": 1}


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"{len(tests)} passed")
