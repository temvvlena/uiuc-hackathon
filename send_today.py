"""The morning run (what a scheduler would do at ~6 AM each day): text today's alert, if any.

  python send_today.py                  # demo farm, live forecast for today
  python send_today.py --demo-weather   # stored hot July week; --day picks which day is "today"
  python send_today.py --demo-weather --day 5
  python send_today.py --phone +1309... # a farm that signed up by text
  python send_today.py --dry-run        # print only

Also prints the behind-the-scenes week table. Days below heat index 79 get no text.
"""
import argparse
import sys

from forecast import ATTRIBUTION, WeatherError, get_week
from messages import (FARM_FILE, baseline_request, checkin_days, herd_loss, is_alert_day,
                      load_json, load_table, morning_message, save_farm, week_total, fmt_l, tk)
from season import season_due, season_message, year_at_stake
from sms import send


def behind_the_scenes(week, farm, table, note, today_idx=0):
    price = farm.get("milk_price_tk") or 0
    c = farm.get("currency", "Tk")
    print(f"\n{note}  |  {ATTRIBUTION}")
    print(f"Farm: {farm['place']}, herd {farm['herd']}, milk {c} {price:g}/L\n")
    print(f"   {'Day':<12}{'mean THI':>9}{'max':>7}  band  {'hrs>=80':>7}  {'herd loss L/day [range]':<24} text?")
    for i, r in enumerate(week.itertuples()):
        p, lo, hi = herd_loss(farm["herd"], r.band, table)
        mark = "->" if i == today_idx else "  "
        txt = "YES" if is_alert_day(r) else "-"
        flag = "  >85: beyond study" if r.beyond_study else ""
        print(f"{mark} {r.date.strftime('%a %d %b'):<12}{r.mean_thi:>9.1f}{r.max_thi:>7.1f}  {r.band:<4}  "
              f"{r.hours_ge80:>7}  {f'{p:.1f} [{lo:.1f}-{hi:.1f}]':<24} {txt}{flag}")
    p, lo, hi = week_total(week, farm, table)
    money = f" ~ {c} {tk(p, price)} [{tk(lo, price)}-{tk(hi, price)}]" if price else ""
    print(f"\nWeek at stake: {fmt_l(p)} L [{fmt_l(lo)}-{fmt_l(hi)}]{money}")
    print(f"Texts this week: {sum(is_alert_day(r) for r in week.itertuples())} of {len(week)} days")
    y = year_at_stake(farm, table)
    if y:
        money = f" ~ {c} {int(round(y * price, -3)):,}" if price else ""
        print(f"Usual year at stake: {y:.0f} L{money} (weather history: {farm['usual_year']['source']})")


def todays_text(week, farm, table, idx=0):
    """(text, pending_checkin) for day idx, or (None, None)."""
    r = list(week.itertuples())[idx]
    msg = morning_message(r, farm, table)
    if msg:
        return msg, {"kind": "hot", "date": str(r.date), "band": r.band}
    if any(d == r.date and k == "baseline" for d, k, _ in checkin_days(week, farm)):
        return baseline_request(farm), {"kind": "baseline", "date": str(r.date)}
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-weather", action="store_true")
    ap.add_argument("--day", type=int, default=0, help="which day of the week is 'today' (0-6)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--phone", help="a farm that joined by text")
    a = ap.parse_args(argv)
    table, to, path = load_table(), None, FARM_FILE
    if a.phone:
        from onboard import load_farm
        farm, path = load_farm(a.phone)
        if not farm or farm.get("onboarding") or not farm.get("active", True):
            print(f"No active, fully signed-up farm for {a.phone}.")
            return 1
        to = farm.get("phone", a.phone)
    else:
        farm = load_json(FARM_FILE)
    try:
        week, note = get_week(farm, demo=a.demo_weather)
    except WeatherError as e:
        print(f"{e}\nGuardrail: forecast unavailable -> sending nothing.")
        return 1
    behind_the_scenes(week, farm, table, note, a.day)
    text, pending = todays_text(week, farm, table, a.day)
    if not text and season_due(week, farm, a.day):
        text = season_message(farm, table)
        if text:
            print("\nQuiet day before the hot days -> the once-a-year message.")
            if not a.dry_run:
                from datetime import date
                farm["season_tip_year"] = date.today().year
                save_farm(farm, path)
            send(text, to=to, dry=a.dry_run)
            return 0
    if not text:
        print("\nToday is below heat index 79 -> no text (on purpose).")
        return 0
    farm["pending_checkin"] = pending
    save_farm(farm, path)
    send(text, to=to, dry=a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
