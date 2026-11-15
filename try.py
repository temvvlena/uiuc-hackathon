"""Play with HerdX: any place, any week, any herd. Prints the table + the first morning text.
Doesn't touch farm.json / farm_demo.json. Sends nothing unless you add --send.

  python try.py                                     # Savar, live 7-day forecast, demo herd
  python try.py --place rangpur --date 2025-05-10    # a past week from weather history
  python try.py --lat 23.0 --lon 89.2 --date 2024-08-01
  python try.py --place chattogram --herd 3,1,0      # 3 Deshi, 1 half-bred, 0 high-bred
  python try.py --price 45 --sentinel half-bred      # milk Tk/L, best cow's type
  python try.py --list                               # named places
"""
import argparse
import copy
import json
import os
from datetime import date, timedelta

from forecast import ATTRIBUTION, WeatherError, fetch_forecast, fetch_history, week_from_today
from messages import herd_loss, is_alert_day, load_table, morning_message, week_total, fmt_l, tk
from sms import send

HERE = os.path.dirname(os.path.abspath(__file__))

PLACES = {  # name: (lat, lon)
    "savar": (23.858, 90.266), "dhaka": (23.810, 90.412), "sirajganj": (24.457, 89.708),
    "shahjadpur": (24.170, 89.600), "chattogram": (22.356, 91.783), "rangpur": (25.746, 89.275),
    "rajshahi": (24.374, 88.604), "khulna": (22.846, 89.540), "sylhet": (24.895, 91.872),
    "barishal": (22.701, 90.353), "mymensingh": (24.747, 90.420), "bogura": (24.849, 89.373),
    "anand": (22.556, 72.951), "nyeri": (-0.420, 36.947), "musanze": (-1.500, 29.633),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--place", default="savar")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--date", help="first day of a past week, YYYY-MM-DD (default: live forecast)")
    ap.add_argument("--herd", default="0,2,2", help="Deshi,half-bred,high-bred counts (default 0,2,2)")
    ap.add_argument("--unknown", type=int, default=0, help="cows of unknown type")
    ap.add_argument("--price", type=float, default=55, help="milk price Tk/L (default 55)")
    ap.add_argument("--sentinel", default="high-bred", choices=["deshi", "half-bred", "high-bred"])
    ap.add_argument("--send", action="store_true", help="actually text FARMER_PHONE")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        for k, (la, lo) in PLACES.items():
            print(f"{k:<12}{la:>8.3f}{lo:>9.3f}")
        return
    if a.lat is not None and a.lon is not None:
        lat, lon, name = a.lat, a.lon, f"{a.lat:.3f}, {a.lon:.3f}"
    else:
        key = a.place.lower()
        if key not in PLACES:
            raise SystemExit(f"Unknown place '{a.place}'. Use --list, or give --lat and --lon.")
        (lat, lon), name = PLACES[key], a.place.title()

    d, h, hb = (int(x) for x in a.herd.split(","))
    with open(os.path.join(HERE, "farm_demo.json")) as f:
        farm = json.load(f)
    farm = copy.deepcopy(farm)
    farm.update(place=name, lat=lat, lon=lon, milk_price_tk=a.price,
                herd={"deshi": d, "half-bred": h, "high-bred": hb, "unknown": a.unknown})
    farm["cows"][0]["type"] = a.sentinel
    table = load_table()

    try:
        if a.date:
            start = date.fromisoformat(a.date)
            hourly = fetch_history(lat, lon, start, start + timedelta(days=6))
            week, note = week_from_today(hourly, start=start), f"History: week of {start}"
        else:
            week, note = week_from_today(fetch_forecast(lat, lon), start=date.today()), "Live 7-day forecast from today"
    except WeatherError as e:
        raise SystemExit(f"{e}\nGuardrail: no forecast -> HerdX would send nothing.")
    if week.empty:
        raise SystemExit("No complete days returned (history lags ~5 days behind today; try an earlier date).")

    price = farm["milk_price_tk"]
    print(f"\n{name} ({lat}, {lon})  |  {note}  |  {ATTRIBUTION}")
    print(f"Herd {farm['herd']}, milk {price:g}/L, best cow: {a.sentinel}\n")
    print(f"{'Day':<12}{'mean THI':>9}{'max':>7}  band  {'hrs>=80':>7}  {'herd loss L/day [range]':<24} text?")
    for r in week.itertuples():
        p, lo, hi = herd_loss(farm["herd"], r.band, table)
        flag = "  >85: beyond study" if r.beyond_study else ""
        txt = "YES" if is_alert_day(r) else "-"
        print(f"{r.date.strftime('%a %d %b'):<12}{r.mean_thi:>9.1f}{r.max_thi:>7.1f}  {r.band:<4}  "
              f"{r.hours_ge80:>7}  {f'{p:.1f} [{lo:.1f}-{hi:.1f}]':<24} {txt}{flag}")
    p, lo, hi = week_total(week, farm, table)
    print(f"\nWeek at stake: {fmt_l(p)} L [{fmt_l(lo)}-{fmt_l(hi)}] ~ {tk(p, price)} [{tk(lo, price)}-{tk(hi, price)}]")
    alerts = [r for r in week.itertuples() if is_alert_day(r)]
    print(f"Texts this week: {len(alerts)} of {len(week)} days")
    if not alerts:
        print("\nNo day reaches heat index 79 -> no texts this week.")
        return
    first = alerts[0]
    print(f"\nFirst text ({first.date.strftime('%a %d %b')} morning):")
    send(morning_message(first, farm, table), dry=not a.send)


if __name__ == "__main__":
    main()
