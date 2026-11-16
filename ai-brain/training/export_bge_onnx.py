"""Export BAAI/bge-small-en-v1.5 (MIT) to ONNX opset 17 + dynamic per-channel int8 for the ai-brain RAG engine.

Output: ai-brain/models/bge_small/{model_int8.onnx, tokenizer.json}. The graph returns the
L2-normalised CLS embedding. Parity vs the fp32 torch model is printed on real eval texts.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import onnx
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai-brain"))
from rag_engine import OnnxEmbedder, canonical  # noqa: E402


class ClsEmbed(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask, token_type_ids):
        cls = self.model(input_ids=input_ids, attention_mask=attention_mask,
                         token_type_ids=token_type_ids).last_hidden_state[:, 0]
        return torch.nn.functional.normalize(cls, dim=-1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default=str(ROOT / "build-check/students/bge_small"))
    ap.add_argument("--out", default=str(ROOT / "ai-brain/models/bge_small"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(args.src)
    # SDPA traces the padding-mask construction as constants (fp32 parity 0.95); eager exports cleanly.
    model = ClsEmbed(AutoModel.from_pretrained(args.src, attn_implementation="eager").eval())
    enc = tok(["warm up text with several tokens here", "x"], padding=True, return_tensors="pt")
    fp32 = out / "model_fp32.onnx"
    torch.onnx.export(model, (enc["input_ids"], enc["attention_mask"], enc["token_type_ids"]), str(fp32),
                      input_names=["input_ids", "attention_mask", "token_type_ids"], output_names=["embedding"],
                      dynamic_axes={n: {0: "batch", 1: "seq"} for n in ("input_ids", "attention_mask", "token_type_ids")}
                      | {"embedding": {0: "batch"}}, opset_version=17, dynamo=False)
    m = onnx.load(str(fp32))
    m.ir_version = min(m.ir_version, 8)
    onnx.save(m, str(fp32))
    quantize_dynamic(str(fp32), str(out / "model_int8.onnx"), weight_type=QuantType.QInt8, per_channel=True)
    fp32.unlink()
    shutil.copy(Path(args.src) / "tokenizer.json", out / "tokenizer.json")

    rows = [json.loads(l) for l in (ROOT / "datasets/new_custom_datasets/out/rag_eval/rag_eval.jsonl").open(encoding="utf-8")]
    texts = [canonical(r["text"]) for r in rows[::10]]
    onnx_vecs = torch.tensor(OnnxEmbedder(out)(texts))
    reference = ClsEmbed(AutoModel.from_pretrained(args.src).eval())
    with torch.inference_mode():
        ref = torch.cat([reference(**tok([t], truncation=True, max_length=256, return_tensors="pt")) for t in texts])
    cos = (onnx_vecs * ref).sum(-1)
    print(json.dumps({"texts": len(texts), "int8_vs_fp32_cosine_mean": round(cos.mean().item(), 5),
                      "min": round(cos.min().item(), 5),
                      "model_bytes": (out / "model_int8.onnx").stat().st_size}))


if __name__ == "__main__":
    main()
