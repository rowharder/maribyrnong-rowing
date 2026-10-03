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
- One **row per factor**: Wind, Temperature, Rain, Lightning, Fog, Darkness, Tide, Flood.
- An **Overall** light per column (the worst factor), with the factors that set it listed underneath.
- **Tap a column** for the reasons behind each light. **Tap a row name ↗** to open the source page and check it.
- A **Right now** section:
  - Essendon Airport weather
  - river gauges
  - Keilor level forecast chart
  - tide at the course (measured and predicted)
- Lights: green = Go, yellow = Caution, red = No go, grey = No data.
  - If the whole page is more than 8 hours old, every light goes grey.

## Rules

All numbers are in `config/thresholds.json`. In that file, `amber` means yellow.

| Factor | Yellow | Red |
|---|---|---|
| Wind | 10 kn or more | 15 kn or more, or a BOM Severe Weather Warning (Central) |
| Temperature | under 10 °C, or 30 °C or more | 35 °C or more |
| Rain | 2 mm/hr or more | – (see combinations) |
| Lightning | BOM day forecast mentions thunder, lightning or hail, or unstable air with rain | thunderstorm forecast during the session, or a BOM Severe Thunderstorm Warning (Central) |
| Fog | visibility under 1,600 m, or fog forecast | visibility under 500 m |
| Darkness | any part of the session before first light or after last light (civil twilight, sun 6° below the horizon) | – (see combinations) |
| Tide | outgoing, falling 0.1 m/hr or faster (BOM Williamstown, in step with the course) | – (see combinations) |
| Flood | Keilor 0.6 m or more, BOM Flood Watch, or an upstream gauge rising 0.2 m/hr or faster | Keilor 1.0 m or more, BOM Maribyrnong Flood Warning, or an upstream gauge rising 0.5 m/hr or faster |

**Combinations that are red** (in `combinations`). Each needs all of its factors at yellow or worse:

- Dark + fog
- Dark + rain (rain counts here from 0.3 mm/hr)
- Rain + wind
- Outgoing tide + high river

**Flood uses the Keilor gauge reading** (Melbourne Water 230105A), which is the same figure as BOM's
"Maribyrnong River at Keilor", so it can be checked on BOM's river heights page (IDV60201). For sessions
more than 3 hours away, the Flood light uses the Keilor forecast (below).

Displayed numbers are rounded, and the colour is judged on the rounded number, so they always agree.

## Keilor forecast (trial)

Forecasts Keilor's height for the next 3 days from two inputs only:

- **Keilor's current flow**
- **Catchment rain**: Melbourne Water rain gauges at Keilor, Darraweit Guim, Sunbury and Bulla, plus
  Open-Meteo forecast rain over the catchment

The model was learned from 2018–2024 hourly records, after removing sensor glitches.

Tested on 2025–26 data it hadn't seen, a day ahead it was typically:

- within about 3 cm in normal conditions
- within about 24 cm when the river is high

It handles falling rivers well, but **misses sudden rises**. It can't see a pulse of water already coming
down from upstream, and it under-forecasts big floods (Oct 2022, Jan 2024). Upstream gauges were left out
of the forecast on purpose, to keep it simple.

To switch the forecast off for the lights, set `river_forecast.use_for_lights` to `false` in `config/sources.json`.

To refit the model (for example once a year, or after a big flood):

```
python3 scripts/fetch_history.py        # downloads history/ (not committed)
python3 scripts/fit_river_model.py      # several minutes; writes config/river_model.json
```

Check the printed test results before uploading a new model.

## How it runs

- **GitHub Actions** (`.github/workflows/update.yml`) runs the update every hour at :23. It also runs on
  every push, and from the Actions tab via "Update conditions" → "Run workflow". Each run:
  1. runs the tests,
  2. runs `scripts/build.py` to fetch all the data, apply the rules and write `site/data/latest.json`,
  3. publishes `site/` to GitHub Pages.
- GitHub sometimes skips scheduled runs. Running hourly at :23 (off the busy hour and half-hour) keeps
  gaps well under 6 hours. If skipped runs become a problem, use an external trigger such as cron-job.org.
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
| `config/sources.json` | Location, session times, data URLs, gauge IDs, row "check" links, forecast settings |
| `config/river_model.json` | Fitted Keilor forecast (made by `fit_river_model.py`) |
| `scripts/build.py` | Fetches everything, applies rules, writes `site/data/latest.json` |
| `scripts/sources.py` | One fetch function per data source |
| `scripts/rules.py` | The traffic-light rules (no network; unit tested) |
| `scripts/river_model.py` | Keilor forecast maths |
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
