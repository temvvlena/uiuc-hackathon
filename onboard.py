"""Sign-up by text message + routing of every incoming text to the right farm.

Identity = the sender's phone number (the carrier already authenticates it). One file per farm:
farms/<digits>.json. The demo farm (farm.json, FARMER_PHONE) is used until that phone sends JOIN.

  JOIN -> place -> YES -> herd (L0 H2 X1) -> best milker (L/H/X) -> where cows stay (1/2/3)
       -> milk price -> done + this week's forecast
  A sign-up in progress lives in farms/signup/ and becomes a farm (farms/<digits>.json) only when
  every question is answered. Unfinished sign-ups are deleted after HERDX_SIGNUP_MINUTES (default 60)
  without a reply; STOP during sign-up cancels it. JOIN always starts again from the first question.
  STOP after sign-up -> leave (file kept, inactive). JOIN again restarts.

  python onboard.py --list            # joined farms
  python onboard.py --reset +1309...  # forget one farm (to re-record the sign-up)
"""
import argparse
import json
import os
import re
import time

import requests

from messages import (FARM_FILE, HELP, handle_reply, load_json, load_table, outlook_text,
                      save_farm)

HERE = os.path.dirname(os.path.abspath(__file__))
FARMS = os.path.join(HERE, "farms")
SIGNUPS = os.path.join(FARMS, "signup")
SIGNUP_MINUTES = float(os.getenv("HERDX_SIGNUP_MINUTES", "60"))
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

TYPE_KEYS = {"L": "deshi", "H": "half-bred", "X": "high-bred", "U": "unknown"}
TYPE_WORDS = {"deshi": "local", "half-bred": "half-bred", "high-bred": "high-bred", "unknown": "not sure"}
CURRENCY = {  # ASCII only: a non-ASCII symbol would force 70-char SMS segments
    "BD": "Tk", "IN": "Rs", "PK": "Rs", "NP": "Rs", "LK": "Rs", "KE": "KSh", "TZ": "TSh",
    "UG": "USh", "RW": "RWF", "ET": "Birr", "NG": "NGN", "GH": "GHS", "ZM": "ZMW", "MW": "MWK",
    "ZW": "USD", "ID": "Rp", "PH": "PHP", "VN": "VND", "TH": "THB", "MM": "MMK", "KH": "KHR",
    "BR": "R$", "MX": "MXN", "CO": "COP", "PE": "PEN", "EC": "USD", "US": "USD", "MN": "MNT",
}

ASK_PLACE = "HerdX: Welcome to HerdX. Where is your farm? Send your town or district, for example Dhaka"
ASK_HERD = ("HerdX: How many cows of each type? Use L for local breed, H for half-bred, "
            "X for high-bred and U if not sure. For example L0 H2 X1")
ASK_BEST = "HerdX: Which type is your best milker? Reply L, H or X"
ASK_SHED = ("HerdX: Where do your cows stay on hot days? Reply 1 for a shed with a tin roof, "
            "2 for a shed with a straw roof, or 3 if they are tied outside")
SHEDS = {"1": "tin", "TIN": "tin", "2": "thatch", "STRAW": "thatch", "THATCH": "thatch",
         "3": "outside", "OUTSIDE": "outside", "OUT": "outside"}
SHED_WORDS = {"tin": "tin roof shed", "thatch": "straw roof shed", "outside": "tied outside"}
CANCELLED = "HerdX: Sign up cancelled. Send JOIN to start again."
ASK_PRICE = ("HerdX: What price do you sell 1 litre of milk for? Reply with a number, "
             "for example 50, or send SKIP")
NOT_JOINED = "HerdX: Send JOIN to get heat stress alerts for your dairy cows."


# ---------- storage ----------

def digits(phone):
    return re.sub(r"\D", "", phone or "")


def farm_path(phone):
    return os.path.join(FARMS, f"{digits(phone)}.json")


def load_farm(phone):
    p = farm_path(phone)
    if os.path.exists(p):
        return load_json(p), p
    demo = digits(os.getenv("FARMER_PHONE"))
    if demo and digits(phone)[-10:] == demo[-10:]:
        return load_json(FARM_FILE), FARM_FILE      # demo farm until this phone JOINs
    return None, p


def signup_path(phone):
    return os.path.join(SIGNUPS, f"{digits(phone)}.json")


def save_signup(farm, phone):
    os.makedirs(SIGNUPS, exist_ok=True)
    farm["updated_at"] = time.time()
    save_farm(farm, signup_path(phone))


def purge_stale_signups(now=None):
    """Delete sign-ups with no reply for SIGNUP_MINUTES. Returns the phones removed."""
    now = now or time.time()
    gone = []
    if os.path.isdir(SIGNUPS):
        for f in os.listdir(SIGNUPS):
            p = os.path.join(SIGNUPS, f)
            try:
                fm = load_json(p)
            except Exception:
                continue
            if now - fm.get("updated_at", 0) > SIGNUP_MINUTES * 60:
                os.remove(p)
                gone.append(fm.get("phone", f))
                print(f"[sign up expired, deleted] {fm.get('phone', f)}")
    return gone


