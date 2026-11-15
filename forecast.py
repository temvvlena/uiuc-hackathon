"""Open-Meteo forecast / history -> hourly T, RH (local time) -> daily THI bands.

Weather data by Open-Meteo.com (CC BY 4.0).

  python forecast.py                  # 7-day forecast for the demo farm
  python forecast.py --save-demo-week # fetch a hot July week from history -> data/demo_weather.json
"""
import argparse
import json
import os
from datetime import date, timedelta

import pandas as pd
import requests

from thi import daily_summary

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DEMO_FILE = os.path.join(DATA, "demo_weather.json")
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TZ = "auto"  # each farm's local time (Savar -> Asia/Dhaka, Nyeri -> Africa/Nairobi)
ATTRIBUTION = "Weather data by Open-Meteo.com"


class WeatherError(Exception):
    """Forecast unavailable -> callers send nothing (guardrail)."""


def _to_df(js):
    h = js["hourly"]
    df = pd.DataFrame({"time": h["time"], "temp": h["temperature_2m"],
                       "rh": h["relative_humidity_2m"]})
    return df.dropna()


def fetch_forecast(lat, lon, days=7, timeout=20, tries=2):
    params = {"latitude": lat, "longitude": lon, "timezone": TZ, "forecast_days": days + 1,
              "hourly": "temperature_2m,relative_humidity_2m"}
    err = None
    for _ in range(tries):  # one retry: a single network blip shouldn't cost the farmer a forecast
        try:
            r = requests.get(FORECAST_URL, params=params, timeout=timeout)
            r.raise_for_status()
            df = _to_df(r.json())
            break
        except Exception as e:  # network, HTTP, malformed JSON
            err = e
    else:
        raise WeatherError(f"Open-Meteo forecast failed: {err}") from err
    if df.empty:
        raise WeatherError("Open-Meteo returned no hourly data")
    return df


def fetch_history(lat, lon, start, end, timeout=120):
    params = {"latitude": lat, "longitude": lon, "timezone": TZ,
              "start_date": str(start), "end_date": str(end),
              "hourly": "temperature_2m,relative_humidity_2m"}
    r = requests.get(ARCHIVE_URL, params=params, timeout=timeout)
    r.raise_for_status()
    return _to_df(r.json())


def week_from_today(hourly, start=None, days=7):
    """Daily summary for `days` full days starting `start` (default: tomorrow)."""
    d = daily_summary(hourly)
    start = start or date.today() + timedelta(days=1)
    d = d[d.date >= start].head(days).reset_index(drop=True)
    return d


# ---------- demo weather (stored hot July week) ----------

def pick_demo_week(daily):
    """A July week that reads well in a demo: 2-4 T2 days with cooler days around them
    (so the day-before alert fires). Fallback: hottest 7-day window."""
    best, best_score = None, -1e9
    for i in range(len(daily) - 6):
        w = daily.iloc[i:i + 7]
        n2 = (w.band == "T2").sum()
        starts_cool = w.band.iloc[0] != "T2"
        score = (10 if 2 <= n2 <= 4 else 0) + (5 if starts_cool else 0) + w.mean_thi.max() / 100
        if score > best_score:
            best, best_score = w, score
    return best


def save_demo_week(lat, lon, year=2025):
    hourly = fetch_history(lat, lon, f"{year}-07-01", f"{year}-07-31")
    daily = daily_summary(hourly)
    w = pick_demo_week(daily)
    first, last = w.date.iloc[0], w.date.iloc[-1]
    keep = hourly[(pd.to_datetime(hourly.time).dt.date >= first) &
                  (pd.to_datetime(hourly.time).dt.date <= last)]
    os.makedirs(DATA, exist_ok=True)
    with open(DEMO_FILE, "w") as f:
        json.dump({"source": f"Open-Meteo historical (ERA5), {first} to {last}",
                   "lat": lat, "lon": lon, "hourly": keep.to_dict(orient="list")}, f)
    print(f"Saved {DEMO_FILE}: {first} .. {last}")
    print(daily_summary(keep).to_string(index=False))


def load_demo_week(start=None):
    """Stored July week, re-dated to start today (so weekday names read naturally).
    Returns (hourly_df, note)."""
    if not os.path.exists(DEMO_FILE):
        raise WeatherError(f"{DEMO_FILE} missing - run: python forecast.py --save-demo-week")
    with open(DEMO_FILE) as f:
        js = json.load(f)
    df = pd.DataFrame(js["hourly"])
    t = pd.to_datetime(df["time"])
    start = start or date.today()
    shift = pd.Timestamp(start) - t.dt.normalize().min()
    df["time"] = (t + shift).dt.strftime("%Y-%m-%dT%H:%M")
    return df, f"DEMO WEATHER: replaying {js['source']} as this week"


def get_week(farm, demo=False):
    """7 days starting TODAY (row 0 = today, for the morning text). Returns (daily_df, note).
    Raises WeatherError if the live forecast fails."""
    if demo:
        hourly, note = load_demo_week()
    else:
        hourly, note = fetch_forecast(farm["lat"], farm["lon"]), "Live Open-Meteo forecast"
    return week_from_today(hourly, start=date.today()), note


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-demo-week", action="store_true")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--demo-weather", action="store_true")
    a = ap.parse_args()
    with open(os.path.join(HERE, "farm.json")) as f:
        farm = json.load(f)
    if a.save_demo_week:
        save_demo_week(farm["lat"], farm["lon"], a.year)
    else:
        week, note = get_week(farm, demo=a.demo_weather)
        print(note)
        print(week.to_string(index=False))
        print(ATTRIBUTION)
