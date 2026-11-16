from __future__ import annotations

import argparse
import gc
import json
import math
import random
import shutil
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

from l4_v9 import OUT, ROOT, cutoff, digest, encode_views, gates, read_rows, save_json, score_onnx, session, teacher_windows

V8 = ROOT / "build-check/l4_v8/out_v8"
V6 = ROOT / "build-check/l4_distill/out_minilm_l12_v2"
PROTECT = ROOT / "fraud-gate/training/benchmarks/rivals/protectai_deberta_v3"
DEST = OUT / "out_v9"


def calibration_paths():
    base = ROOT / "datasets/new_custom_datasets/out/v5"
    return {"internal": base / "l4_v5_calib.jsonl", "external": base / "l4_v5_external_calib.jsonl",
            "v8new": ROOT / "build-check/l4_v8/new_calib.jsonl", "v9new": OUT / "new_calib.jsonl", "paired": OUT / "paired_calib.jsonl"}


def validate_data():
    manifest = json.loads((OUT / "data_manifest.json").read_text())
    for path, sha in manifest["locked"].items():
        if digest(ROOT / path) != sha:
            raise ValueError(f"Locked dataset changed: {path}")
    for name, sha in manifest["outputs"].items():
        if digest(OUT / f"{name}.jsonl") != sha:
            raise ValueError(f"v9 dataset changed: {name}")
    return manifest


def protocol():
    value = {"seed": 13, "epochs": 4, "lr": 1e-5, "batch_size": 32, "alpha": .5, "temperature": 3.,
             "lambda_cos": .05, "lambda_hinge": .1, "hinge_margin": 1.5, "quant_noise_sd": .1,
             "segment_dropout": .5, "calibration_fpr_budget": .01, "test_fpr_gate": .02,
             "pos_weight": "sqrt(negative/positive), capped at 3, computed per view", "init": str(V8.relative_to(ROOT)),
             "teachers": ["local ProtectAI DeBERTa-v3 (bf16 GPU)", "v6 retention HF checkpoint (bf16 GPU), A only"],
             "teacher_window": "decode student-visible token window; ProtectAI retokenizes at max512, system first",
             "stacker": "TFIDF 1-3grams max50000 + LR fit train A only; 5 GroupKFold XGB depth3/300trees fit meta only; no external labels in fitting",
             "selection": "maximize mean recall across four standalone calibration slices and synthetic paired calibration; thresholds per view, worst-case within view",
             "threshold": "strict >; per model calibration-only; stacker max(meta OOF worst-case, ensemble locked-calibration worst-case)",
             "data_manifest_sha256": digest(OUT / "data_manifest.json"), "baseline_sha256": {"v6": digest(V6 / 'model.onnx'), "v8": digest(V8 / 'model.onnx')},
             "limitations": ["research only: noncommercial No Robots", "no unlabelled examples in this run", "no Prompt Guard specialist teacher", "synthetic pairs are authored templates, no independent human spot-check", "Java paired/stacked integration NOT_MEASURED", "no deployed changes permitted by this experiment"]}
    path = OUT / "protocol.json"
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("Protocol drift")
    else:
        save_json(path, value)
    return value


def torch_scores(model, encoded, batch_size=32, hidden=False):
    margins, vectors = [], []
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(encoded["input_ids"]), batch_size):
            feed = {k: torch.from_numpy(v[start:start + batch_size]).cuda() for k, v in encoded.items()}
            with torch.autocast("cuda", dtype=torch.bfloat16):
                result = model(**feed, output_hidden_states=hidden)
            margins.extend((result.logits[:, 1].float() - result.logits[:, 0].float()).cpu().tolist())
            if hidden:
                vectors.extend(result.hidden_states[-1][:, 0].float().cpu().numpy())
    return np.asarray(margins, dtype=np.float32), np.asarray(vectors, dtype=np.float16)