def current_question(farm):
    return {"place": ASK_PLACE, "place_confirm": ASK_PLACE, "herd": ASK_HERD, "best": ASK_BEST,
            "shed": ASK_SHED, "price": ASK_PRICE}.get(farm.get("onboarding"), ASK_PLACE)


def new_farm(phone):
    return {"phone": phone, "active": True, "onboarding": "place", "pending_place": None,
            "place": None, "lat": None, "lon": None, "country": None, "currency": "",
            "milk_price_tk": None, "herd": {}, "cows": [], "more": False,
            "pending_checkin": None, "breath_log": [], "milk_log": []}


# ---------- place lookup ----------

def geocode(text):
    """'Nyeri' or 'Nyeri, Kenya' -> best match dict, or None. Raises on network failure."""
    name, _, country = (x.strip() for x in text.partition(","))
    r = requests.get(GEOCODE_URL, params={"name": name, "count": 10, "language": "en",
                                          "format": "json"}, timeout=15)
    r.raise_for_status()
    res = r.json().get("results") or []
    if country:
        res = [x for x in res if country.lower() in (x.get("country", "").lower(),
                                                      x.get("country_code", "").lower())] or res
    return res[0] if res else None


def place_label(g):
    parts = [g.get("name"), g.get("admin1"), g.get("country")]
    out = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return ", ".join(out)


# ---------- conversation ----------

def parse_herd(t):
    pairs = re.findall(r"([LHXU])\s*(\d+)", t.upper())
    if not pairs:
        return None
    herd = {"deshi": 0, "half-bred": 0, "high-bred": 0, "unknown": 0}
    for k, n in pairs:
        herd[TYPE_KEYS[k]] += int(n)
    return herd


def herd_text(herd):
    n = sum(herd.values())
    parts = [f"{v} {TYPE_WORDS[k]}" for k, v in herd.items() if v]
    return f"{n} cow{'s' if n != 1 else ''} ({', '.join(parts)})"


def build_cows(herd, best):
    """Sentinel first (one cow of the best type), then the rest as 'cow 2', 'cow 3', ..."""
    cows = [{"name": "your best cow", "type": best, "sentinel": True, "baseline_counts": []}]
    left = dict(herd)
    left[best] -= 1
    i = 2
    for t, n in left.items():
        for _ in range(max(0, n)):
            cows.append({"name": f"cow {i}", "type": t, "sentinel": False, "baseline_counts": []})
            i += 1
    return cows


def first_forecast(farm, table):
    """Right after joining, once: when the next hot day is. None if the forecast fails."""
    from datetime import date
    from forecast import WeatherError, fetch_forecast, week_from_today
    try:
        week = week_from_today(fetch_forecast(farm["lat"], farm["lon"]), start=date.today())
    except WeatherError as e:
        print(f"[first forecast skipped] {e}")
        return None
    except Exception as e:  # never let a forecast problem break the sign-up
        print(f"[first forecast skipped] {type(e).__name__}: {e}")
        return None
    return outlook_text(week, farm)


