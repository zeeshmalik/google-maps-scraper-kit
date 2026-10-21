#!/usr/bin/env python3
"""Independent eating places for a set of councils: FSA hygiene register + Companies House owners + Google Maps.

    python3 scripts/eating_places.py --fsa-dir DIR --maps-dir DIR --out FILE.csv [--ch-dir DIR]

--fsa-dir   FHRS<code>en-GB.xml files, one per council (https://ratings.food.gov.uk/api/open-data-files/...)
--ch-dir    food_companies.csv + food_psc.jsonl, the Companies House bulk files cut down to SIC 56xxx
            (live companies; persons with significant control that have not ceased). Optional: without
            it the owner/company columns are left out.
--maps-dir  raw scraper CSVs from scripts/uk_queue.py (output/<run>/raw/<region>/*.csv); optional

The FSA register is the base list. Chains are dropped by name and by the "same name at 4+ sites" rule.
An eating place gets owner names only when it matches a company by postcode + name (high) or by a unique
exact name in the same postcode area (medium); otherwise the owner columns stay blank. Standard library only.
"""
import argparse, collections, csv, difflib, glob, json, os, re, sys, xml.etree.ElementTree as ET

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
KEEP_TYPES = {"Restaurant/Cafe/Canteen", "Takeaway/sandwich shop", "Pub/bar/nightclub", "Mobile caterer"}
CHAINS = [
    "costa", "greggs", "mcdonald", "mcdonalds", "kfc", "subway", "nando", "nandos", "domino", "dominos",
    "pizza hut", "pret", "pret a manger", "starbucks", "caffe nero", "caffè nero", "nero", "wetherspoon",
    "greene king", "toby carvery", "harvester", "wagamama", "pizzaexpress", "pizza express", "zizzi", "prezzo",
    "five guys", "leon", "burger king", "papa john", "papa johns", "taco bell", "popeyes", "wingstop",
    "tim hortons", "german doner kebab", "miller & carter", "beefeater", "brewers fayre", "hungry horse",
    "sizzling pubs", "stonehouse", "vintage inns", "all bar one", "slug and lettuce", "browns", "bella italia",
    "cafe rouge", "frankie & benny", "frankie and benny", "chiquito", "las iguanas", "yo sushi", "itsu",
    "wasabi", "tortilla", "chopstix", "coffee#1", "coffee 1", "black sheep coffee", "gail's", "joe & the juice",
    "krispy kreme", "chef & brewer", "flaming grill", "ember inns", "morley's", "dixy chicken", "crussh",
    "sainsbury", "tesco", "asda", "morrisons", "marks & spencer", "m&s", "ikea", "boots", "waitrose",
    "côte", "cote brasserie", "giraffe", "gourmet burger kitchen", "honest burgers", "tgi friday", "tgi fridays",
    "bill's", "turtle bay", "the real greek", "byron", "pizza pilgrims", "franco manca", "dishoom", "hooters",
    "chicken cottage", "taco bell", "pho", "wildwood", "loungers", "cosy club", "brewdog", "pitcher & piano",
    "revolution", "be at one", "slim chickens", "popeyes", "wendy's", "wendys", "caffe ritazza", "upper crust",
    "soho coffee", "esquires", "muffin break", "harris + hoole", "puccino's", "patisserie valerie",
    "kaspa's", "kaspas", "creams cafe", "heavenly desserts", "chaiiwala", "chicken george", "wingers",
    "compass group", "sodexo", "aramark", "baxterstorey", "elior", "chartwells", "eurest",
]
CHAIN_RX = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(c) for c in CHAINS) + r")(?![a-z0-9])")
LEGAL = re.compile(r"\b(ltd|limited|plc|llp|lp|cic|co|company|the|and|t a|t/a|trading as|uk|group|holdings?|"
                   r"enterprises?|services|catering|restaurants?|cafe|takeaway|ventures?)\b")
PC_RX = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
OUT = ["Business Name", "Category", "Full Address", "Phone", "Email", "Website", "Region"]
OWNER_COLS = ["Owner/Director Name(s)", "Role", "Company Name", "Company Number", "Match Confidence"]


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]+", " ", (s or "").lower().replace("’", "'").replace("'", ""))).strip()


def core(s):  # name without legal suffixes / generic words, for company matching
    return re.sub(r"\s+", " ", LEGAL.sub(" ", norm(s).replace("&", " "))).strip()


def pc(s):
    m = PC_RX.search(s or "")
    return (m.group(1) + m.group(2)).upper() if m else ""


def pc_area(p):
    return re.match(r"[A-Z]+", p).group(0) if p else ""


