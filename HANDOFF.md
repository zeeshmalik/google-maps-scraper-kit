# Handoff: UK eating-places job (cafés, restaurants, takeaways, pubs) with owner names

Read this first in a new session. It carries the user's decisions and what earlier sessions learned
so the user doesn't have to repeat anything.

## The user

- Builds UK business contact lists and checks in from their phone while at work. Keep replies short
  and plain; lead with the number they care about.
- Standing instruction: **keep the job running non-stop, slow or fast**. Don't pause to ask unless a
  decision is really theirs.
- Wants a **phone push notification** (PushNotification) when each region finishes.
- **Attachments don't work for them**: SendUserFile files arrive on their phone as `content.json`.
  Deliver files through a **private download page** (an Artifact with the `downloads` capability; see
  `scripts/ops/download_page/`). The user explicitly approved this for scraped business data.

## Finished job: independent grocery & convenience shops (done 2026-10-21)

- 34,095 independent shops, master CSV plus one CSV per region, on the user's download page:
  https://claude.ai/artifact/7MD7WqFgLp82K2VPdLWEPL . The data itself lives only there and in the
  user's files (`output/` is gitignored). To reuse it, Artifact `read` that URL with
  `path: "data/uk-master-independent-shops.csv"`.
- Built with `scripts/uk_queue.py` + `examples/uk-regions-remaining.json`, merged with the user's
  earlier city workbooks by `scripts/ops/merge_master.py`.
- Still not covered: East London, Leicester, Bristol, Coventry, Stoke, Luton, Slough, Black Country,
  South Wales.

## Next job (agreed with the user, not started)

**Every independent eating place in the UK** with owner / director names.

Decisions the user made:
- Types: **all eating places**: restaurants, cafés, canteens, takeaways, sandwich shops, pubs/bars,
  mobile caterers. Not schools, hospitals or care homes.
- **Independent only**: small businesses and small companies. No big chains or brands
  (Costa, Greggs, McDonald's, KFC, Subway, Nando's, Domino's, Pizza Hut, Pret, Starbucks, Caffè Nero,
  Wetherspoon, Greene King, Toby, Harvester, Wagamama, PizzaExpress, Zizzi, Prezzo, Five Guys, Leon,
  Burger King, …) plus the "same name at 4+ sites = chain" rule from `uk_queue.py`.
- **No Companies House API key** (the user can't create one). Use the free bulk files instead.
- Pending: the user still has to say "go" and pick the pilot city (suggested: Manchester).

Plan:
1. **Base list: Food Standards Agency hygiene-rating register** (free, OGL, no key; reachable from the
   cloud container). API `https://api.ratings.food.gov.uk/` (send header `x-api-version: 2`) or the
   per-council XML files `https://ratings.food.gov.uk/api/open-data-files/FHRS<id>en-GB.xml`.
   Business types to keep: Restaurant/Cafe/Canteen, Takeaway/sandwich shop, Pub/bar/nightclub,
   Mobile caterer (check the exact names via the BusinessTypes endpoint).
2. **Owner names: Companies House bulk data** (free, no key):
   - `https://download.companieshouse.gov.uk/en_output.html`: BasicCompanyDataAsOneFile (~470 MB zip):
     live companies, registered address, SIC codes. Keep SIC 56101, 56102, 56103, 56210, 56290, 56302.
   - `https://download.companieshouse.gov.uk/en_pscdata.html`: PSC snapshot, 33 zips of ~75 MB:
     owners (persons with significant control). Gives owners, not every director; for small firms the
     owner is usually the director.
   - Stream each zip, keep only rows for the food companies, delete the zip: the session's disk
     allowance is limited.
   - Match an eating place to a company by postcode + name similarity. Add a Match Confidence
     column (high/medium); leave names blank rather than guess. Expect ~25-40% matched (sole traders
     are not on Companies House).
3. **Phone, website, category: Google Maps** via the local scraper (`scripts/uk_queue.py` pattern,
   same towns as the grocery regions, keywords like "cafe in {town}", "restaurant in {town}",
   "takeaway in {town}", "pub in {town}").
4. Deliver in two stages: (a) FSA list + owner names for the whole UK (~1 day); (b) phones/websites
   region by region (~10-14 days), each region added to a download page with a push notification.

Output columns: Business Name, Category, Full Address, Phone, Website, Owner/Director Name(s), Role,
Company Name, Company Number, Match Confidence, Region.

Compliance (tell the user once, briefly; they've already been told): owner names are personal data
under UK GDPR. B2B outreach is fine with a legitimate-interests basis, a privacy notice to the people
named and working opt-outs; screen calls against TPS/CTPS; email to sole traders needs consent (PECR).

## Running long jobs in a cloud session: lessons learned

- **First run `bash scripts/ops/cloud_setup.sh`.** It makes the scraper trust the session's proxy CA
  (without it every Maps request fails TLS) and starts Docker + the scraper on http://localhost:8080.
- **The container only lives while the session is active.** Keep `scripts/ops/keepalive.sh` running with
  run_in_background (timeout 7200000) and restart it every time it exits; its exit code tells you what to
  do with one tool call (0 heartbeat, 10 notify, 11 supervisor dead). Have the supervisor append a line
  to `$OPS_DIR/notify` (default `/root/gmaps-ops`) when a deliverable is ready. Also create a
  3-hourly routine (create_trigger, cron `0 */3 * * *`) that runs `scripts/ops/recover.sh` and restarts
  keepalive.sh, as a safety net after container restarts.
- Put the supervisor command in `$OPS_DIR/queue.sh` (end it with `exec python3 -u …`); `recover.sh`
  (re)starts it. Add a SessionStart hook in `.claude/settings.local.json` running `scripts/ops/recover.sh`.
- **Claude usage limits stop everything**: when the 5-hour or weekly limit is hit, no turn runs and the
  container shuts down until the next wake. Keep each check-in to 1-2 tool calls and replies short.
- Scraper settings that work: default concurrency (`-c 4` left jobs stuck "working"), `fast_mode: false`
  (fast mode lost ~30% of results and the category), depth 8, radius 12 km, 12 keywords per job.
  `uk_queue.py` has the stall guard, Nominatim 429 retries, and a nearby-town fallback for geocoding.
