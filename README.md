# Maribyrnong Rowing Conditions

Traffic-light guide for rowing on the Maribyrnong River at Poyntons, Essendon.

**Live page:** https://rowharder.github.io/maribyrnong-rowing/
**Repo:** https://github.com/rowharder/maribyrnong-rowing (public)

Guide only. The coach or captain makes the call.

## What the page shows

- One **column per session** for the next 4 days. Times are set in `config/sources.json`:
  - weekday mornings 05:30–07:00
  - weekend mornings 06:30–08:00
  - evenings 18:00–20:00
- One **row per factor**: Wind, Temperature, Rain, Lightning, Fog, Flow.
- A **Lights** note under the session time ("Lights to 06:24" / "Lights from 19:54") when any part of the
  session is before sunrise or after sunset. It's information, not a light.
- An **Overall** light per column (the worst factor), with the factors that set it listed underneath.
- **Tap a column** for the reasons behind each light. **Tap a row name ↗** to open the source page and check it.
- A **Right now** section:
  - Essendon Airport weather
  - river gauges
  - water speed at the course (estimated last day, forecast ahead)
  - tide at the course: water height at Poyntons (measured and forecast) against the river mouth
- Colours: green = Go, yellow = Caution, red = No go, grey = No data.
  - If the whole page is more than 8 hours old, every light goes grey.

## Rules

All numbers are in `config/thresholds.json`. In that file, `amber` means yellow.

| Factor | Yellow | Red |
|---|---|---|
| Wind | 18 km/h or more | 28 km/h or more, or a BOM Severe Weather Warning (Central) |
| Temperature | under 10 °C, or 30 °C or more | 35 °C or more |
| Rain | 2 mm/hr or more | – (see combinations) |
| Lightning | BOM day forecast mentions thunder, lightning or hail, or unstable air with rain | thunderstorm forecast during the session, or a BOM Severe Thunderstorm Warning (Central) |
| Fog | visibility under 1,600 m, or fog forecast | visibility under 500 m |
| Flow | water speed 2 km/h or more (either way), BOM Flood Watch (sessions in the next 24 h), or an upstream gauge rising 0.2 m/hr or faster | 4 km/h or more, BOM Maribyrnong Flood Warning, or an upstream gauge rising 0.5 m/hr or faster |

**Combinations that are red** (in `combinations`). Each needs all of its factors at yellow or worse
(darkness counts when lights are needed):

- Dark + fog (visibility under 1,000 m; fog forecast alone, or 1,000–1,600 m, stays yellow)
- Rain + wind

**Overall also goes red when 3 or more of Wind, Temperature, Rain, Fog and Flow are yellow at once** (`yellow_count_red`).
Dark + rain is no longer a red combination.

Flow already includes the tide, so there is no separate Tide light.

Displayed numbers are rounded, and the colour is judged on the rounded number, so they always agree.

## Flow: water speed at the course (estimate)

Flow is the fastest the water is expected to move past Poyntons during the session, in km/h. It comes from a
volume balance (`scripts/flow_model.py`):

```
water past the course = Keilor's river flow (2 h earlier) + the tide filling or emptying the river upstream
speed = that ÷ (river width × depth at the course)
```

- **River flow:** Keilor's flow (Melbourne Water 230105A). It's measured now, then forecast for 3 days from
  catchment rain (see below). Past the 3-day forecast, the flow is held at its last value.
- **Tide:** the BOM Williamstown prediction. Its rate of rise or fall is multiplied by the water surface
  upstream of the course. Williamstown sits at the mouth and runs in step with the course gauge.
- **River shape** (`flow` in `config/sources.json`):
  - width 52 m, measured on OpenStreetMap
  - water surface upstream to near Solomon's Ford: 360,000 m², measured on OpenStreetMap
  - depth 2.5 m: **a guess**

Speed scales with 1 ÷ (width × depth), so the km/h figures are only as good as these numbers. A rough
check on 5 Oct 2026: about 0.2 km/h was seen going out at 7am, and the model said about 0.4. That suggests
the river may be deeper than 2.5 m. If anyone measures the depth, put it in `depth_m`.

Why not use the slope of the water between Poyntons and the mouth? Over the 9 km of river below the
course the slope is tiny. In Jan 2024, Keilor ran at 84–120 m³/s and Poyntons rose only 0.1–0.3 m. That's
no more than normal weather swings, so the slope only shows up in big floods.

The **height chart** shows Poyntons against the mouth (Williamstown, on the same datum). The gap between
them is how far river flow lifts the water at Poyntons. That's fitted from history
(`config/flow_model.json`): about 0.1 m at 30 m³/s, 0.25 m at 60 m³/s and 2.7 m at 500 m³/s.

Checked against history using measured data:

| Event | Fastest, going out |
|---|---|
| Oct 2022 flood | about 8 km/h |
| Jan 2024 flood | about 3 km/h |
| Normal day | under 1 km/h |

### Keilor flow forecast

Forecasts Keilor's flow for the next 3 days from two inputs only:

- **Keilor's current flow**
- **Catchment rain**: Melbourne Water rain gauges at Keilor, Darraweit Guim, Sunbury and Bulla, plus
  Open-Meteo forecast rain over the catchment