def cache_teachers(tok, sets):
    lock = OUT / "teacher_cache.json"
    if lock.exists():
        info = json.loads(lock.read_text())
        for name, rows in sets.items():
            if info["files"][name] != digest(OUT / f"teacher_{name}.npz"):
                raise ValueError("Teacher cache changed")
        if info["protocol_sha256"] != digest(OUT / 'protocol.json'):
            raise ValueError("Teacher protocol changed")
        return info
    cache = {}
    for name, rows in sets.items():
        cache[name] = {"a": np.full((len(rows), 2), np.nan, np.float32), "b": np.full((len(rows), 2), np.nan, np.float32)}
        if name == "train":
            cache[name].update(ha=np.zeros((len(rows), 768), np.float16), hb=np.zeros((len(rows), 768), np.float16))
    ptok = AutoTokenizer.from_pretrained(str(PROTECT), local_files_only=True)
    protect = AutoModelForSequenceClassification.from_pretrained(str(PROTECT), local_files_only=True).cuda().eval()
    for name, rows in sets.items():
        for view in ("a", "b"):
            indices, texts = teacher_windows(tok, rows, view)
            keep = [j for j, i in enumerate(indices) if view == "b" or rows[i]["label_a"] is not None]
            indices, texts = [indices[j] for j in keep], [texts[j] for j in keep]
            if not texts:
                continue
            start_time = time.time()
            for start in range(0, len(texts), 16):
                items = texts[start:start + 16]
                if view == "b":
                    encoded = ptok([x[0] for x in items], [x[1] for x in items], padding=True, truncation=True, max_length=512, return_tensors="np")
                else:
                    encoded = ptok(items, padding=True, truncation=True, max_length=512, return_tensors="np")
                encoded.pop("token_type_ids", None)
                margins, hidden = torch_scores(protect, encoded, 16, hidden=name == "train")
                idx = indices[start:start + len(items)]
                cache[name][view][idx, 0] = margins
                if name == "train":
                    cache[name]['h' + view][idx] = hidden
                if start % 1600 == 0:
                    print(f"ProtectAI {name}/{view} {start}/{len(texts)} elapsed={time.time()-start_time:.1f}s", flush=True)
    del protect
    gc.collect()
    torch.cuda.empty_cache()
    retention = AutoModelForSequenceClassification.from_pretrained(str(V6 / "hf_checkpoint"), local_files_only=True).cuda().eval()
    for name, rows in sets.items():
        indices, encoded = encode_views(tok, rows, "a")
        scores, _ = torch_scores(retention, encoded)
        cache[name]["a"][:, 1] = scores
    del retention
    gc.collect()
    torch.cuda.empty_cache()
    offsets = {}
    for view in ("a", "b"):
        offsets[view] = []
        for column in range(2):
            if view == "b" and column == 1:
                offsets[view].append(0.)
                continue
            scores, labels = [], []
            for name, rows in sets.items():
                if name == "train":
                    continue
                y = np.array([r["label_a"] if view == "a" else r["label"] for r in rows])
                s = cache[name][view][:, column]
                valid = np.isfinite(s) & (y != None)
                if valid.any():
                    scores.append(np.clip(s[valid], -20, 20))
                    labels.append(y[valid].astype(int))
            offsets[view].append(cutoff(scores, labels, .01))
    for name, data in cache.items():
        np.savez_compressed(OUT / f"teacher_{name}.npz", **data)
    info = {"offsets": offsets, "files": {name: digest(OUT / f"teacher_{name}.npz") for name in cache},
            "protocol_sha256": digest(OUT / "protocol.json"), "models": {"protectai": digest(PROTECT / "model.safetensors"), "v6": digest(V6 / "hf_checkpoint/model.safetensors")}}
    save_json(lock, info)
    print("Teacher offsets", offsets, flush=True)
    return info


