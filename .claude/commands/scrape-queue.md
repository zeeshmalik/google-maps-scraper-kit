---
description: Region queue — scrape UK areas (city, then surrounding towns) into one de-chained CSV per region, resumable
argument-hint: [--only <region-slug>] [--target 1300] [--status]
---
The user wants a **region-by-region queue** of independent (non-chain) grocery / convenience shops. Input: **$ARGUMENTS**

Use the `google-maps-scraper` skill rules (emails on, warn-don't-block, PII). Then:

1. Ensure the scraper is up (`curl -s http://localhost:8080/api/v1/jobs`; `docker compose up -d` if not).
2. Show progress first: `python3 scripts/uk_queue.py --status`.
3. Warn ONCE: this is a long, high-volume run (many towns × 12 keywords) — it can get the IP temporarily
   rate-limited by Google; suggest `--proxies`. Then proceed.
4. To run in chunks add `--max-areas N` (N towns per run; re-run for the next chunk).
   Run in the BACKGROUND (`run_in_background: true`): `python3 scripts/uk_queue.py $ARGUMENTS`.
   Regions/towns/keywords live in `examples/uk-regions-remaining.json` (edit to add towns).
   Each region → `output/uk-independent-shops/<region>.csv`, filled area by area until ~1300 (cap 1500).
5. **Continue** = re-run the same command; finished towns are skipped and in-flight jobs re-attached.
6. Chains (Tesco, Co-op, Spar, Londis, Premier, forecourts, wholesalers, any name at 4+ sites) are dropped.
   `--keep-symbol-groups` keeps franchise fascias; `--exclude-dir <folder>` skips shops already in old CSVs.
7. Report per-region row counts + CSV paths; show only a few sample rows.
