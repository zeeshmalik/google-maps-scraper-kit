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

Independent shops only: add --exclude-chains (drops names matching examples/uk-chains.txt).

Managing the queue (the places file is the queue, out-dir/done.txt is the progress):
    --status                       show done / pending counts and what runs next
    --add "Place" ["Place" ...]    append new areas to the places file (skips duplicates)
    --mark-done "Place" [...]      record areas you already scraped elsewhere so they are skipped
Standard library only.
"""
import argparse, csv, glob, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def load_chains(path):
    """Chain names -> one case-insensitive whole-word regex (None if the file is empty)."""
    with open(path) as f:
        names = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if not names:
        return None
    alts = "|".join(re.escape(n).replace("'", "['\u2019]?") for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alts})(?![A-Za-z0-9])", re.I)


def drop_chains(path, chain_re):
    """Rewrite one CSV without chain-named rows; return how many were removed."""
    with open(path, newline="") as f:
        rd = csv.DictReader(f)
        fields, rows = rd.fieldnames or [], list(rd)
    keep = [r for r in rows if not chain_re.search(r.get("title", ""))]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields or ["title"])
        w.writeheader(); w.writerows(keep)
    return len(rows) - len(keep)


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


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
    ap.add_argument("--exclude-chains", nargs="?", const=os.path.join(HERE, "..", "examples", "uk-chains.txt"),
                    metavar="FILE", help="drop chain/franchise names (default list: examples/uk-chains.txt)")
    ap.add_argument("--status", action="store_true", help="show queue progress and exit")
    ap.add_argument("--add", nargs="+", metavar="PLACE", help="append places to the places file and exit")
    ap.add_argument("--mark-done", nargs="+", metavar="PLACE", help="mark places as already scraped and exit")
    a = ap.parse_args(argv)

    os.makedirs(os.path.join(a.out_dir, "places"), exist_ok=True)
    done_path = os.path.join(a.out_dir, "done.txt")

    if a.add:
        have = {p.lower() for p in read_lines(a.places_file)}
        new = [p for p in a.add if p.lower() not in have]
        with open(a.places_file, "a") as f:
            f.writelines(p + "\n" for p in new)
        print(f"✓ added {len(new)} place(s) to {a.places_file}" + (f": {', '.join(new)}" if new else " (all already queued)"))
        return
    if a.mark_done:
        have = set(read_lines(done_path))
        new = [p for p in a.mark_done if p not in have]
        with open(done_path, "a") as f:
            f.writelines(p + "\n" for p in new)
        print(f"✓ marked {len(new)} place(s) done in {done_path}")
        return

    places = read_lines(a.places_file)
    terms = [t.strip() for t in a.terms.split(",") if t.strip()]
    done = set(read_lines(done_path))
    chain_re = load_chains(a.exclude_chains) if a.exclude_chains else None

    todo = [p for p in places if p not in done]
    if a.status:
        print(f"{len(places)} places in {a.places_file}: {len(places) - len(todo)} done, {len(todo)} pending")
        if todo:
            print("next up: " + ", ".join(todo[:10]) + (" …" if len(todo) > 10 else ""))
        return
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
            if chain_re and os.path.exists(out):
                print(f"  removed {drop_chains(out, chain_re)} chain/franchise listings")
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
