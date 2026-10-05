# UK location lists (for Google Maps research)

| File | Contents |
|---|---|
| `uk_all_locations.txt` | Everything below, deduplicated, one per line as `Place, Nation` (3,917) |
| `uk_cities_official.txt` | The 76 places with official UK city status, by nation |
| `uk_councils_districts.txt` | 216 council areas: London boroughs, metropolitan districts, counties, unitary authorities, Scottish council areas, NI districts |
| `uk_towns_places.txt` | 3,871 cities, towns, suburbs and villages, grouped by nation |
| `towns_<nation>.txt` | Same as above, one plain file per nation |
| `uk_places_with_coords.csv` | Towns/places with `lat,lon`, ready for the scraper's `lat`/`lon` fields |

Source: the open [countries-states-cities-database](https://github.com/dr5hn/countries-states-cities-database)
(ODbL-1.0), through the `country-state-city` npm package. Council list predates the 2023 English
reorganisations. Official city list compiled by hand (as of the 2022 Platinum Jubilee grants).
The data isn't exhaustive: small hamlets are missing.
