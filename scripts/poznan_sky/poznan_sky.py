#!/usr/bin/env python3
"""Nightly sky report for Poznań.

Fetches tonight's cloud forecast from Open-Meteo, decides whether the night
is clear enough for a telescope, and, if it is, lists the most interesting
objects that will be well placed during the clear hours.

Prints JSON to stdout:
  {"clear": false, ...}                      -> cloudy night, send nothing
  {"clear": true, "weather": {...}, "objects": [...], ...}

Usage: python3 poznan_sky.py [--date YYYY-MM-DD] [--weather-json FILE]
Requires: python3 -m pip install ephem
"""
import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import ephem

LAT, LON, ELEV = 52.4064, 16.9252, 80
TZ = ZoneInfo("Europe/Warsaw")
CLOUD_OK = 30        # % total cloud cover counted as "clear enough"
MIN_CLEAR_HOURS = 3  # need at least this many clear dark hours
MIN_ALT = 20         # degrees above horizon for deep-sky objects
FOG_VIS_M = 2000     # visibility below this = fog/mist
FOG_RH = 95          # radiation-fog setup: humidity >= this ...
FOG_SPREAD_C = 1.0   # ... temp - dew point <= this ...
FOG_WIND_KMH = 5     # ... and wind below this

# name, type, RA (h:m:s), Dec (d:m:s), magnitude, rarity 1..5, note
CATALOG = [
    ("NGC 7331 + Квинтет Стефана", "галактики", "22:37:04", "+34:24:56", 9.5, 5, "квинтет — тест для 250 мм+ и тёмного неба"),
    ("NGC 891", "галактика с ребра", "02:22:33", "+42:20:57", 9.9, 5, "тонкая пылевая полоса"),
    ("NGC 4565 (Игла)", "галактика с ребра", "12:36:21", "+25:59:16", 9.6, 4, "длинное веретено с балджем"),
    ("Конская Голова (B33)", "тёмная туманность", "05:40:59", "-02:27:30", 99, 5, "только с H-beta фильтром"),
    ("Вуаль (NGC 6960/6992)", "остаток сверхновой", "20:51:00", "+30:40:00", 7.0, 4, "с OIII фильтром — кружево"),
    ("M1 (Крабовидная)", "остаток сверхновой", "05:34:32", "+22:00:52", 8.4, 3, "остаток вспышки 1054 года"),
    ("M51 (Водоворот)", "галактика", "13:29:53", "+47:11:43", 8.4, 3, "спирали видны в 200 мм"),
    ("M101 (Вертушка)", "галактика", "14:03:13", "+54:20:56", 7.9, 3, "низкая поверхностная яркость"),
    ("M81 + M82", "пара галактик", "09:55:33", "+69:03:55", 6.9, 3, "M82 — сигара с пылевыми прожилками"),
    ("M33 (Треугольник)", "галактика", "01:33:51", "+30:39:37", 5.7, 3, "HII-область NGC 604 видна отдельно"),
    ("M31 + M32 + M110", "галактики", "00:42:44", "+41:16:09", 3.4, 2, "ищи пылевые полосы M31"),
    ("Триплет Льва (M65/M66/NGC 3628)", "галактики", "11:19:00", "+13:20:00", 9.0, 4, "три галактики в одном поле"),
    ("NGC 2903", "галактика", "09:32:10", "+21:30:03", 9.0, 3, "яркая, но малоизвестная"),
    ("M64 (Чёрный Глаз)", "галактика", "12:56:44", "+21:40:58", 8.5, 3, "тёмная пылевая полоса у ядра"),
    ("NGC 253 (Скульптор)", "галактика", "00:47:33", "-25:17:18", 7.1, 4, "низко над горизонтом в Познани"),
    ("M42 + Трапеция", "туманность", "05:35:17", "-05:23:28", 4.0, 2, "ищи звёзды E и F Трапеции"),
    ("NGC 2392 (Эскимос)", "планетарная туманность", "07:29:11", "+20:54:42", 9.1, 4, "лицо в капюшоне при 200x+"),
    ("NGC 7662 (Голубой снежок)", "планетарная туманность", "23:25:54", "+42:32:06", 8.3, 4, "ярко-голубой диск"),
    ("NGC 7009 (Сатурн)", "планетарная туманность", "21:04:11", "-11:21:48", 8.0, 4, "«ушки» при большом увеличении"),
    ("NGC 6543 (Кошачий Глаз)", "планетарная туманность", "17:58:33", "+66:37:59", 8.1, 4, "зеленоватый, держит увеличение"),
    ("NGC 6826 (Мигающая)", "планетарная туманность", "19:44:48", "+50:31:30", 8.8, 4, "исчезает при прямом взгляде"),
    ("M57 (Кольцо)", "планетарная туманность", "18:53:35", "+33:01:45", 8.8, 2, "центральная звезда — вызов"),
    ("M27 (Гантель)", "планетарная туманность", "19:59:36", "+22:43:16", 7.5, 2, "с OIII — «яблоко»"),
    ("M97 (Сова)", "планетарная туманность", "11:14:48", "+55:01:08", 9.9, 4, "два тёмных «глаза»"),
    ("NGC 2158 рядом с M35", "скопления", "06:08:54", "+24:20:00", 5.3, 3, "старое и молодое скопление в одном поле"),
    ("NGC 2438 в M46", "ПТ в скоплении", "07:41:50", "-14:44:00", 6.1, 4, "планетарка на фоне скопления"),
    ("Хи и Аш Персея", "двойное скопление", "02:20:00", "+57:08:00", 4.3, 2, "при малом увеличении"),
    ("M13", "шаровое скопление", "16:41:41", "+36:27:37", 5.8, 2, "рядом пропеллер и NGC 6207"),
    ("M15", "шаровое скопление", "21:29:58", "+12:10:01", 6.2, 3, "внутри — ПТ Pease 1 (вызов)"),
    ("NGC 2264 (Ёлочка + Конус)", "скопление/туманность", "06:41:06", "+09:53:42", 3.9, 3, "S Mon на вершине"),
    ("NGC 2419 (Межгалактический бродяга)", "шаровое скопление", "07:38:08", "+38:52:55", 10.4, 5, "в 300 тыс. св. лет от нас"),
    ("Звезда Хайнда (R Lep)", "углеродная звезда", "04:59:36", "-14:48:23", 7.0, 4, "кроваво-красная"),
    ("Гранатовая звезда (μ Cep)", "красный сверхгигант", "21:43:30", "+58:46:48", 4.0, 3, "глубокий оранжево-красный"),
    ("Альбирео", "двойная звезда", "19:30:43", "+27:57:35", 3.1, 1, "золото + сапфир"),
    ("γ Андромеды (Аламак)", "двойная звезда", "02:03:54", "+42:19:47", 2.1, 2, "оранжевая + голубая"),
    ("ε Лиры", "двойная двойная", "18:44:20", "+39:40:12", 4.7, 3, "делится на 4 при 150x"),
    ("Сигма Ориона", "кратная звезда", "05:38:45", "-02:36:00", 3.8, 3, "рядом Struve 761"),
]

