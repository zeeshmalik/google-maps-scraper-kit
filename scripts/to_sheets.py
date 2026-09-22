#!/usr/bin/env python3
"""Push a results file (CSV or JSON) into Google Sheets — standard library only, free.

Uses the Apps Script receiver in sheets/apps-script.gs (one-time setup: SETUP.md →
"Export to Google Sheets"). Reads SHEETS_WEBHOOK_URL and SHEETS_SECRET from the environment
or from the kit's .env file.

    python3 scripts/to_sheets.py results-1a2b3c4d.csv
    python3 scripts/to_sheets.py results-1a2b3c4d.csv --tab "Dentists Austin"

scripts/scrape.py --sheet calls push_rows() below right after a scrape.
"""
import argparse, csv, json, os, sys, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH = 500  # rows per request (keeps each Apps Script call well under its limits)


def load_env(path=os.path.join(ROOT, ".env")):
    """Minimal .env loader: KEY=VALUE lines, never overrides variables already set."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def push_rows(headers, rows, tab="Leads", url=None, secret=None, dedupe=True):
    """Append rows (list of dicts) to a tab. Returns (added, skipped, sheet_url). Raises on error."""
    load_env()
    url = url or os.environ.get("SHEETS_WEBHOOK_URL", "")
    secret = secret or os.environ.get("SHEETS_SECRET", "")
    if not url:
        raise RuntimeError("SHEETS_WEBHOOK_URL is not set (see SETUP.md → 'Export to Google Sheets').")
    added = skipped = 0
    sheet_url = ""
    for i in range(0, max(len(rows), 1), BATCH):
        chunk = [[r.get(h, "") for h in headers] for r in rows[i:i + BATCH]]
        body = json.dumps({"secret": secret, "tab": tab, "headers": headers,
                           "rows": chunk, "dedupe": dedupe}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        # Apps Script answers a POST with a 302 to the result; urllib follows it as a GET.
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", "replace")
        try:
            res = json.loads(raw)
        except ValueError:
            raise RuntimeError("Unexpected reply from Apps Script — is the web app deployed with "
                               "'Who has access: Anyone'? First 200 chars:\n" + raw[:200])
        if not res.get("ok"):
            raise RuntimeError(res.get("error", "unknown error"))
        added += res.get("added", 0)
        skipped += res.get("skipped", 0)
        sheet_url = res.get("url", sheet_url)
    return added, skipped, sheet_url


def read_file(path):
    if path.lower().endswith(".json"):
        with open(path) as f:
            rows = json.load(f)
        headers = list(rows[0].keys()) if rows else []
    else:
        with open(path, newline="") as f:
            rd = csv.DictReader(f)
            rows, headers = list(rd), rd.fieldnames or []
    return headers, rows


def main():
    ap = argparse.ArgumentParser(description="Push a CSV/JSON results file to Google Sheets.")
    ap.add_argument("file", help="results-*.csv or .json from scrape.py")
    ap.add_argument("--tab", default="Leads", help="sheet tab to append to (created if missing)")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="append every row, even businesses already in the tab")
    a = ap.parse_args()

    headers, rows = read_file(a.file)
    if not rows:
        sys.exit("✗ No rows in " + a.file)
    print(f"▶ Sending {len(rows)} rows to Google Sheets (tab \"{a.tab}\")…")
    try:
        added, skipped, url = push_rows(headers, rows, tab=a.tab, dedupe=not a.no_dedupe)
    except (RuntimeError, urllib.error.URLError) as e:
        sys.exit(f"✗ Sheets export failed: {e}")
    print(f"✓ Added {added} rows" + (f", skipped {skipped} duplicates" if skipped else "") + ".")
    if url:
        print(f"  {url}")


if __name__ == "__main__":
    main()
