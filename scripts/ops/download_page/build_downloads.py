#!/usr/bin/env python3
"""Regenerate the private download page (index.html + data/*.csv) from the completed regions in state.json.

Output goes to output/uk-independent-shops/download_page/ (gitignored: the CSVs hold personal data).
Publish it with the Artifact tool: file_path <that dir>/index.html, root <that dir>, files = data/<region>.csv.
"""
import csv, json, os, shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))
OUT = os.path.join(ROOT, "output/uk-independent-shops")
DL = os.path.join(OUT, "download_page")
NAMES = {
    "east-anglia": "East Anglia",
    "essex-hertfordshire": "Essex & Hertfordshire",
    "kent-sussex": "Kent & Sussex",
    "surrey-west-sussex-north-hampshire": "Surrey, West Sussex & North Hampshire",
    "milton-keynes-northants-beds-bucks": "Milton Keynes, Northants, Beds & Bucks",
    "devon-cornwall": "Devon & Cornwall",
    "dorset-wiltshire-somerset": "Dorset, Wiltshire & Somerset",
    "gloucs-worcs-hereford-shropshire": "Gloucestershire, Worcestershire, Herefordshire & Shropshire",
    "hull-york-north-yorkshire": "Hull, York & North Yorkshire",
    "lincolnshire": "Lincolnshire",
    "cheshire-north-wales-cumbria": "Cheshire, North Wales & Cumbria",
    "west-mid-wales": "West & Mid Wales",
    "scotland-north-east-highlands": "Scotland: North East & Highlands",
    "scotland-central-south": "Scotland: Central & South",
    "northern-ireland": "Northern Ireland",
    "central-north-london": "Central & North London",
    "extra-towns": "Extra towns: North East, Midlands, Thames Valley, Isle of Wight & Scottish islands",
}

cfg = json.load(open(os.path.join(ROOT, "examples/uk-regions-remaining.json")))
state = json.load(open(os.path.join(OUT, "state.json")))["regions"]
os.makedirs(os.path.join(DL, "data"), exist_ok=True)
done, todo = [], []
for r in cfg["regions"]:
    s, short = state[r["slug"]], r["slug"].replace("-independent-shops", "")
    name = NAMES.get(short, short.replace("-", " ").title())
    if not s["complete"]:
        todo.append({"name": name, "towns": len(r["areas"]), "doneTowns": len(s["done"]), "shops": s["rows"]})
        continue
    src = os.path.join(OUT, r["slug"] + ".csv")
    shutil.copyfile(src, os.path.join(DL, "data", r["slug"] + ".csv"))
    with open(src, encoding="utf-8-sig") as f:
        shops = sum(1 for _ in csv.reader(f)) - 1
    done.append({"slug": r["slug"], "name": name, "towns": len(r["areas"]), "shops": shops,
                 "kb": round(os.path.getsize(src) / 1024)})

manifest = {"done": done, "todo": todo}
master = os.path.join(OUT, "uk-master-independent-shops.csv")
if os.path.exists(master):
    shutil.copyfile(master, os.path.join(DL, "data", "uk-master-independent-shops.csv"))
    with open(master, encoding="utf-8-sig") as f:
        manifest["master"] = {"shops": sum(1 for _ in csv.reader(f)) - 1, "kb": round(os.path.getsize(master) / 1024)}
tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.tpl.html"), encoding="utf-8").read()
open(os.path.join(DL, "index.html"), "w", encoding="utf-8").write(
    tpl.replace("/*MANIFEST*/null", json.dumps(manifest, ensure_ascii=False)))
print(f"{len(done)} regions, {sum(d['shops'] for d in done)} shops → {DL}/index.html")
print(json.dumps({f"data/{d['slug']}.csv": f"{DL}/data/{d['slug']}.csv" for d in done}))
