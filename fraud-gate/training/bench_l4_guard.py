"""Benchmark the L4 semantic guard against real rivals on the LOCKED v5 held-out slices.

Common protocol for every scorer (apples-to-apples):
  * same input truncation (max_length, default 256);
  * ONE threshold chosen by worst-case FPR across BOTH calibration slices (in-domain + external),
    never on any test slice (reuses calibrate_l4_v5.worst_case_threshold);
  * held-out metrics on in_domain_test and external_test with Wilson 95% CIs;
  * single-row latency p50/p95 on a fixed sample.

Scorers: my v5 ONNX (new), my v4 ONNX (previous real), deployed v1 ONNX (toy baseline),
ProtectAI deberta-v3-base-prompt-injection-v2 (public neural rival, >100M so NOT deployable in
the L4 runtime but a valid quality reference), and a TF-IDF+LogReg baseline trained on v5 train.
Prompt-Guard-86M is gated (needs an HF token); its published numbers are cited in the report,
not reproduced here. Nothing is downloaded by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np

try:
    from .score_l4_onnx import load_rows, confusion, choose_threshold
    from .calibrate_l4_v5 import worst_case_threshold
except ImportError:
    from score_l4_onnx import load_rows, confusion, choose_threshold
    from calibrate_l4_v5 import worst_case_threshold


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for b in iter(lambda: fh.read(65536), b""):
            h.update(b)
    return h.hexdigest()


class OnnxAdapter:
    def __init__(self, name: str, model_path: Path, tokenizer_dir: Path, max_length: int, inj_index: int = 1):
        import onnxruntime as ort
        from transformers import AutoTokenizer
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        td = Path(tokenizer_dir)
        if (td / "tokenizer_config.json").exists() or (td / "tokenizer.json").exists():
            self.tok = AutoTokenizer.from_pretrained(str(td))
        else:
            # transformers 5 ignores BertTokenizerFast(vocab_file=...) (vocab size 5, all [UNK]).
            # Match the Java WordPieceTokenizer: lowercase, accents kept.
            from tokenizers import BertWordPieceTokenizer
            from transformers import PreTrainedTokenizerFast
            wp = BertWordPieceTokenizer(str(td / "vocab.txt"), lowercase=True, strip_accents=False)
            self.tok = PreTrainedTokenizerFast(tokenizer_object=wp._tokenizer, unk_token="[UNK]", pad_token="[PAD]",
                                               cls_token="[CLS]", sep_token="[SEP]", mask_token="[MASK]")
        n_vocab = sum(1 for _ in (td / "vocab.txt").open(encoding="utf-8")) if (td / "vocab.txt").exists() else None
        if self.tok.vocab_size < 1000 or (n_vocab and self.tok.vocab_size != n_vocab):
            raise SystemExit(f"{name}: tokenizer vocab {self.tok.vocab_size} != vocab.txt {n_vocab}")
        self.max_length = max_length
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.name = name
        self.inj_index = inj_index
        self.kind = "onnx-int8"
        self.deployable_under_100m = True

    def predict(self, texts: list[str], batch_size: int = 32) -> list[float]:
        out: list[float] = []
        for s in range(0, len(texts), batch_size):
            enc = self.tok(texts[s:s + batch_size], truncation=True, max_length=self.max_length,
                           padding="max_length", return_tensors="np",
                           return_token_type_ids="token_type_ids" in self.inputs)
            feed = {n: enc[n].astype(np.int64) for n in self.inputs}
            logits = self.session.run(None, feed)[0].astype(np.float64)
            shifted = logits - logits.max(axis=1, keepdims=True)
            e = np.exp(shifted)
            out.extend((e[:, self.inj_index] / e.sum(axis=1)).tolist())
        return out


class TransformersAdapter:
    def __init__(self, name: str, model_dir: Path, max_length: int, threads: int = 8):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        torch.set_num_threads(threads)
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(str(model_dir))
        self.model = AutoModelForSequenceClassification.from_pretrained(str(model_dir)).eval()
        id2label = {int(k): str(v).upper() for k, v in self.model.config.id2label.items()}
        self.inj_index = next((i for i, lab in id2label.items() if "INJECT" in lab or lab in ("1", "LABEL_1")), 1)
        self.max_length = max_length
        self.name = name
        self.kind = "transformers-fp32"
        self.param_count = sum(p.numel() for p in self.model.parameters())
        self.deployable_under_100m = self.param_count < 100_000_000
        self.id2label = id2label

    def predict(self, texts: list[str], batch_size: int = 16) -> list[float]:
        out: list[float] = []
        torch = self.torch
        with torch.no_grad():
            for s in range(0, len(texts), batch_size):
                enc = self.tok(texts[s:s + batch_size], truncation=True, max_length=self.max_length,
                               padding="max_length", return_tensors="pt")
                logits = self.model(**enc).logits
                probs = torch.softmax(logits, dim=-1)[:, self.inj_index]
                out.extend(probs.tolist())
        return out


class TfidfAdapter:
    def __init__(self, name: str, train_rows: list[dict], max_features: int = 60000):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        self.vec = TfidfVectorizer(ngram_range=(1, 2), max_features=max_features, sublinear_tf=True,
                                   strip_accents="unicode", lowercase=True)
        X = self.vec.fit_transform([r["text"] for r in train_rows])
        y = np.array([r["label"] for r in train_rows])
        self.clf = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
        self.clf.fit(X, y)
        self.name = name
        self.kind = "tfidf-logreg"
        self.deployable_under_100m = True

    def predict(self, texts: list[str], batch_size: int = 1024) -> list[float]:
        return self.clf.predict_proba(self.vec.transform(texts))[:, 1].tolist()


def latency_ms(scorer, texts: list[str], samples: int = 200) -> dict:
    n = min(samples, len(texts))
    idx = np.linspace(0, len(texts) - 1, n, dtype=int)
    rows = [texts[i] for i in idx]
    for r in rows[:3]:
        scorer.predict([r])
    t = []
    for r in rows:
        s = time.perf_counter_ns()
        scorer.predict([r])
        t.append((time.perf_counter_ns() - s) / 1e6)
    return {"p50": round(float(np.percentile(t, 50)), 3), "p95": round(float(np.percentile(t, 95)), 3),
            "p99": round(float(np.percentile(t, 99)), 3), "samples": n}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v5-dir", type=Path, help="artifact dir with model.int8.onnx + encoder/")
    p.add_argument("--v5-label", default="chimera_l4_v5 (mine)", help="display label for the --v5-dir scorer")
    p.add_argument("--student", action="append", default=[], metavar="LABEL=DIR",
                   help="extra distilled guard: DIR holds model.onnx (or model.int8.onnx) + vocab.txt")
    p.add_argument("--threads", type=int, default=16, help="torch threads for the non-deployable rival")
    p.add_argument("--v4-dir", type=Path)
    p.add_argument("--v1-dir", type=Path, help="deployed dir with model.int8.onnx + vocab.txt")
    p.add_argument("--protectai-dir", type=Path)
    p.add_argument("--train-data", type=Path, required=True, help="v5 train for the TF-IDF baseline")
    p.add_argument("--in-domain-calib", type=Path, required=True)
    p.add_argument("--external-calib", type=Path, required=True)
    p.add_argument("--in-domain-test", type=Path, required=True)
    p.add_argument("--external-test", type=Path, required=True)
    p.add_argument("--max-fpr", type=float, default=0.02)
    p.add_argument("--max-length", type=int, default=256)
    p.add_argument("--scorers", default="v5,v4,v1,protectai,tfidf")
    p.add_argument("--latency-samples", type=int, default=200)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()

    wanted = [s.strip() for s in args.scorers.split(",") if s.strip()]
    calib = {"in_domain_calib": load_rows(args.in_domain_calib),
             "external_calib": load_rows(args.external_calib)}
    test = {"in_domain_test": load_rows(args.in_domain_test),
            "external_test": load_rows(args.external_test)}
    train_rows = load_rows(args.train_data)

    scorers = []
    if "v5" in wanted and args.v5_dir:
        scorers.append(OnnxAdapter(args.v5_label, args.v5_dir / "model.int8.onnx",
                                   args.v5_dir / "encoder", args.max_length))
    if "v4" in wanted and args.v4_dir:
        scorers.append(OnnxAdapter("chimera_l4_v4 (mine, prev)", args.v4_dir / "model.int8.onnx",
                                   args.v4_dir / "encoder", args.max_length))
    if "v1" in wanted and args.v1_dir:
        scorers.append(OnnxAdapter("chimera_l4_v1 (deployed toy)", args.v1_dir / "model.int8.onnx",
                                   args.v1_dir, args.max_length))
    if "protectai" in wanted and args.protectai_dir:
        scorers.append(TransformersAdapter("protectai_deberta_v3 (rival)", args.protectai_dir, args.max_length,
                                           threads=args.threads))
    for spec in args.student:
        label, _, d = spec.partition("=")
        d = Path(d)
        onnx_path = d / "model.int8.onnx" if (d / "model.int8.onnx").exists() else d / "model.onnx"
        scorers.append(OnnxAdapter(label, onnx_path, d, args.max_length))
    if "tfidf" in wanted:
        scorers.append(TfidfAdapter("tfidf_logreg (baseline)", train_rows))

    results = {}
    for sc in scorers:
        t0 = time.perf_counter()
        calib_probs = {k: sc.predict([r["text"] for r in rows]) for k, rows in calib.items()}
        slices = [([r["label"] for r in calib[k]], calib_probs[k]) for k in calib]
        thr = worst_case_threshold(slices, args.max_fpr)
        entry = {"kind": sc.kind, "threshold": round(float(thr), 6),
                 "deployable_under_100m": getattr(sc, "deployable_under_100m", None),
                 "param_count": getattr(sc, "param_count", None),
                 "calib_fpr": {k: round(float(np.mean([p >= thr for p, r in zip(calib_probs[k], calib[k]) if r["label"] == 0])), 6)
                               for k in calib},
                 "test": {}}
        for k, rows in test.items():
            probs = sc.predict([r["text"] for r in rows])
            entry["test"][k] = confusion([r["label"] for r in rows], probs, thr)
        entry["latency_ms"] = latency_ms(sc, [r["text"] for r in test["external_test"]], args.latency_samples)
        entry["total_seconds"] = round(time.perf_counter() - t0, 1)
        results[sc.name] = entry
        print(f"[done] {sc.name} thr={thr:.4f} ext_recall={entry['test']['external_test']['recall']} "
              f"ext_fpr={entry['test']['external_test']['fpr']} ({entry['total_seconds']}s)", flush=True)

    report = {
        "protocol": {"max_length": args.max_length, "max_fpr_budget": args.max_fpr,
                     "threshold_method": "worst_case_fpr across in_domain_calib + external_calib",
                     "threshold_never_selected_on_test": True},
        "data_sha256": {k: sha256_file(p) for k, p in
                        {"train": args.train_data, "in_domain_calib": args.in_domain_calib,
                         "external_calib": args.external_calib, "in_domain_test": args.in_domain_test,
                         "external_test": args.external_test}.items()},
        "rows": {k: len(v) for k, v in {**calib, **test}.items()},
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "models": results,
        "rival_published_not_reproduced": {
            "protectai_deberta_v3": "HF card: detects prompt injection, NOT jailbreaks; 184M params (>100M runtime cap)",
            "meta_llama_prompt_guard_86M": "gated (HF token required); published ~0.98 recall on vendor benchmark, not reproduced here",
        },
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "l4_benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = ["# L4 semantic guard benchmark — locked v5 held-out slices", "",
             f"Common max_length={args.max_length}; threshold = worst-case FPR<= {args.max_fpr} across both calib slices; "
             "never selected on test. external_test is the honest generalization slice (SPML).", "",
            "| Model | Deployable<100M | Thr | ext recall [CI95] | ext FPR [CI95] | ext prec | in-dom recall | in-dom FPR | p50 ms | p95 ms |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for name, e in results.items():
        ext = e["test"]["external_test"]; ind = e["test"]["in_domain_test"]
        rc = ext.get("recall_ci95"); fc = ext.get("fpr_ci95")
        lines.append(
            f"| {name} | {e['deployable_under_100m']} | {e['threshold']} | "
            f"{ext['recall']} {rc} | {ext['fpr']} {fc} | {ext['precision']} | "
            f"{ind['recall']} | {ind['fpr']} | {e['latency_ms']['p50']} | {e['latency_ms']['p95']} |")
    (args.out_dir / "l4_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()