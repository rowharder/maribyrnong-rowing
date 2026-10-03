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
   - Open-Meteo: hourly forecast for wind, temperature, rain, fog/visibility and storm potential
2. applies the rules in `scripts/rules.py` using the numbers in `config/thresholds.json`,
3. writes `site/data/latest.json` and publishes the `site/` folder to GitHub Pages.

If a source fails, its lights show grey ("No data – check manually") rather than a false green. If the
whole page is more than 3 hours old, every light turns grey.

## The rules (edit `config/thresholds.json`)

| Factor | Amber | Red |
|---|---|---|
| Wind | ≥10 kn | ≥15 kn |
| Temperature | ≥30 °C, or below 5 °C | ≥35 °C |
| Rain | ≥2 mm/hr | – |
| Storms | thunderstorm forecast | BOM severe thunderstorm/weather warning (Central district) |
| Fog / visibility | <2 km or fog forecast | <1 km |
| Darkness | any part of the session before first light or after last light (civil twilight) | – (red with fog or rain) |
| Tide | outgoing, falling ≥0.1 m/hr | – |
| River / flood | Keilor ≥1.5 m or ≥20 m³/s, upstream rising ≥0.2 m/hr, or Flood Watch | Keilor ≥3.5 m (minor flood), ≥60 m³/s, or a BOM Maribyrnong flood warning |

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