def onboarding_step(farm, t, table):
    """Returns a list of reply texts."""
    step = farm["onboarding"]
    up = t.strip().upper()

    if step == "place" and up in ("YES", "Y"):
        return [ASK_PLACE]
    if step in ("place", "place_confirm") and up not in ("YES", "Y"):
        try:
            g = geocode(t)
        except Exception:
            return ["HerdX: Sorry, we couldn't look up places right now. Please send your town again in a few minutes."]
        if not g:
            return [f"HerdX: We could not find {t.strip()}. Send a nearby bigger town, or add the country, for example Nairobi, Kenya"]
        farm["pending_place"] = g
        farm["onboarding"] = "place_confirm"
        return [f"HerdX: Is your farm in {place_label(g)}? Reply YES, or send a nearer town"]

    if step == "place_confirm":  # YES
        g = farm["pending_place"]
        farm.update(place=place_label(g), lat=g["latitude"], lon=g["longitude"],
                    country=g.get("country"), currency=CURRENCY.get(g.get("country_code", ""), ""),
                    pending_place=None, onboarding="herd")
        return [ASK_HERD]

    if step == "herd":
        herd = parse_herd(t)
        if not herd or not 1 <= sum(herd.values()) <= 50:
            return ["HerdX: Please send the number of each type, for example L0 H2 X1. Between 1 and 50 cows."]
        farm["herd"] = herd
        typed = [k for k in ("deshi", "half-bred", "high-bred") if herd[k]]
        if len(typed) <= 1:  # only one known type (or only 'not sure'): no need to ask
            best = typed[0] if typed else "unknown"
            farm.update(cows=build_cows(herd, best), onboarding="shed")
            return [ASK_SHED]
        farm["onboarding"] = "best"
        return [ASK_BEST]

    if step == "best":
        k = TYPE_KEYS.get(up[:1])
        if k not in ("deshi", "half-bred", "high-bred") or not farm["herd"].get(k):
            hv = [c for c, v in TYPE_KEYS.items() if farm["herd"].get(v) and c != "U"]
            have = ", ".join(hv[:-1]) + " or " + hv[-1] if len(hv) > 1 else hv[0]
            return [f"HerdX: Please reply {have} for the type of your best milker."]
        farm.update(cows=build_cows(farm["herd"], k), onboarding="shed")
        return [ASK_SHED]

    if step == "shed":
        shed = SHEDS.get(up.split()[0] if up else "")
        if not shed:
            return [ASK_SHED]
        farm.update(shed=shed, onboarding="price")
        return [ASK_PRICE]

    if step == "price":
        if up == "SKIP":
            farm["milk_price_tk"] = None
        else:
            m = re.fullmatch(r"\D*(\d+(?:\.\d+)?)\D*", t.strip())
            if not m or not 0 < float(m.group(1)) < 1_000_000:
                return ["HerdX: Please reply with the price as a number, for example 50, or send SKIP"]
            farm["milk_price_tk"] = float(m.group(1))
        farm["onboarding"] = None
        c = f"{farm['currency']} " if farm.get("currency") else ""
        price = f", milk {c}{farm['milk_price_tk']:g} per litre" if farm["milk_price_tk"] else ""
        best = next(c["type"] for c in farm["cows"] if c["sentinel"])
        best_txt = f", best cow {TYPE_WORDS[best]}" if best != "unknown" else ""
        done = (f"HerdX: You are signed up. {farm['place'].split(',')[0]}, {farm.get('country') or ''}, "
                f"{herd_text(farm['herd'])}{best_txt}, {SHED_WORDS[farm['shed']]}{price}. "
                "We will text you on hot mornings, and once a year before the hot days. Send STOP to leave or HELP for help.")
        out = [done.replace(", ,", ",")]
        fc = first_forecast(farm, table)
        if fc:
            out.append(fc)
        return out
    return [HELP]


def route(phone, text, table=None):
    """Handle one incoming text. Returns (list of replies, farm or None). Saves the farm."""
    table = table or load_table()
    purge_stale_signups()
    t = text.strip()
    up = t.upper()

    # Sign-up in progress: kept apart until every question is answered
    if up in ("JOIN", "START"):
        su = new_farm(phone)
        save_signup(su, phone)
        return [ASK_PLACE], su
    sp = signup_path(phone)
    if os.path.exists(sp):
        su = load_json(sp)
        if up in ("STOP", "UNSUBSCRIBE", "CANCEL"):
            os.remove(sp)
            return [CANCELLED], None
        replies = [current_question(su)] if up in ("HELP", "?") else onboarding_step(su, t, table)
        if su.get("onboarding"):
            save_signup(su, phone)
        else:                                   # last answer in: now a registered farm
            su.pop("updated_at", None)
            os.makedirs(FARMS, exist_ok=True)
            save_farm(su, farm_path(phone))
            os.remove(sp)
        return replies, su

    farm, path = load_farm(phone)
    if farm is None:
        return [NOT_JOINED], None
    elif up in ("STOP", "UNSUBSCRIBE"):
        farm["active"] = False
        replies = ["HerdX: You have left HerdX and will not get more texts. Send JOIN to come back."]
    elif not farm.get("active", True):
        return [NOT_JOINED], farm
    elif up in ("HELP", "?"):
        replies = [HELP]
    elif farm.get("onboarding"):
        replies = onboarding_step(farm, t, table)
    else:
        replies = [handle_reply(t, farm, table)]

    os.makedirs(FARMS, exist_ok=True)
    save_farm(farm, path)
    return replies, farm


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--reset", metavar="PHONE")
    a = ap.parse_args()
    if a.reset:
        found = False
        for p in (farm_path(a.reset), signup_path(a.reset)):
            if os.path.exists(p):
                os.remove(p)
                print("removed", p)
                found = True
        if not found:
            print("no farm for", a.reset)
    else:
        purge_stale_signups()
        os.makedirs(FARMS, exist_ok=True)
        for f in sorted(x for x in os.listdir(FARMS) if x.endswith(".json")):
            fm = load_json(os.path.join(FARMS, f))
            state = fm.get("onboarding") or ("active" if fm.get("active") else "left")
            print(f"{fm['phone']:<16}{(fm.get('place') or '-'):<40}{state:<14}{fm.get('herd')}")
        if os.path.isdir(SIGNUPS):
            for f in sorted(os.listdir(SIGNUPS)):
                fm = load_json(os.path.join(SIGNUPS, f))
                left = SIGNUP_MINUTES - (time.time() - fm.get("updated_at", 0)) / 60
                print(f"{fm['phone']:<16}{'signing up, at ' + str(fm.get('onboarding')):<40}"
                      f"deleted in {left:.0f} min if no reply")
