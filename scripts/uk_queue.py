#!/usr/bin/env python3
"""Region queue: scrape area-by-area (main city, then surrounding towns) into ONE CSV per region,
skipping chains. By default EVERY town in a region is scraped (no cap). Resumable.

    python3 scripts/uk_queue.py                       # run / CONTINUE the whole queue
    python3 scripts/uk_queue.py --only lincolnshire-independent-shops
    python3 scripts/uk_queue.py --status              # progress per region
    python3 scripts/uk_queue.py --rebuild             # re-filter saved raw data, no scraping
    python3 scripts/uk_queue.py --forever             # unattended: auto-wait out rate limits / restarts

Continue: progress lives in <out-dir>/state.json and raw results in <out-dir>/raw/. Just re-run the
same command after a stop/crash/reboot — finished areas are skipped and an in-flight job is re-attached
by its id instead of being scraped again.

Chains: big multiples, symbol-group fascias (Spar, Londis, Premier, Nisa…), forecourts and wholesalers
are dropped by name, plus any name that appears at 4+ addresses in the data (a chain we didn't list).
Use --keep-symbol-groups to keep independently-owned Spar/Londis/Premier-style franchise stores.
Standard library only (works on Windows/macOS/Linux).
"""
import argparse, csv, glob, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
try:  # Windows consoles (cp1252) can't print ✓/══ — replace instead of crashing
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass
BASE = os.environ.get("SCRAPER_BASE_URL", "http://localhost:8080")
UA = "google-maps-scraper-kit/1.0 (region queue)"
LEAD = ["title", "phone", "emails", "website", "category", "address", "review_rating", "review_count", "area"]

# ── Chain filter ──────────────────────────────────────────────────────────────
CHAINS = [  # national / multinational grocers, discounters, pharmacies, bakeries, forecourts, wholesale
    "tesco", "sainsbury", "asda", "morrisons", "aldi", "lidl", "waitrose", "marks & spencer", "marks and spencer",
    "m&s", "iceland", "the food warehouse", "co-op", "coop", "co-operative", "cooperative", "scotmid",
    "farmfoods", "heron foods", "b&m", "home bargains", "poundland", "poundstretcher", "pound bakery",
    "booths", "whole foods", "planet organic", "holland & barrett", "holland and barrett", "amazon fresh",
    "ocado", "getir", "gopuff", "jack's supermarket", "dunnes", "supervalu", "eurospar", "the range", "wilko",
    "boots", "superdrug", "lloyds pharmacy", "greggs", "subway", "mcdonald", "kfc", "costa", "starbucks",
    "shell", "bp", "esso", "texaco", "jet", "gulf", "applegreen", "circle k", "euro garages", "eg on the move",
    "mfg", "moto", "welcome break", "roadchef", "post office", "whsmith", "wh smith", "bargain booze",
    "wine rack", "majestic wine", "threshers", "booker", "bestway", "costco", "makro", "parfetts", "dhamecha",
    "united wholesale", "jd wholesale", "cooltrader", "jtf", "fulton's foods", "fultons foods", "card factory",
    "tgjones", "tg jones", "inpost", "amazon counter", "amazon locker", "collect+", "evri",
    "lifestyle express", "morrisons daily", "little waitrose", "sainsbury's local", "tesco express",
]
SYMBOL_GROUPS = [  # usually independently owned franchisees under a national brand
    "spar", "londis", "budgens", "costcutter", "nisa", "premier", "one stop", "best-one", "best one",
    "bestone", "family shopper", "day-today", "day today", "mccolls", "mccoll's", "martin mccoll",
    "select convenience", "centra", "mace", "go local", "simply fresh", "keystore", "key store", "today's",
    "todays", "vivo", "gala", "select & save", "lifestyle", "local plus", "your local", "go local extra",
]
FOODISH = ["grocery", "convenience", "supermarket", "market", "newsstand", "magazine", "off licence", "off-licence", "liquor", "wine",
           "beer", "food", "newsagent", "news agent", "delicatessen", "deli", "butcher", "halal", "tobacco",
           "organic", "fruit", "vegetable", "greengrocer", "produce", "general store", "variety store",
           "international", "asian", "polish", "african", "caribbean", "oriental", "chinese", "indian",
           "turkish", "middle eastern", "kosher", "latin", "european", "ethnic", "spice", "bangladeshi",
           "pakistani", "eastern european", "romanian", "lithuanian", "japanese", "korean", "thai", "filipino"]
UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I)


