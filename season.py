"""Rare long-term advice: once a year, on a quiet morning just before the hot days start.

What's at stake in a usual year = herd loss on a hot day x hot days per year
                                  + herd loss on a warm day x warm days per year,
with days per year from the farm's weather history (10 years, 2015-2024, Open-Meteo ERA5).
It is milk at stake, not milk saved: the data has no cooling trial, so the text says
fixes "can save part of this" and gives no payback claim.

Prices (Bangladesh only, checked Nov 2026): 18-inch stand fan about Tk 4,300-5,100
(Walton, ula.com.bd). Straw has no price in the text: it swings from Tk 8-10/kg to
Tk 25-30/kg by season (Bangladesh Post, Nov 2025). Straw ceiling under a tin roof:
sheds 5-9 C cooler at peak, more milk (Sahu et al. 2022; Mandal et al. 2018).
"""
import math
import os
from datetime import date

import pandas as pd

from messages import cur, herd_loss, is_alert_day, your_cows

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STORED = [("savar", 23.858, 90.266), ("sirajganj", 24.457, 89.708), ("chattogram", 22.356, 91.783),
          ("rangpur", 25.746, 89.275), ("anand", 22.556, 72.951), ("nyeri", -0.420, 36.947)]
NEAR_KM = 100          # use a stored history if the farm is this close to it
MIN_LITRES = 50        # below this a yearly message isn't worth a text
BIG_LITRES = 200       # a season with this much at stake (about 2 fans' worth at Tk 55) justifies a fan

# Long-term fixes (one line each). Evidence: straw ceiling under tin 5-9 C cooler at peak, more
# milk (Sahu 2022, Mandal 2018); red oxide paint on tin 2-4 F cooler (Khandaker, poultry sheds);
# shade first, then air movement + wetting (extension guidance); air exchange needed for other
# cooling to work; humid air slows evaporation, so moving air matters.
FIX = {
    "straw":  "Straw under the tin roof. It costs little and keeps the shed cooler.",
    "straw?": "If your shed has a tin roof, put straw under it. It keeps the shed cooler.",
    "paint":  "Red oxide paint on the tin roof. It keeps the shed a little cooler.",
    "open":   "Keep the shed sides open so air can move through.",
    "drum":   "A second water drum in the shade, so the cows drink more.",
    "trees":  "Plant trees where the cows are tied. They give free shade for years.",
    "roof":   "A simple roof of bamboo and straw over the cows. It costs little.",
}


def fan_line(farm):
    if farm.get("currency", "Tk") == "Tk":
        return f"A stand fan, about Tk {FAN_TK}, if you have power. It works best on wet cows."
    return "A stand fan, if you have power. It works best on wet cows."


def shed_seems_hot(farm):
    """Breath counts said 'more stressed than the forecast' on a very warm day."""
    return any(b.get("forecast_band") == "T1" and b.get("high") for b in farm.get("breath_log", []))


def pick_fixes(farm, litres):
    """Two long-term fixes for this farm: where the cows stay + how much milk is at stake."""
    big = litres >= BIG_LITRES
    shed = farm.get("shed")
    if shed is None and shed_seems_hot(farm):
        shed = "tin"                      # unknown shed, but counts point to a hot (tin) roof
    if shed == "tin":
        return [FIX["straw"], fan_line(farm) if big else FIX["paint"]]
    if shed == "thatch":
        return [FIX["open"], fan_line(farm) if big else FIX["drum"]]
    if shed == "outside":
        return [FIX["roof"], FIX["trees"]] if big else [FIX["trees"], FIX["roof"]]
    return [FIX["straw?"], fan_line(farm) if big else FIX["drum"]]   # signed up before the question
FAN_TK = "5,000"       # 18-inch stand fan, rounded


def _km(a, b, c, d):
    p = math.pi / 180
    h = (math.sin((c - a) * p / 2) ** 2 +
         math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


HOT_MONTH_SHARE = 0.25   # a month is "hot season" if at least this share of its days would get a text


def _days(daily):
    """Days per year by band, plus the months that are usually hot season."""
    dt = pd.to_datetime(daily["date"])
    years = dt.dt.year.nunique()
    alert = (daily["band"] == "T2") | (daily["mean_thi"] >= 79)   # same rule as the morning text
    share = alert.groupby(dt.dt.month).mean()
    return {"T1": float((daily["band"] == "T1").sum() / years),
            "T2": float((daily["band"] == "T2").sum() / years),
            "hot_months": [int(m) for m, v in share.items() if v >= HOT_MONTH_SHARE]}


def usual_days(farm):
    """Hot (T2) and warm (T1) days per year for this farm, cached in the farm file.
    Nearest stored 10-year history within 100 km, else 3 years fetched live. None if unavailable."""
    if farm.get("usual_year", {}).get("hot_months") is not None:
        return farm["usual_year"]
    lat, lon = farm.get("lat"), farm.get("lon")
    if lat is None:
        return None
    name, km = min(((n, _km(lat, lon, a, b)) for n, a, b in STORED), key=lambda x: x[1])
    if km <= NEAR_KM:
        d = _days(pd.read_csv(os.path.join(DATA, f"history_{name}.csv")))
        d["source"] = f"{name} 2015-2024"
    else:
        try:
            from forecast import fetch_history
            from thi import daily_summary
            y = date.today().year
            d = _days(daily_summary(fetch_history(lat, lon, f"{y - 3}-01-01", f"{y - 1}-12-31")))
            d["source"] = f"farm location {y - 3}-{y - 1}"
        except Exception as e:  # no history -> no yearly text (guardrail)
            print(f"[yearly message skipped] weather history unavailable: {e}")
            return None
    farm["usual_year"] = d
    return d


def year_at_stake(farm, table):
    """Litres at stake for the herd in a usual year, or None."""
    d = usual_days(farm)
    if not d:
        return None
    return (herd_loss(farm["herd"], "T1", table)[0] * d["T1"] +
            herd_loss(farm["herd"], "T2", table)[0] * d["T2"])


def season_message(farm, table):
    p = year_at_stake(farm, table)
    if p is None or p < MIN_LITRES:
        return None
    d = usual_days(farm)
    here = date.today().month in d["hot_months"]
    litres = f"{int(round(p, -1)):,}"
    price = farm.get("milk_price_tk")
    money = f" (about {cur(farm)}{int(round(p * price, -3)):,})" if price else ""
    # Short paragraphs, one fix per line (a line break is 1 character in an SMS)
    return "\n".join([
        f"HerdX: Hot season is {'here' if here else 'coming'}.",
        "",
        # 10-year average per season: "This hot season" before it starts, "Each" once it's under way
        f"The heat {'each hot season' if here else 'this season'} may cost you about {litres} litres of milk{money}.",
        "",
        "These are two recommendations to consider.",
        *pick_fixes(farm, p),
    ])


def season_due(week, farm, idx=0):
    """Today is quiet, a hot or very warm day is coming this week, and no yearly text yet this year."""
    rows = list(week.itertuples())
    return (not is_alert_day(rows[idx]) and farm.get("season_tip_year") != date.today().year
            and any(is_alert_day(r) for r in rows[idx + 1:]))