def train(tok, sets, info, cfg):
    if (DEST / "hf_checkpoint/config.json").exists():
        raise ValueError("Checkpoint already exists; use export stage, not retraining")
    random.seed(cfg["seed"])
    np.random.seed(cfg["seed"])
    torch.manual_seed(cfg["seed"])
    model = AutoModelForSequenceClassification.from_pretrained(str(V8 / "hf_checkpoint"), local_files_only=True).cuda()
    projection = nn.Linear(model.config.hidden_size, 768, bias=False).cuda()
    rows = sets["train"]
    cache = np.load(OUT / "teacher_train.npz")
    data = {}
    for view in ("a", "b"):
        indices, enc = encode_views(tok, rows, view)
        indices = np.asarray(indices)
        y = np.array([rows[i]["label_a"] if view == "a" else rows[i]["label"] for i in indices])
        valid = y != None
        indices, y = indices[valid], y[valid].astype(int)
        centered, weights = gates(cache[view][indices], info["offsets"][view], y, [rows[i]["source"] for i in indices], view)
        data[view] = {"enc": {k: torch.from_numpy(v[valid]) for k, v in enc.items()}, "y": torch.tensor(y),
                      "target": torch.from_numpy(centered), "weight": torch.from_numpy(weights),
                      "hidden": torch.from_numpy(cache['h' + view][indices].astype(np.float32)),
                      "posweight": min(3., math.sqrt(sum(y == 0) / sum(y == 1)))}
    params = list(model.parameters()) + list(projection.parameters())
    opt = torch.optim.AdamW(params, lr=cfg["lr"], weight_decay=.01)
    steps = sum(math.ceil(len(d["y"]) / cfg["batch_size"]) for d in data.values())
    sched = get_linear_schedule_with_warmup(opt, int(.06 * steps * cfg["epochs"]), steps * cfg["epochs"])
    history, best_score, best_state, best_epoch = [], -1., None, None
    cal = {name: (encode_views(tok, rows, 'b' if name == 'paired' else 'a')[1], np.array([r['label'] for r in rows])) for name, rows in sets.items() if name != "train"}
    for epoch in range(1, cfg["epochs"] + 1):
        batches = []
        rng = np.random.default_rng(cfg["seed"] + epoch)
        for view, d in data.items():
            order = rng.permutation(len(d["y"]))
            batches.extend((view, order[start:start + cfg['batch_size']]) for start in range(0, len(order), cfg['batch_size']))
        rng.shuffle(batches)
        model.train()
        projection.train()
        total, started = 0., time.time()
        for step, (view, idx) in enumerate(batches):
            d = data[view]
            feed = {k: v[idx].cuda() for k, v in d["enc"].items()}
            if view == "b":
                feed["token_type_ids"] *= (torch.rand((len(idx), 1), device="cuda") >= .5)
            y, target, weight, hidden = (d[k][idx].cuda() for k in ("y", "target", "weight", "hidden"))
            with torch.autocast("cuda", dtype=torch.bfloat16):
                result = model(**feed, output_hidden_states=True)
                projected = projection(result.hidden_states[-1][:, 0])
            logits = result.logits.float()
            margin = logits[:, 1] - logits[:, 0]
            noisy = margin + torch.randn_like(margin) * cfg['quant_noise_sd']
            ce = F.cross_entropy(logits, y, weight=torch.tensor([1., d['posweight']], device='cuda'), reduction='none')
            temperature = cfg['temperature']
            kd = F.binary_cross_entropy_with_logits(noisy[:, None].expand_as(target) / temperature, torch.sigmoid(target / temperature), reduction='none') * temperature ** 2
            count = weight.sum(1)
            kd = (kd * weight).sum(1) / count.clamp(min=1)
            alpha = torch.where(count > 0, cfg['alpha'], 1.)
            cosine = (1 - F.cosine_similarity(projected.float(), hidden, dim=1)) * weight[:, 0]
            hinge = F.relu(cfg['hinge_margin'] - (2 * y - 1) * noisy)
            loss = (alpha * ce + (1 - alpha) * kd + cfg['lambda_cos'] * cosine + cfg['lambda_hinge'] * hinge).mean()
            if not torch.isfinite(loss):
                raise ValueError("Nonfinite training loss")
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.)
            opt.step()
            sched.step()
            total += loss.item()
            if step % 100 == 0:
                print(f"epoch={epoch} step={step}/{steps} loss={total/(step+1):.5f} seconds={time.time()-started:.1f}", flush=True)
        scores = {name: torch_scores(model, enc)[0] for name, (enc, _) in cal.items()}
        cut_a = cutoff([s for n, s in scores.items() if n != 'paired'], [y for n, (_, y) in cal.items() if n != 'paired'], .01)
        cut_b = cutoff([scores['paired']], [cal['paired'][1]], .01)
        measures = {name: {"recall": float(np.mean(s[y == 1] > (cut_b if name == 'paired' else cut_a))), "fpr": float(np.mean(s[y == 0] > (cut_b if name == 'paired' else cut_a)))} for name, s in scores.items() for y in [cal[name][1]]}
        selection = float(np.mean([m['recall'] for m in measures.values()]))
        record = {"epoch": epoch, "loss": total / steps, "seconds": time.time()-started, "calibration": measures, "selection": selection, "cut_a": cut_a, "cut_b": cut_b}
        history.append(record)
        print(json.dumps(record), flush=True)
        if selection > best_score:
            best_score, best_epoch = selection, epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    model.cpu().eval().save_pretrained(DEST / "hf_checkpoint")
    tok.save_pretrained(DEST / "hf_checkpoint")
    save_json(OUT / "training_result.json", {"best_epoch": best_epoch, "best_score": best_score, "history": history,
              "parameters": sum(p.numel() for p in model.parameters()), "protocol_sha256": digest(OUT / 'protocol.json'),
              "teacher_cache_sha256": digest(OUT / 'teacher_cache.json')})
    del model, projection, best_state
    gc.collect()
    torch.cuda.empty_cache()