PLANETS = [("Меркурий", ephem.Mercury), ("Венера", ephem.Venus), ("Марс", ephem.Mars),
           ("Юпитер", ephem.Jupiter), ("Сатурн", ephem.Saturn), ("Уран", ephem.Uranus),
           ("Нептун", ephem.Neptune)]
PLANET_NOTE = {"Юпитер": "пояса, БКП, тени спутников", "Сатурн": "кольца и щель Кассини",
               "Марс": "полярная шапка, тёмные области", "Венера": "фаза",
               "Уран": "зеленоватый диск 3.7\"", "Нептун": "голубая точка 2.3\", спутник Тритон",
               "Меркурий": "фаза, низко"}


def observer(dt_utc):
    o = ephem.Observer()
    o.lat, o.lon, o.elevation = str(LAT), str(LON), ELEV
    o.date = ephem.Date(dt_utc)
    o.pressure = 0
    return o


def sun_alt(dt_utc):
    s = ephem.Sun(observer(dt_utc))
    return math.degrees(s.alt)


def dark_hours(night):
    """Hourly local datetimes from 18:00 to 06:00 when the sun is below -12°."""
    start = datetime(night.year, night.month, night.day, 18, tzinfo=TZ)
    out = []
    for i in range(13):
        t = start + timedelta(hours=i)
        if sun_alt(t.astimezone(timezone.utc).replace(tzinfo=None)) < -12:
            out.append(t)
    return out


def fetch_weather():
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&hourly=cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,"
           "visibility,temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m,"
           "precipitation_probability&timezone=Europe%%2FWarsaw&forecast_days=3" % (LAT, LON))
    req = urllib.request.Request(url, headers={"User-Agent": "poznan-sky/1.0"})
    for attempt, pause in enumerate((30, 60, 120, 240, 0)):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            retryable = not isinstance(e, urllib.error.HTTPError) or e.code in (429, 500, 502, 503, 504)
            if not retryable or pause == 0:
                raise
            print(f"weather fetch failed ({e}), retry in {pause}s", file=sys.stderr)
            time.sleep(pause)


def weather_for(hours, data):
    h = data["hourly"]
    idx = {t: i for i, t in enumerate(h["time"])}
    rows = []
    for t in hours:
        i = idx.get(t.strftime("%Y-%m-%dT%H:00"))
        if i is None:
            continue
        rows.append({k: h[k][i] for k in h if k != "time"} | {"time": t.strftime("%H:%M")})
    return rows


def foggy(r):
    """Fog now (low visibility) or radiation fog likely (saturated, calm air)."""
    vis = r.get("visibility")
    if vis is not None and vis < FOG_VIS_M:
        return True
    rh, t, td, wind = (r.get(k) for k in ("relative_humidity_2m", "temperature_2m", "dew_point_2m", "wind_speed_10m"))
    if None in (rh, t, td, wind):
        return False
    return rh >= FOG_RH and t - td <= FOG_SPREAD_C and wind < FOG_WIND_KMH


