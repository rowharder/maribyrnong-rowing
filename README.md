# Maribyrnong Rowing Conditions

A public web page with traffic lights for each rowing session (weekday mornings 05:30–07:00, weekend
mornings 06:30–08:00, evenings 18:00–20:00) over the next few days on the Maribyrnong River. Each column is a session; each row is a
risk factor; the top row is the overall call.

**Guide only. The coach or captain on the day makes the call.**

## How it works

Every 30 minutes a GitHub Action runs `scripts/build.py`, which:

1. fetches data from:
   - BOM: text forecast, Essendon Airport observations, Victorian warnings, Williamstown tide predictions
   - Melbourne Water: river gauges at Maribyrnong (tidal, ~700 m from Poyntons – shown as the measured tide), Keilor, Keilor North, Bulla North, Sunbury and Darraweit Guim
   - Open-Meteo: hourly forecast for wind, temperature, rain, fog/visibility and thunderstorms
2. applies the rules in `scripts/rules.py` using the numbers in `config/thresholds.json`,
3. writes `site/data/latest.json` and publishes the `site/` folder to GitHub Pages.

If a source fails, its lights show grey ("No data – check manually") rather than a false green. If the
whole page is more than 3 hours old, every light turns grey.

## The rules (edit `config/thresholds.json`)

| Factor | Amber | Red |
|---|---|---|
| Wind | ≥10 kn | ≥15 kn, or a BOM Severe Weather Warning (Central district) |
| Temperature | ≥30 °C, or below 5 °C | ≥35 °C |
| Rain | ≥2 mm/hr | – |
| Lightning | BOM day forecast mentions thunder/lightning/hail, or unstable air with rain | thunderstorm forecast during the session, or a BOM Severe Thunderstorm Warning (Central district) |
| Fog / visibility | <2 km or fog forecast | <1 km |
| Darkness | any part of the session before first light or after last light (civil twilight) | – (red with fog or rain) |
| Tide | outgoing, falling ≥0.1 m/hr | – |
| River / flood | Keilor 0.1–0.6 m above its normal for the time of year, upstream rising ≥0.2 m/hr, or BOM Flood Watch | Keilor ≥0.6 m above normal, upstream rising ≥0.5 m/hr, or a BOM Maribyrnong flood warning |

Keilor's normal level changes with the season (about 0.28 m in summer to 0.46 m in August – median daily
levels 2014–2026, in `flood.keilor_normal_by_month_m`), so the yellow/red heights move through the year.

**Dangerous combinations turn red** (in `combinations`):

- Dark + fog
- Dark + rain (any rain from 0.3 mm/hr)
- Rain + wind at amber
- Outgoing tide + high river (river at amber or worse)

Add your own combination by copying an entry. Use `"a|b"` to mean "either a or b".

## Running locally

```
python3 -m unittest discover tests   # rule tests
python3 scripts/build.py             # fetch data → site/data/latest.json
cd site && python3 -m http.server 8765   # then open http://localhost:8765
```

No packages to install; it uses only Python 3.11+ built-ins.

## Visitor counter

Sign up free at goatcounter.com, enable "Allow adding visitor counts on your website" in its settings,
and put your code in `site/config.js`. The footer will then show total visits and visits this week.

## Keilor river forecast (experimental)

`scripts/river_model.py` forecasts Keilor's height for the next 3 days from just two things: Keilor's
current flow and catchment rain (Melbourne Water gauges at Keilor, Darraweit Guim, Sunbury and Bulla,
plus Open-Meteo forecast rain over the catchment). For each look-ahead it learned from 2018–2024 history
how much the river changes given recent rain, how wet the catchment already is, and rain to come.

Tested on 2025–26 (not used for fitting), a day ahead it was typically within ~3 cm in normal
conditions and ~24 cm when the river was high. It handles falling rivers well but under-estimates sharp
flood rises. With `river_forecast.use_for_lights: true` (in `config/sources.json`) it sets the River / flood
light for sessions more than 3 hours away (sessions past the 3-day forecast use its last value); nearer
sessions use the live Keilor reading. BOM warnings and Flood Watches still apply on top.

To refit (e.g. after a big event):

```
python3 scripts/fetch_history.py
python3 scripts/fit_river_model.py   # several minutes; writes config/river_model.json
```
