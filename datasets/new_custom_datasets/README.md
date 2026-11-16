# chimera_datasets: real-data evaluation module for CHIMERA

Replaces `generate_datasets.py` as the source of test numbers. It fetches public labeled data, normalizes it,
removes duplicates and label conflicts, builds splits that cannot leak, and scores a detector's decisions with
confidence intervals.

Status: the code is tested (9 unit tests, plus an end-to-end run on small stand-in files shaped like the dataset
cards). **No real dataset has been downloaded or run through it yet.** Hugging Face and Kaggle were not reachable from
the build environment. The first thing to do on your machine is `fetch` then `inspect`.

## Why the synthetic files gave misleading results

Read directly from `generate_datasets.py`:

1. **The IP separates the classes perfectly.** Every malicious row gets `45.x.x.x`, every benign row `192.168.x.x`.
   L1 scoring 100% on this tests nothing.
2. **Severity is a label leak.** Benign is always `0.0`, malicious is random in 6.5-10. A severity correlation
   computed on this data mostly measures the benign/malicious gap, not calibration.
3. **Tiny effective sample size.** Each 2,000-row file draws from 4-6 benign and 4-6 malicious strings, so a file
   holds only 8-10 distinct payloads. The row count is 2,000 but the independent sample is about ten.
4. **`role` and `purpose` are random** and unrelated to the label, so L2 and L3 get no real signal either.

Any detector, including one that reads only the IP, can reach 100% on data like this. A perfect score here is not evidence.

## Quick start (on your machine)

```
pip install -r requirements.txt
python -m chimera_datasets list                 # sources, licence notes, what was and was not verified
python -m chimera_datasets fetch spml           # or: fetch all   (HF_TOKEN for gated sets; kaggle.json for Kaggle)
python -m chimera_datasets inspect web_attack   # PRINT THE COLUMNS AND LABEL VALUES. Fix catalog.py if they differ.
python -m chimera_datasets build                # writes out/text_{train,dev,test,external_test}.csv + BUILD_REPORT.md
python -m chimera_datasets tabular creditcard_ulb   # time-ordered split for the fraud gate
python -m chimera_datasets score out/text_test.csv my_predictions.csv
```

`my_predictions.csv` needs columns `id,pred`. `id` is in every split file. `pred` is 0/1 or an action name
(BLOCK, CHALLENGE, QUARANTINE, VAULTED, REMEDIATED count as detected; ALLOW as not).
`--treat-remediated-as-allowed` is the stricter reading.

The first six columns of each split CSV match the old generator (`label,payload,severity,role,purpose,ip`), so your
existing Java loader should read them. `role`, `purpose` and `ip` are **empty**: public data does not have them.

## Sources

| Key | Track | Where | Licence | Verified 2026-11-09 |
|---|---|---|---|---|
| `spml` | L4 prompt injection, held out | HF `reshabhs/SPML_Chatbot_Prompt_Injection` | MIT | Page opened. Label column `Prompt Injection`, graded `Degree`. The other label value is not defined on the page |
| `codesagar_v3` | L4 prompt injection | HF `codesagar/malicious-llm-prompts-v3` | Not stated | Page opened. 8,760 rows. Aggregates other sets, so overlaps are expected |
| `web_attack` | L4 SQLi, XSS, command injection, LFI | HF `YangYang-Research/web-attack-detection` | MIT | Page opened. 625,904 rows. **Column names not listed**; meaning of label 1 assumed |
| `mendeley_sqli`, `mendeley_xss` | L4 web payloads | data.mendeley.com (manual download) | See page | Titles seen in search only. Off by default |
| `deepset_pi` | L4 prompt injection | HF `deepset/prompt-injections` | Check page | Not checked. Off by default; already inside `codesagar_v3` |
| `creditcard_ulb` | Fraud gate (card) | Kaggle `mlg-ulb/creditcardfraud` | Check page | Not checked (you already use it) |
| `paysim` | Fraud gate (simulated wire) | Kaggle `ealaxi/paysim1` | Check page | Not checked. Synthetic |
| `baf` | Fraud gate (account opening) | Kaggle `sgpjesus/bank-account-fraud-dataset-neurips-2022` | Read repo LICENSE | Link confirmed on the Feedzai GitHub page. Column names from memory |
| `ieee_cis` | Fraud gate (card, e-commerce) | Kaggle competition `ieee-fraud-detection` | Competition rules | Not checked. Accept the rules on Kaggle first |
| `cicids2017` | Network IDS, reference only | HF `rdpahalavan/CIC-IDS2017` | Apache-2.0 on HF; original UNB terms apply | Page opened. Not wired in: it targets flow-level intrusion detection, not CHIMERA's L1 IP-reputation ring |