def export(tok):
    import onnx
    from onnxruntime.quantization import QuantType, quantize_dynamic
    torch.set_num_threads(1)
    model = AutoModelForSequenceClassification.from_pretrained(str(DEST / "hf_checkpoint"), local_files_only=True, attn_implementation="eager").float().eval()
    class Wrapper(nn.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model
        def forward(self, input_ids, attention_mask, token_type_ids):
            return self.model(input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids).logits
    wrapper = Wrapper(model)
    enc = encode_views(tok, [{"text": "explain a bank transfer", "system": "answer finance questions only"}], 'b')[1]
    torch.onnx.export(wrapper, tuple(torch.from_numpy(v) for v in enc.values()), str(DEST / "model_fp32.onnx"),
                      input_names=list(enc), output_names=['logits'], dynamic_axes={**{k: {0: 'batch', 1: 'seq'} for k in enc}, 'logits': {0: 'batch'}},
                      opset_version=17, do_constant_folding=True, dynamo=False)
    quantize_dynamic(str(DEST / "model_fp32.onnx"), str(DEST / "model.onnx"), weight_type=QuantType.QInt8)
    onnx.checker.check_model(str(DEST / "model.onnx"))
    shutil.copyfile(V8 / "vocab.txt", DEST / "vocab.txt")
    s32, s8 = session(DEST / "model_fp32.onnx"), session(DEST / "model.onnx")
    report = {"sha256": digest(DEST / 'model.onnx'), "bytes": (DEST / 'model.onnx').stat().st_size, "views": {}}
    for view in ('a', 'b'):
        rows = list(read_rows(OUT / ('paired_calib.jsonl' if view == 'b' else 'new_calib.jsonl')))[:64]
        _, enc = encode_views(tok, rows, view)
        f32, q8 = score_onnx(s32, enc), score_onnx(s8, enc)
        report['views'][view] = {"int8_mean_abs_margin_drift": float(np.mean(abs(q8-f32))),
                                 "int8_max_abs_margin_drift": float(np.max(abs(q8-f32))), "samples": len(rows)}
    report['eager_parity'] = "verified separately under system Python CPU torch (export_parity.json); ROCm/CPU torch exporters trace the eager mask differently"
    save_json(OUT / 'export_result.json', report)
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorized-data', action='store_true')
    parser.add_argument('--stage', choices=['all', 'export'], default='all')
    args = parser.parse_args()
    if not args.authorized_data:
        raise SystemExit('--authorized-data required')
    validate_data()
    cfg = protocol()
    tok = AutoTokenizer.from_pretrained(str(V8 / 'hf_checkpoint'), local_files_only=True)
    DEST.mkdir(exist_ok=True)
    if args.stage == 'all':
        if not torch.cuda.is_available():
            raise SystemExit('ROCm GPU required for this recorded training protocol')
        torch.set_num_threads(16)
        sets = {'train': list(read_rows(OUT / 'train.jsonl')), **{name: list(read_rows(path)) for name, path in calibration_paths().items()}}
        info = cache_teachers(tok, sets)
        train(tok, sets, info, cfg)
    export(tok)


if __name__ == '__main__':
    main()
