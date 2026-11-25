# MuleWatch research pipeline

A pipeline for studying money-mule account advertising on public Telegram channels: collection,
PII redaction, annotation, leakage-aware splits, baselines, robustness to evasion, and seller-network
analysis. It is kept apart from the MuleWatch app: nothing here imports or changes `backend/`,
`frontend/` or `forum/`, and it has its own requirements, `.env` and git-ignored data store.

```
research/
  collect/telegram_public.py   read-only Telethon collector (public broadcast channels only)
  config/channels.yaml         the channels to read, each with the reason it was included
  pii/redact.py                mask phones, UPI IDs, accounts, cards, IDs, e-mails, URLs, handles; keyed hashes
  annotate/                    Label Studio config, batch export, import, Cohen's kappa
  data/splits.py               time, channel and time+channel splits, duplicate-leak removal
  models/                      TF-IDF+LR, MuRIL, IndicBERT, XLM-R (HF Trainer), LLM zero/few-shot
    configs/*.yaml             one config per baseline
  robustness/attacks.py        character substitution, transliteration, emoji swap, LLM paraphrase
  graph/build.py               entity graph, connected components, Louvain, Gephi export
  results/                     CSV + LaTeX tables (committed)
  store/                       raw and derived data, sessions, graphs (git-ignored, never committed)
  tests/                       pytest
  tools/                       synthetic data + end-to-end smoke test
```

## Setup

```bash
cd research
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# MuRIL / IndicBERT / XLM-R only (GPU recommended):
.venv/bin/pip install -r requirements-transformers.txt
sudo apt install tesseract-ocr tesseract-ocr-hin          # OCR (hin+eng)
cp .env.example .env                                      # fill in, never commit
.venv/bin/python -m pytest                                # 104 tests
tools/smoke.sh                                            # all stages on synthetic data, in a temp dir
```

`.env` holds the Telegram API id/hash (from my.telegram.org; use a dedicated research account), the
hash salt (`python -c "import secrets; print(secrets.token_hex(32))"`), the LLM endpoint and the
optional Label Studio key. `research/.gitignore` excludes `.env`, `*.session` and `store/`.

All commands below run from `research/` with `.venv/bin/python` (written `python` here).

## Pipeline

**1. Collect.** List channels in `config/channels.yaml`, then:

```bash
python -m collect.telegram_public --config config/channels.yaml --out store/raw/telegram.jsonl
```

Each post is stored with its post id, channel, date (UTC), text, media type, OCR text of the image
(Tesseract `hin+eng`), views, forwards and whether it was edited. Reruns fetch only new posts
(`store/raw/telegram_state.json`). Requests are limited to `requests_per_minute` (default 20, 60 at
most), with a pause between channels; FloodWaits up to 5 minutes are slept through, longer ones stop
that channel until the next run.

**1a. Discover channels (optional).** Finds candidate channels for `channels.yaml`, read-only:

```bash
python -m collect.discover_channels --login            # once, in a terminal (phone + code)
python -m collect.discover_channels --dry-run          # the plan, no requests
python -m collect.discover_channels -v                 # run daily until it reports "finished"
```

It searches Telegram's public directory for the keywords in `config/discovery_keywords.yaml` (English,
Hinglish, Hindi, crypto, Rajasthan places) and the seeds in `config/discovery_seeds.yaml` plus
`store/discovery_seeds.yaml`. It reads the last 20 posts of each new public channel and keeps only
aggregates: score, category, Rajasthan geo score, language mix, the share of posts with a contact (counted,
never stored), subscribers and last post. Results go to `config/channels.discovered.{yaml,csv}`
(git-ignored), every entry with `approved: false`. The collector reads only the entries you set to
`approved: true` that are labelled `likely_fraud` or `likely_legit`.

It goes easy on Telegram on purpose:
- 6 requests a minute, and at most 300 a day across runs. Progress is saved after every channel, so the
  next day's run continues where the last one stopped and nothing is read twice.
- A FloodWait longer than 60 s pauses discovery until the next run. A shorter one is waited out, and
  the pace is halved for the rest of the run.
- Seeds are looked up in the session cache before any username lookup is sent.
- At most 15 new channels are scored per keyword.
- Rajasthan searches start with the main districts.
- Only one Telegram job (discovery or collector) can run at a time.

Use the official API with one research account. Don't use extra accounts, proxies or timing tricks to get
around Telegram's limits.

**2. Redact.**

```bash
python -m pii.redact store/raw/telegram.jsonl --out store/redacted/posts.jsonl [--hash-channels]
```