def usable(r):
    return (r["cloud_cover"] or 0) <= CLOUD_OK and not foggy(r)


def best_window(rows):
    """Longest run of consecutive clear, fog-free hours."""
    best, cur = [], []
    for r in rows:
        if usable(r):
            cur.append(r)
            if len(cur) > len(best):
                best = list(cur)
        else:
            cur = []
    return best


def moon_info(dt_utc):
    m = ephem.Moon(observer(dt_utc))
    return {"illumination_pct": round(m.phase), "alt_deg": round(math.degrees(m.alt))}, m


def objects_tonight(hours_local, moon_pct, moon_up_frac):
    times = [t.astimezone(timezone.utc).replace(tzinfo=None) for t in hours_local]
    result = []

    for name, cls in PLANETS:
        alts, mag = [], None
        for t in times:
            p = cls(observer(t))
            alts.append(math.degrees(p.alt))
            mag = p.mag
        best_i = max(range(len(alts)), key=lambda i: alts[i])
        if alts[best_i] >= 15:
            result.append({"name": name, "type": "планета", "mag": round(mag, 1),
                           "max_alt": round(alts[best_i]), "best_time": hours_local[best_i].strftime("%H:%M"),
                           "note": PLANET_NOTE[name], "score": 6 + alts[best_i] / 30})

    bright_moon = moon_pct > 50 and moon_up_frac > 0.5
    for name, typ, ra, dec, mag, rarity, note in CATALOG:
        star = ephem.FixedBody()
        star._ra, star._dec, star._epoch = ra, dec, ephem.J2000
        alts = []
        for t in times:
            star.compute(observer(t))
            alts.append(math.degrees(star.alt))
        best_i = max(range(len(alts)), key=lambda i: alts[i])
        alt = alts[best_i]
        if alt < MIN_ALT:
            continue
        score = rarity + alt / 45
        faint_diffuse = mag > 7.5 and "звезда" not in typ and "двойн" not in typ
        if bright_moon and faint_diffuse:
            score -= 2.5 * (moon_pct / 100)
        result.append({"name": name, "type": typ, "mag": mag if mag < 50 else None, "max_alt": round(alt),
                       "best_time": hours_local[best_i].strftime("%H:%M"), "note": note, "score": score})

    result.sort(key=lambda o: -o["score"])
    planets = [o for o in result if o["type"] == "планета"]
    others = [o for o in result if o["type"] != "планета"][:7]
    for o in planets + others:
        o.pop("score")
    return planets + others


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="night start date (local), default today")
    ap.add_argument("--weather-json", help="use a saved Open-Meteo response instead of fetching")
    args = ap.parse_args()

    night = date.fromisoformat(args.date) if args.date else datetime.now(TZ).date()
    hours = dark_hours(night)
    data = json.load(open(args.weather_json)) if args.weather_json else fetch_weather()
    rows = weather_for(hours, data)
    window = best_window(rows)

    if len(window) < MIN_CLEAR_HOURS:
        clear_sky = [r for r in rows if (r["cloud_cover"] or 0) <= CLOUD_OK]
        reason = "fog" if clear_sky and sum(map(foggy, clear_sky)) >= len(clear_sky) / 2 else "clouds"
        print(json.dumps({"clear": False, "night": str(night), "reason": reason,
                          "avg_cloud": round(sum(r["cloud_cover"] for r in rows) / max(len(rows), 1)),
                          "fog_hours": [r["time"] for r in rows if foggy(r)]},
                         ensure_ascii=False))
        return

    win_hours = [h for h in hours if h.strftime("%H:%M") in {r["time"] for r in window}]
    mid = win_hours[len(win_hours) // 2].astimezone(timezone.utc).replace(tzinfo=None)
    moon, _ = moon_info(mid)
    moon_up = sum(1 for h in win_hours if ephem.Moon(observer(h.astimezone(timezone.utc).replace(tzinfo=None))).alt > 0)
    moon["up_during_window"] = f"{moon_up}/{len(win_hours)} ч"

    def avg(k):
        vals = [r[k] for r in window if r.get(k) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    report = {
        "clear": True,
        "night": str(night),
        "window": f"{window[0]['time']}–{(win_hours[-1] + timedelta(hours=1)).strftime('%H:%M')}",
        "weather": {"cloud_avg_pct": avg("cloud_cover"), "cloud_high_avg_pct": avg("cloud_cover_high"),
                    "temp_c": avg("temperature_2m"), "humidity_pct": avg("relative_humidity_2m"),
                    "dew_point_c": avg("dew_point_2m"), "wind_kmh": avg("wind_speed_10m"),
                    "visibility_km": round(avg("visibility") / 1000, 1) if avg("visibility") else None,
                    "precip_prob_pct": avg("precipitation_probability"),
                    "hourly": [{"t": r["time"], "cloud": r["cloud_cover"], "temp": r["temperature_2m"], "fog": foggy(r)} for r in rows]},
        "fog_hours": [r["time"] for r in rows if foggy(r)],
        "moon": moon,
        "objects": objects_tonight(win_hours, moon["illumination_pct"], moon_up / len(win_hours)),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
