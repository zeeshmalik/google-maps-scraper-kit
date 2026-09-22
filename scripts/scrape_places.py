#!/usr/bin/env python3
"""Scrape the same business type across MANY places (e.g. every UK town) — resumable.

Google Maps returns at most ~120 results per search, so one search for "grocery stores in UK"
can never be complete. This runs one scrape.py job per place (with several search terms each),
saves a CSV per place, skips places already done if you re-run it, and merges everything
into one de-duplicated file at the end.

    python3 scripts/scrape_places.py examples/uk-places.txt \
        --terms "supermarket,grocery store,convenience store" --country "UK" \
        --out-dir out/uk-grocery --sheet "UK grocery"

Extra flags after "--" go straight to scrape.py, e.g.  -- --no-email --depth 8
Standard library only.
"""
import argparse, csv, glob, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def merge(out_dir):
    """Combine every per-place CSV into all.csv, de-duplicated on title + address."""
    seen, rows, fields = set(), [], []
    for path in sorted(glob.glob(os.path.join(out_dir, "places", "*.csv"))):
        with open(path, newline="") as f:
            rd = csv.DictReader(f)
            for h in rd.fieldnames or []:
                if h not in fields:
                    fields.append(h)
            for r in rd:
                key = (r.get("title", "").strip().lower(), r.get("address", "").strip().lower())
                if key not in seen:
                    seen.add(key); rows.append(r)
    out = os.path.join(out_dir, "all.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields or ["title"], extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    return out, len(rows)


def main():
    argv = sys.argv[1:]
    passthrough = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv

    ap = argparse.ArgumentParser(description="Scrape one business type across many places (resumable).")
    ap.add_argument("places_file", help="one place per line, e.g. examples/uk-places.txt")
    ap.add_argument("--terms", default="supermarket,grocery store,convenience store",
                    help="comma-separated search terms run in EACH place")
    ap.add_argument("--country", default="", help='appended to each place, e.g. "UK"')
    ap.add_argument("--out-dir", default="out/places-run", help="where CSVs + progress are kept")
    ap.add_argument("--sheet", metavar="TAB", help="also append every place's results to this Google Sheets tab")
    ap.add_argument("--pause", type=int, default=30, help="seconds to wait between places (be gentle)")
    ap.add_argument("--limit", type=int, default=0, help="only do the next N places this run (0 = all)")
    a = ap.parse_args(argv)

    with open(a.places_file) as f:
        places = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    terms = [t.strip() for t in a.terms.split(",") if t.strip()]
    os.makedirs(os.path.join(a.out_dir, "places"), exist_ok=True)
    done_path = os.path.join(a.out_dir, "done.txt")
    done = set()
    if os.path.exists(done_path):
        with open(done_path) as f:
            done = {l.strip() for l in f if l.strip()}

    todo = [p for p in places if p not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"▶ {len(places)} places, {len(done)} already done, {len(todo)} to run now. Terms: {', '.join(terms)}")
    print("⚠️  Long runs like this can get your IP temporarily rate-limited by Google. It pauses between")
    print("    places and stops after 3 failures in a row; for full-country runs, proxies help.\n")

    fails = 0
    for i, place in enumerate(todo, 1):
        where = f"{place}, {a.country}" if a.country else place
        out = os.path.join(a.out_dir, "places", slug(place) + ".csv")
        cmd = [sys.executable, os.path.join(HERE, "scrape.py"), f"{terms[0]} in {where}"]
        for t in terms[1:]:
            cmd += ["--keyword", f"{t} in {where}"]
        cmd += ["--city", where, "--out", out]
        if a.sheet:
            cmd.append(f"--sheet={a.sheet}")
        cmd += passthrough
        print(f"━━ [{i}/{len(todo)}] {where}", flush=True)
        ok = subprocess.run(cmd).returncode == 0
        if ok:
            fails = 0
            with open(done_path, "a") as f:
                f.write(place + "\n")
        else:
            fails += 1
            print(f"  ✗ {place} failed — it will be retried next run.")
            if fails >= 3:
                print("\n✗ 3 failures in a row — probably rate-limited. Wait an hour (or add proxies) and")
                print("  re-run the same command; finished places are skipped.")
                break
        if i < len(todo):
            time.sleep(a.pause)

    out, n = merge(a.out_dir)
    print(f"\n✓ Merged {n} unique businesses → {out}")


if __name__ == "__main__":
    main()