The model was learned from 2018–2024 hourly records, after removing sensor glitches. Tested on 2025–26
data it hadn't seen, a day ahead it was typically within about 3 cm of Keilor's level in normal
conditions, and within about 24 cm when the river is high.

It handles falling rivers well, but **misses sudden rises**. It can't see a pulse of water already coming
down from upstream, and it under-forecasts big floods (Oct 2022, Jan 2024). That's why Flow also goes
yellow or red when an upstream gauge rises fast.

To refit the models (for example once a year, or after a big flood):

```
python3 scripts/fetch_history.py        # downloads history/ (not committed)
python3 scripts/fit_river_model.py      # several minutes; writes config/river_model.json
python3 scripts/fit_flow_model.py       # writes config/flow_model.json; prints flood hindcasts
```

Check the printed results before uploading new models.

## How it runs

- **cron-job.org** triggers the update **every 3 hours at :23** (1:23, 4:23, 7:23, 10:23 am and pm,
  Melbourne time), so there's a fresh update about an hour before each session. It calls GitHub's
  "run workflow" API using a fine-grained token that can only run Actions on this repo. The token is stored
  in cron-job.org only (not in this repo), has no expiry, and can be revoked under GitHub → Settings →
  Developer settings → Fine-grained tokens. To replace it, make a new token with the same settings and paste
  it into the cron-job.org job's `Authorization: Bearer …` header.
  **Before March 2028:** GitHub retires API version `2022-11-28` (sent in the job's `X-GitHub-Api-Version`
  header). Change it to the current version listed at https://docs.github.com/en/rest/about-the-rest-api/api-versions.
- **GitHub Actions** (`.github/workflows/update.yml`) does the work. It also has its own hourly schedule
  (:23) as a backup, but GitHub skips most of those. It runs on every push too, and on demand from the
  Actions tab via "Update conditions" → "Run workflow". Each run:
  1. runs the tests,
  2. runs `scripts/build.py` to fetch all the data, apply the rules and write `site/data/latest.json`,
  3. publishes `site/` to GitHub Pages (retrying once if GitHub glitches).
- A small monthly commit stops GitHub pausing the schedule on an inactive repository.
- Each publish gives the page's code files a new version number, so browsers fetch the new code. Pages left
  open reload themselves when the code changes.
- No server and no cost. Python 3.11 standard library only, with nothing to install.

### Data sources

| What | Source |
|---|---|
| Hourly forecast (wind, gusts, temperature, rain, visibility, thunderstorms) | Open-Meteo |
| Text forecast (Melbourne) | BOM FTP `IDV10450.xml` |
| Current weather | BOM Essendon Airport `IDV60901.95866.json` |
| Warnings (Victoria) | BOM `IDZ00059.warnings_vic.xml` |
| Tide predictions | BOM Melbourne (Williamstown) `VIC_TP003` |
| River levels and rain | Melbourne Water API: Keilor 230105A, Maribyrnong 230106A (tidal, near Poyntons), Keilor North 230237A, Bulla North 230102A, Sunbury 230104A, Darraweit Guim 230100A; rain gauges 230105A, 230100A, 230104A, 587014 |
| Sun times | calculated in `scripts/rules.py` |

If a source fails, only its lights go grey. Every download is retried once.

## Files

| File | What it does |
|---|---|
| `config/thresholds.json` | All rule numbers and combinations |
| `config/sources.json` | Location, session times, data URLs, gauge IDs, row "check" links, forecast settings, river shape |
| `config/river_model.json` | Fitted Keilor flow forecast (made by `fit_river_model.py`) |
| `config/flow_model.json` | Fitted Poyntons water-level setup (made by `fit_flow_model.py`) |
| `scripts/build.py` | Fetches everything, applies rules, writes `site/data/latest.json` |
| `scripts/sources.py` | One fetch function per data source |
| `scripts/rules.py` | The traffic-light rules (no network; unit tested) |
| `scripts/river_model.py` | Keilor flow forecast maths |
| `scripts/flow_model.py` | Water speed and Poyntons height maths |
| `site/` | The web page (`index.html`, `app.js`, `styles.css`, `config.js`) |
| `tests/` | `python3 -m unittest discover tests` |

## Common changes

- **Change a threshold:** edit `config/thresholds.json`, run the tests, push.
- **Change session times:** edit `sessions` in `config/sources.json`. Weekend times go under `weekend`.
- **Add a red combination:** copy an entry in `combinations`. `"a|b"` means either a or b.
- **Change a "check" link:** edit `verify_links` in `config/sources.json`. The first link is used on the row name.
- **Run locally:**
  ```
  python3 -m unittest discover tests
  python3 scripts/build.py
  cd site && python3 -m http.server 8765    # open http://localhost:8765
  ```
- **Push changes:** `git add -A && git commit -m "..." && git push`. The site updates in about a minute.
  GitHub access on this Mac is through `gh` (account `rowharder`).

## Visitor counter

GoatCounter, code `emuflypast` (https://emuflypast.goatcounter.com). The public counter setting must stay
on. The total counts from 1 Oct 2026, because GoatCounter needs a start date. Set or clear the code in
`site/config.js`.