Identifiers become placeholders (`[PHONE]`, `[UPI]`, `[ACCOUNT]`, `[CARD]`, `[ID]`, `[EMAIL]`, `[URL]`,
`[HANDLE]`), and `entities` keeps a keyed hash for each one: HMAC-SHA256 with the secret salt over the
normalised value. Because values are normalised first, `+91 98290 41736`, `098290-41736`, `९८२९०४१७३६`
and `wa.me/919829041736` get the same hash, and so do `@seller` and `t.me/seller`. Not masked: IFSC codes
(a branch, not a person), prices, the payment app of a UPI ID (`meta.psp`, e.g. `ybl`), and link/e-mail
domains. After masking, the CLI runs the detectors again on the output and warns if anything still looks
like an identifier. Every post also gets a language tag (`en`, `hi`, `hinglish`, `mixed`).

**3. Annotate.** The classes and span labels are defined in `common/labels.py`:

| class | meaning |
|---|---|
| `mule_account_sale` | sells or rents bank accounts, current/savings accounts, full kits |
| `account_holder_recruitment` | asks people to hand over or "rent" their own account for commission |
| `card_sale` | sells ATM / debit / credit cards or card details |
| `kyc_fraud` | fake KYC, rented identity documents, accounts opened on someone else's papers |
| `easy_money_lure` | easy-money / task / part-time job offers that lead to account misuse |
| `awareness` | warns about, reports on or explains mule-account fraud |
| `benign` | everything else, including legitimate financial posts |

Spans: `price`, `bank`, `account_type`, `contact`, `upi`. These classes follow the categories the app
already uses. They are a proposal: if you change them, edit `common/labels.py` and run
`python -m annotate.label_config > annotate/label_config.xml` (a test checks that the two match).

```bash
python -m annotate.export store/redacted/posts.jsonl --annotators a1,a2 --batch-size 200 --overlap 0.25
#   -> store/annotation_batches/batch_001_a1.json, batch_001_a2.json, ...  (import into Label Studio,
#      config: annotate/label_config.xml; or add --push <project ids>)
python -m annotate.importer store/ls_exports/*.json --annotator-map 12=a1,13=a2   # or --pull <project ids>
python -m annotate.agreement store/annotations/annotations.jsonl
```

Each batch has a shared slice that both annotators label, and the rest is split between them. Only the
language is pre-filled; the class is not, so annotators are not anchored on a model's guess. The importer
writes `gold.jsonl` (labels both annotators agreed on, single-annotated labels, and adjudicated ones) and
`conflicts.jsonl`. Disagreements stay out of gold until they are resolved in an adjudication CSV
(`--adjudicated post_id,label`). Agreement tables: Cohen's kappa over the 7 classes and over suspicious
vs not, per-class kappa, observed agreement, exact-match span F1, and a confusion matrix.

**4. Split.**

```bash
python -m data.splits --posts store/redacted/posts.jsonl --gold store/annotations/gold.jsonl
```

* `time`: train on the oldest posts, dev on the next, test on the newest.
* `channel`: test channels never appear in train.
* `time_channel`: train on seen channels before t1, dev on seen channels between t1 and t2, test on
  unseen channels from t2 on. Newer posts from seen channels are kept as `test_seen_channels`, so
  temporal drift and channel drift can be measured separately.

Sellers copy-paste across channels, so a dev/test post whose normalised text (case, digits, punctuation,
emoji and placeholders ignored) also appears in train is removed. The number removed is reported.

**5. Baselines.**

```bash
python -m models.run --config models/configs/tfidf_lr.yaml --split time_channel
python -m models.run --config models/configs/muril.yaml     --split time_channel   # 3 seeds by default
python -m models.run --config models/configs/indicbert.yaml --split time_channel
python -m models.run --config models/configs/xlmr.yaml      --split time_channel
python -m models.run --config models/configs/llm_zeroshot.yaml --split time_channel  # needs vLLM/Ollama
python -m models.run --config models/configs/llm_fewshot.yaml  --split time_channel
```

The input is the post text plus `[IMAGE TEXT] <ocr>`. Each run is scored on every test set of the split.
Reported: macro-F1 (mean ± std over seeds), per-class F1, per-language macro-F1, suspicious-vs-not F1,
throughput (ms/post), single-post p50/p95 latency, and USD per 1,000 posts. Cost is wall-clock time times
the hardware price in the config, plus token cost when the config prices tokens. Set `cost.usd_per_hour`
to your actual hardware. For an LLM, invalid answers fall back to `benign` and are counted.
IndicBERT uses `ai4bharat/IndicBERTv2-MLM-only`; for the original ALBERT model, set
`model_name: ai4bharat/indic-bert`.

**6. Robustness.**

```bash
python -m robustness.attacks --config models/configs/tfidf_lr.yaml --split time_channel \
    --attacks char,translit,emoji,paraphrase [--only-suspicious]
```