"Not checked" means the id came from memory. If a fetch fails or a column is missing, the id or mapping is the first thing to suspect.
Read each licence before redistributing anything; this module keeps data in `raw/` and records a `MANIFEST.json`.

## What public data can and cannot test

| CHIMERA ring | Real public data? | What to do |
|---|---|---|
| L1 IP reputation | Not for your logic | Test against a real blocklist snapshot you download and date-stamp, plus unit tests |
| L2 role + status | No | Deterministic tests: every role x action pair, escalation attempts, property tests |
| L3 purpose | No | Same: declared-purpose vs payload mismatch cases, written by you, reviewed by someone else |
| **L4 injection and leak** | **Yes** | This module |
| L5 human verification | Not verified in this session | Need keystroke/mouse datasets: source and check them before claiming anything |
| Fraud gate | Yes (tabular track) | One model per rail. Never mix card, wire and account-opening data |

Severity calibration (the Pearson r) can only be computed on rows that carry a real severity. SPML's `Degree` is the
only one in this catalog. Otherwise drop that metric rather than invent labels.

## Rules built into the build

- **Payloads are stored untouched.** Zero-width and bidi characters stay, because L4 must see them. Only the dedup hash is canonicalized (NFKC, invisibles removed, casefolded).
- **Cross-source dedup.** If the same canonical text appears twice with the same label, one copy is kept; a held-out copy wins so the external test stays external. With different labels, **all copies are dropped** and listed in the report.
- **Splits are by hash, not by row order**, so one text can never land in two splits. Held-out sources go to `external_test` whole.
- **`SPLIT_LOCK.json`** records sha256 for every output file. Tune on train and dev. Run test once.
- **Artifact checks** warn when payload length or non-ASCII share alone separates the classes (AUC at or above 0.80), or when a source is almost one class. These are cheap checks, not proof the data is clean.
- **Scoring reports Wilson 95% intervals**, per source and overall.
- Missing predictions are reported loudly and excluded; they are never counted as correct.

## What to claim, and what not to

- Report recall and false-positive rate **on `external_test`** and quote the interval. A model that scores 99% on a split of the same sources it was tuned on has told you little.
- Keep a **benign set from realistic banking traffic**. Public benign text is mostly generic chat, which is easy to tell from attacks. Your false-positive rate on real banking requests (with permission, scrubbed of personal data) is the number that matters.
- Attacks that someone else wrote *after* your detectors were frozen are worth more than any public dataset.
- Do not open the CSVs in Excel: attack strings can start with `=`, `+`, `-` or `@` and be treated as formulas. Use a text editor or pandas.
- Use these payloads only against your own sandbox.

## Adding a source

Add a `Source(...)` to `catalog.py`. For a text source set `cols` if the names are unusual. For a manual download, place
the CSV or JSONL in `raw/<key>/` and run `inspect <key>` first. For a tabular source set `time`, `label` and `file`.

## Tests

`python tests/test_module.py` (standard library only). The tests use made-up rows to check the plumbing: dedup,
conflicts, held-out handling, determinism, no payload alteration, scoring with missing predictions.
