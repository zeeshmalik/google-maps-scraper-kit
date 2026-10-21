"""Merge this project's 17 region CSVs with the user's earlier city workbooks into one de-duplicated UK master CSV.

usage: python3 -I merge_master.py <earlier_xlsx_dir>
Only each workbook's 'Independent Shops' sheet is used (franchise / chain / excluded sheets are skipped).
"""
import csv, json, os, re, sys
import openpyxl

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))
OUT = os.path.join(ROOT, "output/uk-independent-shops")
COLS = ["Business Name", "Business Category", "Full Address", "Phone Number", "Website", "Region"]
PC = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
EARLIER = {  # filename fragment -> Region label
    "birmingham": "birmingham",
    "greater-manchester": "greater-manchester",
    "liverpool-lancashire": "liverpool-lancashire",
    "glasgow-edinburgh": "glasgow-edinburgh",
    "north-west-london": "north-west-london",
    "outer-london": "outer-london",
    "south-london": "south-london",
    "southampton-portsmouth-reading-oxford": "southampton-portsmouth-reading-oxford",
    "south-yorkshire-nottingham-derby": "south-yorkshire-nottingham-derby",
    "tyne-wear-teesside": "tyne-wear-teesside",
    "west-yorkshire": "west-yorkshire",
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def key(row):
    m = PC.search(row["Full Address"] or "")
    return norm(row["Business Name"]), (m.group(1) + m.group(2)).upper() if m else norm(row["Full Address"])[:40]


def cell(v):
    return "" if v is None else str(v).strip()


def earlier_rows(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)["Independent Shops"]
    it = ws.iter_rows(values_only=True)
    head = [cell(h) for h in next(it)]
    for r in it:
        d = dict(zip(head, (cell(c) for c in r)))
        if not d.get("Business Name"):
            continue
        if "Full Address" in d:  # same 5-column layout as this project
            yield {c: d.get(c, "") for c in COLS[:5]}
        else:  # Birmingham layout: Phone / Email / Website / Address / Postcode / Category
            addr, pc = d.get("Address", ""), d.get("Postcode", "")
            if pc and norm(pc) not in norm(addr):
                addr = f"{addr}, {pc}".strip(", ")
            yield {"Business Name": d["Business Name"], "Business Category": d.get("Category", ""),
                   "Full Address": addr, "Phone Number": d.get("Phone", ""), "Website": d.get("Website", "")}


def main(xdir):
    seen, rows, stats = set(), [], {}
    cfg = json.load(open(os.path.join(ROOT, "examples/uk-regions-remaining.json")))
    sources = [(r["slug"].replace("-independent-shops", ""), os.path.join(OUT, r["slug"] + ".csv")) for r in cfg["regions"]]
    for f in sorted(os.listdir(xdir)):
        label = next((v for k, v in EARLIER.items() if k in f), None)
        if f.endswith(".xlsx") and label:
            sources.append((label, os.path.join(xdir, f)))
    for label, path in sources:
        src = earlier_rows(path) if path.endswith(".xlsx") else csv.DictReader(open(path, encoding="utf-8-sig"))
        added = dup = 0
        for row in src:
            k = key(row)
            if k in seen:
                dup += 1
                continue
            seen.add(k)
            rows.append({**{c: row.get(c, "") for c in COLS[:5]}, "Region": label})
            added += 1
        stats[label] = (added, dup)
    out = os.path.join(OUT, "uk-master-independent-shops.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    for label, (a, d) in stats.items():
        if label in EARLIER.values():
            print(f"  {label:<24} +{a:>5} added · {d} already in master")
    print(f"master: {len(rows)} shops from {len(stats)} sources → {out}")


if __name__ == "__main__":
    main(sys.argv[1])