The model is trained once, then scored on the clean test set and on each perturbed copy.
`--only-suspicious` perturbs only suspicious posts, which is what an evading seller would do.
Paraphrases come from the LLM endpoint in `--paraphrase-config` and are cached. A paraphrase that loses
or invents a placeholder is discarded, and the original post is kept.

**7. Graph.**

```bash
python -m graph.build store/redacted/posts.jsonl --labels store/annotations/gold.jsonl [--with-channels]
```

Identifiers that appear in the same post are linked. Masked card numbers are not used for linking, and
`--max-posts-per-entity` drops hubs such as an official helpline. The output is a GEXF file for Gephi
plus node and edge CSVs in `store/graph/`, and summary, component-size and top-cluster tables in
`results/`.

## Results

| file | from |
|---|---|
| `agreement`, `agreement_per_class`, `agreement_confusion_*` | annotate.agreement |
| `splits_summary` | data.splits |
| `main_results`, `per_class_f1`, `per_language_f1`, `runs/*.json` | models.run / models.report |
| `robustness` | robustness.attacks |
| `graph_summary`, `graph_components`, `graph_top_clusters` | graph.build |

Each table is written as `.csv` and as a booktabs `.tex`. `results/` holds only aggregates; per-post
predictions go to `store/predictions/`. Never commit numbers from `tools/synthetic.py`: that data is
template-generated and only exists to check that the stages fit together.

## Ethics notes

Before any collection, get approval from your institution's ethics committee (or IRB) and record it here.
The notes below describe the safeguards the code enforces and the ones it relies on you to follow.

**What is collected.** Only public broadcast channels with a public @username. The collector refuses
invite links, private channels, groups and supergroups. Group messages are written by ordinary members,
not by an advertiser, so groups are left out even when public. The Telegram client blocks join, invite,
send, forward, react, vote, start-bot, add-contact, import-contact and mark-as-read requests, so the
research account cannot interact with anyone even by mistake. There is no buying, test messages or
undercover contact with sellers. Each channel in `channels.yaml` records why it was included.

**Minimisation.** Images are downloaded into memory, OCR'd and discarded; no media is stored. Raw
posts are written owner-readable only (`0600`) under `store/`, which git ignores. Redact as soon as
possible, give only redacted data to annotators, models and LLMs, and delete `store/raw/` once the
retention period in your approval ends.

**Pseudonymous, not anonymous.** The hashes link identifiers without storing them, but they are only
as safe as the salt. There are about 10^10 Indian mobile numbers, so an unsalted hash could be reversed
by trying them all. Keep `RESEARCH_HASH_SALT` secret, out of the repo and out of any released data.
Before releasing data, use `--hash-channels` and either drop the entity hashes or redo the redaction
with a fresh salt that is never shared. Redaction is regex-based and will miss some identifiers, for
example numbers written out in words or digits swapped for letters. Spot-check a sample by hand before
anything leaves the team.

**People in the data.** Many account holders are recruited students, workers or people in debt who
are victims as much as offenders. Report patterns and aggregates, not individuals. A cluster in the
entity graph is a lead, not proof that anyone committed a crime. Do not publish cluster details,
channel names or example posts that would let a reader find a specific person. The research data is
not used to take action against individuals. Anything passed to police goes through the app's case
workflow and its legal process, not straight from this pipeline. (In India, the research exemption in
the DPDP Act 2023 covers processing that is not used for decisions about specific individuals. Confirm
how it applies to you with your institution.)

**Third parties.** LLM baselines and paraphrasing default to a local endpoint (vLLM or Ollama). A
remote endpoint is refused unless the config sets `allow_remote: true`, and you should do that only if
sending redacted posts to that provider is covered by your approval. Label Studio should be
self-hosted.

**Dual use.** The robustness attacks are standard text perturbations, used to measure how detectors
degrade. Publish the F1 drops. Do not publish a corpus of perturbed real advertisements, which would
amount to a catalogue of ready-made evasive ads.

**Annotators.** Annotators see redacted text only. The content is fraud advertising rather than
graphic material, but annotators should be told what they will see, be able to skip any post, and
have the class guide (the hints in the Label Studio config) to hand.

## Known limits

* Language tags come from a heuristic until annotators correct them. Per-language scores use the
  corrected tags whenever annotators provided them.
* The HF fine-tuning runner (MuRIL / IndicBERT / XLM-R) has not been run yet: there was no GPU on the
  machine it was written on. Do one short run (`--seeds 13`, `epochs: 1`) before the full sweep. The LLM
  runner is tested against a mocked endpoint, not a real model.
* Duplicate-leak removal catches exact copies after normalisation, not paraphrased reposts.