def sim(a, b):
    a, b = core(a), core(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 5 and len(b) >= 5 and (a in b or b in a):
        return 0.85
    if a.split()[0] != b.split()[0]:  # "Kaspa's Desserts" is not "A&A Desserts"
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def load_fsa(folder):
    rows = []
    for f in sorted(glob.glob(os.path.join(folder, "*.xml"))):
        for e in ET.parse(f).getroot().iter("EstablishmentDetail"):
            g = lambda t: (e.findtext(t) or "").strip()
            if g("BusinessType") not in KEEP_TYPES or not g("BusinessName"):
                continue
            addr = [g(f"AddressLine{i}") for i in range(1, 5)] + [g("PostCode")]
            rows.append({"name": g("BusinessName"), "type": g("BusinessType"), "pc": pc(g("PostCode")),
                         "addr": ", ".join(x for x in addr if x), "region": g("LocalAuthorityName")})
    return rows


def independents(rows):
    sites = collections.defaultdict(set)
    for r in rows:
        sites[norm(r["name"])].add(r["pc"] or r["addr"])
    return [r for r in rows if not CHAIN_RX.search(norm(r["name"])) and len(sites[norm(r["name"])]) < 4]


def load_companies(folder):
    by_pc, by_core = collections.defaultdict(list), collections.defaultdict(list)
    with open(os.path.join(folder, "food_companies.csv"), encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            c = {"name": r["CompanyName"], "num": r["CompanyNumber"], "pc": pc(r["RegAddress.PostCode"])}
            if c["pc"]:
                by_pc[c["pc"]].append(c)
            if core(c["name"]):
                by_core[core(c["name"])].append(c)
    owners = collections.defaultdict(list)
    with open(os.path.join(folder, "food_psc.jsonl"), encoding="utf-8") as f:
        for line in f:
            j = json.loads(line)
            if j["kind"] == "individual-person-with-significant-control" and j.get("name"):
                owners[j["n"]].append(j["name"])
    return by_pc, by_core, owners


def match_company(r, by_pc, by_core):
    best = max(by_pc.get(r["pc"], []), key=lambda c: sim(r["name"], c["name"]), default=None)
    if best and sim(r["name"], best["name"]) >= 0.8:
        return best, "high"
    k = core(r["name"])
    hits = [c for c in by_core.get(k, []) if pc_area(c["pc"]) == pc_area(r["pc"])]
    if len(k) >= 6 and len(hits) == 1:
        return hits[0], "medium"
    return None, ""


def load_maps(folder):
    by_pc = collections.defaultdict(list)
    for p in glob.glob(os.path.join(folder, "**", "*.csv"), recursive=True):
        with open(p, encoding="utf-8", newline="") as f:
            for m in csv.DictReader(f):
                k = pc(m.get("address"))
                if k and m.get("title"):
                    by_pc[k].append(m)
    return by_pc


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fsa-dir", required=True)
    ap.add_argument("--ch-dir")
    ap.add_argument("--maps-dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    allrows = load_fsa(a.fsa_dir)
    rows = independents(allrows)
    by_pc, by_core, owners = load_companies(a.ch_dir) if a.ch_dir else ({}, {}, {})
    maps = load_maps(a.maps_dir) if a.maps_dir else {}
    stats = collections.Counter()
    out = []
    for r in rows:
        c, conf = match_company(r, by_pc, by_core)
        names = owners.get(c["num"], []) if c else []
        m = max(maps.get(r["pc"], []), key=lambda x: sim(r["name"], x["title"]), default=None)
        if m and sim(r["name"], m["title"]) < 0.6:
            m = None
        stats["company"] += bool(c)
        stats["owner"] += bool(names)
        stats["maps"] += bool(m)
        m = m or {}
        email = ", ".join(x for x in re.split(r"[,;\s]+", m.get("emails", "")) if "@" in x)
        stats["phone"] += bool(m.get("phone"))
        stats["email"] += bool(email)
        stats["website"] += bool(m.get("website"))
        row = {"Business Name": r["name"], "Category": m.get("category") or r["type"], "Full Address": r["addr"],
               "Phone": m.get("phone", ""), "Email": email, "Website": m.get("website", ""), "Region": r["region"]}
        if a.ch_dir:
            row.update({"Owner/Director Name(s)": "; ".join(names), "Role": "Owner (PSC)" if names else "",
                        "Company Name": c["name"] if c else "", "Company Number": c["num"] if c else "",
                        "Match Confidence": conf if c else ""})
        out.append(row)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT[:-1] + OWNER_COLS + OUT[-1:] if a.ch_dir else OUT)
        w.writeheader()
        w.writerows(out)
    n = len(out) or 1
    pct = lambda k: f"{k} {stats[k]} ({stats[k] / n:.0%})"
    print(f"eating places {len(allrows)} · independent {len(out)} · "
          + " · ".join(pct(k) for k in ["maps", "phone", "email", "website"] + (["owner"] if a.ch_dir else [])))


if __name__ == "__main__":
    main()
