# Poznań nightly sky report

`poznan_sky.py` checks tonight's Open-Meteo cloud forecast for Poznań and, if there
are at least 3 consecutive dark hours (sun below −12°) with ≤30% cloud cover,
prints a JSON report with the forecast, the Moon and the most interesting
objects (planets + a curated list of challenging deep-sky targets) well placed
during the clear window. On a cloudy night it prints `{"clear": false, ...}`.

```
python3 -m pip install ephem
python3 scripts/poznan_sky/poznan_sky.py            # tonight
python3 scripts/poznan_sky/poznan_sky.py --date 2026-11-04 --weather-json saved.json
```

Needs network access to `api.open-meteo.com`. Used by a daily scheduled Claude task
that sends a push notification only on clear nights.
