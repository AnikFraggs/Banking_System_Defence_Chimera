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
python -m chimera_datasets fetch spml           # or: fetch all (continues past failures)   (HF_TOKEN for gated sets; kaggle.json for Kaggle)
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

"Checked" means the dataset page was opened (2026-11-13 for the rows added in this version). A blank licence means the
page does not state one. The training spec document lists the same sets with roles and model parameters.

| Key | Role | Where | Licence | Notes |
|---|---|---|---|---|
| `spml` | External test | HF `reshabhs/SPML_Chatbot_Prompt_Injection` | MIT | Checked earlier. Graded `Degree` severity |
| `qualifire_bench` | External test | HF `rogue-security/prompt-injections-benchmark` | CC BY-NC 4.0 | Checked. 5,000 rows, test split only, labels jailbreak / benign |
| `yanismiraoui_pi` | External test, recall only | HF `yanismiraoui/prompt_injections` | Apache-2.0 | Checked. 1,034 rows, 7 languages, no label column (all assumed injections) |
| `notinject` | External test, over-defense | HF `leolee99/NotInject` | MIT | Checked 2026-11-14. 339 benign sentences with trigger words; columns prompt/word_list/category |
| `xtram1_safeguard` | Train | HF `xTRam1/safe-guard-prompt-injection` | Not stated | Checked. Synthetic (GPT-3.5-turbo). Label direction not stated: run `inspect` |
| `jayavibhav_safety` | Train (sample) | HF `jayavibhav/prompt-injection-safety` | Not stated | Commit page only: columns and licence unknown. `harmful` rows are skipped |
| `banking77` | Train (benign) and false-positive test | HF `PolyAI/banking77` | CC BY 4.0 | Checked. 13,083 benign banking queries; every row labelled 0 |
| `deepset_pi` | Sanity only (off) | HF `deepset/prompt-injections` | Apache-2.0 | Checked. 662 rows, labels undefined on the card, HiddenLayer: use with caution |
| `codesagar_v3` | Off | HF `codesagar/malicious-llm-prompts-v3` | Not stated | Aggregates other sets; use the originals instead |
| `web_attack` | Test the SQLi/XSS scanner | HF `YangYang-Research/web-attack-detection` | MIT | Checked. Columns not listed: run `inspect`. Not for the semantic guard |
| `creditcard_ulb` | Card model | Kaggle `mlg-ulb/creditcardfraud` | DbCL 1.0 (per Amazon's benchmark) | Kaggle page not opened. About 0.18% fraud |
| `ieee_cis` | Second card model | Kaggle competition `ieee-fraud-detection` | Competition rules | Kaggle page not opened. About 3.5% fraud |
| `paysim`, `baf` | Simulated wire / account opening | Kaggle | Check pages | Not opened this session |
| `cicids2017` | Reference only | HF `rdpahalavan/CIC-IDS2017` | Apache-2.0 on HF | Network flows; not wired in |
| `mendeley_sqli`, `mendeley_xss` | Off | Mendeley Data (manual download) | See page | Not checked |
| `hinglish_scam`, `shade63_scam`, `emunah_fraud_messages` | Listed only | HF | CC BY 4.0 / unclear / unstated | Scam-message text (Indian context). Not injection data; schemas unverified |
| `llmail_inject` | Listed only | HF `microsoft/llmail-inject-challenge` | MIT | 2.45 GB real adaptive attacks; schema unchecked |
| `cmu_keystroke`, `balabit_mouse` | Listed only (L5) | roymaxion.github.io; GitHub | CC-BY-ND 2.0; check | Typist/user identity, not bot detection |
| `ibm_aml` | Listed only | Kaggle `ealtman2019/ibm-transactions-for-anti-money-laundering-aml` | CDLA-Sharing-1.0 | Graph features. Columns unverified |
| `ijr_indic` | Listed only | arXiv 2602.16832 | Unknown | 45k prompts, 12 languages; no download link found |

If a fetch fails or a column is missing, the id or mapping is the first thing to suspect. `fetch all` keeps going and
lists failures at the end; `build` skips a source whose columns it cannot find and prints why.
Sources whose label is constant by design (`banking77`, `yanismiraoui_pi`, `notinject`) use `const_label` and are
exempt from the one-class warning in `catalog.py`; they still count in the length and non-ASCII artifact checks.
Read each licence before redistributing anything; this module keeps data in `raw/` and records a `MANIFEST.json`.

## What public data can and cannot test

| CHIMERA ring | Real public data? | What to do |
|---|---|---|
| L1 IP reputation | Not for your logic | Test against a real blocklist snapshot you download and date-stamp, plus unit tests |
| L2 role + status | No | Deterministic tests: every role x action pair, escalation attempts, property tests |
| L3 purpose | No | Same: declared-purpose vs payload mismatch cases, written by you, reviewed by someone else |
| **L4 injection and leak** | **Yes** | This module |
| L5 human verification | Partly (identity, not bots) | CMU keystroke and Balabit mouse data test typist/user identity. No public bot-vs-human set was found: record your own |
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

`python tests/test_module.py` (standard library only, 10 tests). The tests use made-up rows to check the plumbing: dedup,
conflicts, held-out handling, determinism, no payload alteration, constant-label sources, skipped sources, scoring with
missing predictions.