def _rx(words):
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower().replace("’", "'")).strip()


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def api(method, path, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(r, timeout=120) as resp:
        b = resp.read()
    return b if raw else json.loads(b or b"null")


def geocode(place, cache):
    if place in cache:
        return cache[place]
    q = urllib.parse.urlencode({"format": "json", "limit": 1, "countrycodes": "gb", "q": place})
    r = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + q, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            hits = json.loads(resp.read())
    except Exception as e:
        log(f"  geocode failed for {place}: {e}")
        hits = []
    time.sleep(1.1)  # Nominatim: max ~1 req/sec
    cache[place] = [hits[0]["lat"], hits[0]["lon"]] if hits else None
    return cache[place]


# ── State (atomic JSON writes so Ctrl-C / crashes never corrupt it) ───────────
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ── Filtering / building a region CSV ─────────────────────────────────────────
class Filter:
    def __init__(self, keep_symbol_groups, exclude_keys):
        self.chain_rx = _rx(CHAINS if keep_symbol_groups else CHAINS + SYMBOL_GROUPS)
        self.food_rx = _rx(FOODISH)
        # odd Google category but obviously a shop by name (e.g. "The Newsagents & Off Licence | Building")
        self.title_rx = _rx(["news", "newsagent", "newsagents", "off licence", "off license", "convenience",
                             "mini market", "minimarket", "mini mart", "supermarket", "grocer", "grocers",
                             "grocery", "food and wine", "food & wine", "food store", "stores", "store"])
        self.exclude = exclude_keys  # (name, postcode-ish) keys of shops already scraped elsewhere

    def reason(self, r):
        title, cat = r.get("title", ""), r.get("category", "")
        if not title:
            return "no name"
        if self.chain_rx.search(title.replace("’", "'")):
            return "chain"
        if cat and not self.food_rx.search(cat) and not self.title_rx.search(title):
            return "not grocery"
        if "permanently closed" in (r.get("status", "") or "").lower():
            return "closed"
        addr = r.get("address", "")
        if addr and not (UK_POSTCODE.search(addr) or "united kingdom" in addr.lower()):
            return "outside UK"
        if key(r) in self.exclude:
            return "already scraped"
        return None


def key(r):
    pc = UK_POSTCODE.search(r.get("address", "") or "")
    return (norm(r.get("title")), norm(pc.group(0)) if pc else norm(r.get("address"))[:40])


def ids(r):
    return {x for x in (r.get("place_id"), r.get("cid"), r.get("data_id")) if x} | {key(r)}


def read_raw(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_region(region, out_dir, flt, taken, cap):
    """Merge every raw area file of the region (in queue order) -> filtered, de-duped region CSV."""
    rows, seen, why = [], set(), {}
    name_count = {}
    raw_rows = []
    for area in region["areas"]:
        p = os.path.join(out_dir, "raw", region["slug"], slug(area) + ".csv")
        if os.path.exists(p):
            for r in read_raw(p):
                r["area"] = area
                raw_rows.append(r)
    for r in raw_rows:  # chain heuristic: same name at 4+ different addresses = chain
        name_count.setdefault(norm(r.get("title")), set()).add(key(r)[1])
    for r in raw_rows:
        rs = flt.reason(r)
        if not rs and len(name_count.get(norm(r.get("title")), ())) >= 4:
            rs = "chain (4+ sites)"
        k = ids(r)
        if not rs and (k & seen or k & taken):
            rs = "duplicate"
        if rs:
            why[rs] = why.get(rs, 0) + 1
            continue
        seen |= k
        rows.append({f: r.get(f, "") for f in LEAD})
        if cap and len(rows) >= cap:
            break
    with open(os.path.join(out_dir, region["slug"] + ".csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEAD)
        w.writeheader()
        w.writerows(rows)
    return rows, seen, why


def load_exclusions(folder):
    """CSV/XLSX-exported CSVs of areas you already scraped → keys to skip (needs title + address cols)."""
    keys = set()
    for p in glob.glob(os.path.join(folder, "**", "*.csv"), recursive=True):
        try:
            for r in read_raw(p):
                r = {k.lower().strip().lstrip("﻿"): v for k, v in r.items() if k}
                r["title"] = r.get("title") or r.get("name") or ""
                if r["title"]:
                    keys.add(key(r))
        except Exception as e:
            log(f"  skip exclusion file {p}: {e}")
    return keys


# ── Scraping one area (create or re-attach job, poll, download raw) ───────────
def run_area(region, area, cfg, a, state, geo_cache, state_path, geo_path):
    st = state["regions"][region["slug"]]
    job_id = st["pending"].get(area)
    if job_id:
        try:
            api("GET", f"/api/v1/jobs/{job_id}")
            log(f"  ↺ re-attaching to job {job_id[:8]} for {area}")
        except Exception:
            job_id = None  # job vanished (container reset) → re-create
    if not job_id:
        coords = geocode(f"{area}, {cfg.get('country', 'UK')}", geo_cache)
        save_json(geo_path, geo_cache)
        if not coords:
            log(f"  ✗ could not geocode {area} — skipping")
            return "skip"
        kws = [k.format(town=area) for k in cfg["keywords"]]
        body = {"name": f"{region['slug']}:{area}", "keywords": kws, "lang": "en", "zoom": 14,
                "lat": str(coords[0]), "lon": str(coords[1]), "fast_mode": False, "radius": a.radius,
                "depth": a.depth, "email": a.email, "max_time": a.max_time}
        if a.proxies:
            body["proxies"] = a.proxies
        job_id = api("POST", "/api/v1/jobs", body)["id"]
        st["pending"][area] = job_id
        save_json(state_path, state)
        log(f"  ▶ job {job_id[:8]} · {area} · {len(kws)} keywords · depth {a.depth}")
    deadline = time.time() + a.max_time + 900
    status = None
    while time.time() < deadline:
        try:
            status = api("GET", f"/api/v1/jobs/{job_id}").get("Status")
        except Exception as e:
            log(f"  (poll error: {e})")
        if status in ("ok", "failed"):
            break
        time.sleep(a.poll)
    if status != "ok":
        log(f"  ✗ {area}: job {status or 'timed out'}")
        st["pending"].pop(area, None)
        st["failed"][area] = st["failed"].get(area, 0) + 1
        save_json(state_path, state)
        return "failed"
    raw = api("GET", f"/api/v1/jobs/{job_id}/download", raw=True).decode("utf-8", "replace")
    d = os.path.join(a.out_dir, "raw", region["slug"])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, slug(area) + ".csv"), "w", encoding="utf-8", newline="") as f:
        f.write(raw)
    n = max(0, len(list(csv.DictReader(io.StringIO(raw)))))
    st["pending"].pop(area, None)
    st["done"][area] = n
    save_json(state_path, state)
    if not a.keep_jobs:
        try:
            api("DELETE", f"/api/v1/jobs/{job_id}", raw=True)
        except Exception:
            pass
    return n


class RateLimited(Exception):
    pass


def main():
    ap = argparse.ArgumentParser(description="Queue regions → one de-chained CSV per region (resumable).")
    ap.add_argument("--regions", default="examples/uk-regions-remaining.json")
    ap.add_argument("--out-dir", default="output/uk-independent-shops")
    ap.add_argument("--only", help="comma-separated region slugs to run (default: all, in file order)")
    ap.add_argument("--target", type=int, default=0,
                    help="stop adding towns once a region has this many rows (0 = scrape every town)")
    ap.add_argument("--cap", type=int, default=0, help="max rows per region CSV (0 = no cap)")
    ap.add_argument("--forever", action="store_true",
                    help="unattended: on rate-limit/connection errors wait and continue until the queue is done")
    ap.add_argument("--depth", type=int, default=8)
    ap.add_argument("--radius", type=int, default=12000, help="metres around each town")
    ap.add_argument("--max-time", type=int, default=2400, help="per-area job limit in SECONDS")
    ap.add_argument("--no-email", dest="email", action="store_false", default=True)
    ap.add_argument("--keep-symbol-groups", action="store_true",
                    help="keep Spar/Londis/Premier/Nisa/Costcutter-type franchise stores")
    ap.add_argument("--exclude-dir", help="folder of CSVs you already have; matching shops are skipped")
    ap.add_argument("--proxies", nargs="*", help="proxy URLs, e.g. socks5://user:pass@host:port")
    ap.add_argument("--max-areas", type=int, default=0,
                    help="CHUNK mode: scrape this many towns, then stop (re-run to do the next chunk)")
    ap.add_argument("--poll", type=int, default=20, help="seconds between status checks")
    ap.add_argument("--keep-jobs", action="store_true", help="don't delete finished jobs from the scraper")
    ap.add_argument("--status", action="store_true", help="print progress and exit")
    ap.add_argument("--rebuild", action="store_true", help="rebuild region CSVs from saved raw data and exit")
    a = ap.parse_args()

    with open(a.regions, encoding="utf-8") as f:
        cfg = json.load(f)
    regions = cfg["regions"]
    want = set()
    if a.only:
        want = {x.strip() for x in a.only.split(",")}
        unknown = want - {r["slug"] for r in regions}
        if unknown:
            sys.exit(f"✗ unknown region(s): {', '.join(sorted(unknown))}")
    os.makedirs(a.out_dir, exist_ok=True)
    state_path, geo_path = os.path.join(a.out_dir, "state.json"), os.path.join(a.out_dir, "geocode-cache.json")
    state = load_json(state_path, {"regions": {}})
    geo_cache = load_json(geo_path, {})
    for r in regions:
        state["regions"].setdefault(r["slug"], {"done": {}, "pending": {}, "failed": {}, "rows": 0,
                                                 "complete": False})
    save_json(state_path, state)

    if a.status:
        for r in regions:
            s = state["regions"][r["slug"]]
            mark = "✓" if s["complete"] else ("…" if s["done"] or s["pending"] else " ")
            print(f" {mark} {r['slug']:<56} {s['rows']:>5} rows · {len(s['done'])}/{len(r['areas'])} areas"
                  + (f" · failed: {', '.join(s['failed'])}" if s["failed"] else ""))
        return

    flt = Filter(a.keep_symbol_groups, load_exclusions(a.exclude_dir) if a.exclude_dir else set())
    areas_run = 0  # towns scraped this run (for --max-areas chunks)
    taken = set()  # shops already placed in an earlier region's CSV (surrounding towns overlap)

    for region in regions:
        st = state["regions"][region["slug"]]
        selected = not want or region["slug"] in want
        if a.rebuild or st["complete"] or not selected:
            if any(os.path.exists(os.path.join(a.out_dir, "raw", region["slug"], slug(x) + ".csv"))
                   for x in region["areas"]):
                rows, seen, why = build_region(region, a.out_dir, flt, taken, a.cap)
                taken |= seen
                st["rows"] = len(rows)
                if a.rebuild:
                    log(f"rebuilt {region['slug']}: {len(rows)} rows · dropped {why}")
            continue

        log(f"══ {region['slug']} (target {a.target or 'all towns'}) ══")
        empty_streak = 0
        rows, seen = [], set()
        for area in region["areas"]:
            if area in st["done"]:
                continue
            if st["failed"].get(area, 0) >= 2:
                log(f"  · {area}: failed twice before — skipping")
                continue
            if a.max_areas and areas_run >= a.max_areas:
                save_json(state_path, state)
                log(f"⏸ Chunk done ({areas_run} towns). Re-run the same command for the next chunk.")
                return
            areas_run += 1
            res = run_area(region, area, cfg, a, state, geo_cache, state_path, geo_path)
            if res == "skip":
                continue
            if res == "failed" or res == 0:
                empty_streak += 1
                if empty_streak >= 3:
                    save_json(state_path, state)
                    raise RateLimited()
                else:
                    log("  ⚠ empty/failed result — backing off 5 min")
                    time.sleep(300)
                continue
            empty_streak = 0
            rows, seen, why = build_region(region, a.out_dir, flt, taken, a.cap)
            st["rows"] = len(rows)
            save_json(state_path, state)
            log(f"  ✓ {area}: {res} raw → region now {len(rows)} independent shops (dropped {why})")
            if a.target and len(rows) >= a.target:
                break
        rows, seen, why = build_region(region, a.out_dir, flt, taken, a.cap)
        taken |= seen
        st["rows"] = len(rows)
        retry = [x for x, c in st["failed"].items() if c < 2 and x not in st["done"]]
        st["complete"] = bool(a.target and len(rows) >= a.target) or not retry
        save_json(state_path, state)
        note = "" if not a.target or len(rows) >= a.target else "  (all towns used — below target; add more to the JSON)"
        log(f"══ {region['slug']}: {len(rows)} rows → {os.path.join(a.out_dir, region['slug'] + '.csv')}{note}")
    save_json(state_path, state)
    log("Queue finished.")


def run():
    forever = "--forever" in sys.argv
    while True:
        try:
            return main()
        except RateLimited:
            if not forever:
                sys.exit("✗ 3 towns in a row came back empty/failed — Google is probably rate-limiting this IP.\n"
                         "  Wait 30-60 min (or add --proxies) and re-run the same command to CONTINUE.")
            log("⚠ Looks rate-limited — sleeping 45 min, then continuing (--forever).")
            time.sleep(2700)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            if not forever:
                raise
            log(f"⚠ Scraper unreachable ({e}) — retrying in 2 min (--forever).")
            time.sleep(120)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit("\n⏸ Stopped. Re-run the same command to continue where it left off.")
