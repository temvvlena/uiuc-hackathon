"""HerdX SMS templates (A morning alert, C breath check-in, D milk) + reply logic.

All outputs are herd-level. Loss = "milk at stake" (no cooling trial in the data).
"""
import json
import os
import re
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
FARM_FILE = os.path.join(HERE, "farm.json")
TABLE_FILE = os.path.join(HERE, "loss_table.json")

ALL_GROUPS = ["Local", "HF_50", "HF_62.5", "HF_75", "HF_87.5"]
TYPE_LABEL = {"deshi": "Deshi", "half-bred": "half-bred", "high-bred": "high-bred"}
RISE_HIGH = {"high-bred": 8, "half-bred": 6, "deshi": 6}  # bpm rise over baseline -> HIGH
COUNT_MIN, COUNT_MAX, MAX_SPREAD = 10, 40, 5               # 30-s counts
MILK_MAX_PER_COW = 30
HELP = ("HerdX: Send B and your count, for example B 22, for your best cow's breaths in "
        "30 seconds. Send M and litres, for example M 18, for today's milk from all cows. "
        "Send MORE to count 2 or 3 cows.")


# ---------- I/O ----------

def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_farm(farm, path=FARM_FILE):
    with open(path, "w") as f:
        json.dump(farm, f, indent=2, default=str)


def load_table():
    return load_json(TABLE_FILE)


# ---------- herd loss ----------

def groups_for(cow_type, table):
    return table["herd_types"].get(cow_type, ALL_GROUPS)  # unknown -> all groups (range)


def herd_loss(herd, band_, table):
    """Litres/day at stake for the whole herd vs a cool (T0) day.
    point = sum(cows x mean loss of matched groups); range = sum(cows x min CI low .. max CI high)."""
    if band_ == "T0":
        return 0.0, 0.0, 0.0
    point = lo = hi = 0.0
    for cow_type, n in herd.items():
        if not n:
            continue
        gs = [table["groups"][g] for g in groups_for(cow_type, table)]
        point += n * sum(g["loss"][band_] for g in gs) / len(gs)
        lo += n * min(g["loss_ci"][band_][0] for g in gs)
        hi += n * max(g["loss_ci"][band_][1] for g in gs)
    return point, lo, hi


def n_cows(herd):
    return sum(herd.values())


def your_cows(herd):
    """'your cow' / 'your 4 cows'."""
    n = n_cows(herd)
    return "your cow" if n == 1 else f"your {n} cows"


# ---------- formatting helpers ----------

def fmt_l(x):
    return f"{x:.1f}" if x < 10 else f"{x:.0f}"


def tk(litres, price):
    return int(round(litres * price, -1))  # nearest 10 currency units


def cur(farm):
    """Currency label + space ('Tk ', 'KSh '), or '' if unknown."""
    c = farm.get("currency", "Tk")
    return f"{c} " if c else ""


def money_range(p, lo, hi, farm):
    """' (~Tk 220/day, range Tk 150-280)' or '' when the farmer gave no milk price."""
    price, c = farm.get("milk_price_tk"), cur(farm)
    if not price:
        return ""
    return f" (~{c}{tk(p, price)}/day, range {c}{tk(lo, price)}-{tk(hi, price)})"


def money(p, farm):
    """' (~Tk 220)' or ''."""
    price = farm.get("milk_price_tk")
    return f" (about {cur(farm)}{tk(p, price)})" if price else ""


DAY_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_name(d):
    return d.strftime("%a")


def day_span(dates):
    """[Tue, Wed, Thu] -> 'Tue-Thu'; [Mon, Wed] -> 'Mon, Wed' (consecutive runs joined)."""
    dates = sorted(dates)
    runs, cur = [], [dates[0]]
    for d in dates[1:]:
        if (d - cur[-1]).days == 1:
            cur.append(d)
        else:
            runs.append(cur)
            cur = [d]
    runs.append(cur)
    parts = [day_name(r[0]) if len(r) == 1 else f"{day_name(r[0])}-{day_name(r[-1])}" for r in runs]
    return ", ".join(parts)


def hour_12(h):
    h %= 24
    return f"{12 if h % 12 == 0 else h % 12} {'AM' if h < 12 else 'PM'}"


def window_text(windows):
    """Typical hottest stretch across the days (median start/end), not the union of all days."""
    ws = [w for w in windows if w]
    if not ws:
        return "12 to 3 PM"  # study peak hours
    med = lambda xs: sorted(xs)[len(xs) // 2]
    a, b = hour_12(med([w[0] for w in ws])), hour_12(med([w[1] for w in ws]))
    if a[-2:] == b[-2:]:             # "1 PM to 5 PM" -> "1 to 5 PM"
        a = a[:-3]
    return f"{a} to {b}"


def thi_range(rows):
    a, b = round(min(r.mean_thi for r in rows)), round(max(r.mean_thi for r in rows))
    return f"{a}" if a == b else f"{a}-{b}"


# ---------- A. morning alert (one text per day, only on hot or near-hot days) ----------

ALERT_THI = 79.0   # daily-mean heat index that triggers a text: hot days (>=80) + near-hot warm days


def is_alert_day(r):
    return r.band == "T2" or (r.band == "T1" and r.mean_thi >= ALERT_THI)


def week_total(week, farm, table):
    """Litres at stake over the whole week (for the behind-the-scenes view)."""
    tot = [0.0, 0.0, 0.0]
    for r in week.itertuples():
        for i, v in enumerate(herd_loss(farm["herd"], r.band, table)):
            tot[i] += v
    return tuple(tot)


def _who(farm):
    s = sentinel(farm)
    name = s.get("name") or "your best cow"
    if not name.startswith("your"):          # a named cow: say she is the best cow we count
        name = f"your best cow {name}"
    if farm.get("more"):
        others = [c["name"] for c in farm["cows"] if not c.get("sentinel")][:2]
        return f"{name}, then {' and '.join(others)}, for 30 seconds each", "B 22 20 21"
    return (name if name.startswith("your") else name) + " for 30 seconds", "B 22"


def hours_list(hours):
    """[11, 12, 13, 14] -> '11 AM, 12, 1 and 2 PM'; [12, 14] -> '12 and 2 PM'.
    AM/PM on the last hour, and on the first only when it differs."""
    lab = [hour_12(h) for h in hours]
    nums = [x[:-3] for x in lab]
    if len(lab) == 1:
        return lab[0]
    first = lab[0] if lab[0][-2:] != lab[-1][-2:] else nums[0]
    return ", ".join([first] + nums[1:-1]) + " and " + lab[-1]


def wet_hours(r):
    """Clock times to wet the cows: every hour of the hottest 4 hours on a hot day,
    twice (start and start+2) on a very warm day. Soak to the skin, then let it dry:
    a light spray traps hot air in the coat (extension guidance on evaporative cooling)."""
    s, e = r.peak_window or (12, 16)
    return list(range(s, e)) if r.band == "T2" else [s, s + 2]


def feed_after(r):
    """Evening feed after the hot window and not before 6 PM. In the study data cows ate
    9-19% less dry matter on hot days, so feed is moved to the cool hours."""
    _, e = r.peak_window or (12, 16)
    return hour_12(max(18, e))


def morning_message(r, farm, table, checkin=True):
    """r: one day from the forecast table. The day's only text, sent early morning; None on
    days below the alert threshold. Loss is for the whole day; the window says when to act."""
    if not is_alert_day(r):
        return None
    p, lo, hi = herd_loss(farm["herd"], r.band, table)
    hot = r.band == "T2"
    win = window_text([r.peak_window])
    lead = "Hot today" if hot else "Very warm today"
    q = "at least" if r.beyond_study else "about"
    n = n_cows(farm["herd"])
    text = (f"HerdX: {lead}, hottest from {win}. "
            f"{your_cows(farm['herd']).capitalize()} may give {q} {fmt_l(p)} litres less milk today{money(p, farm)}. "
            f"Keep cows and water in shade. "
            + ("Do not walk them in the sun. " if r.beyond_study else "")
            + f"Wet them to the skin at {hours_list(wet_hours(r))}. "
            f"Feed at dawn and after {feed_after(r)}.")
    if checkin:
        who, ex = _who(farm)
        text += f" At 5 PM, count the breaths of {who} and reply, for example {ex}"
    return text


def outlook_text(week, farm):
    """One-time line after sign-up: when the next alert day is (no weekly texts after that)."""
    days = [r for r in week.itertuples() if is_alert_day(r)]
    place = (farm.get("place") or "your farm").split(",")[0]
    if not days:
        return f"HerdX: No heat stress expected at {place} this week. We will text you on hot mornings."
    d = days[0].date
    delta = (d - date.today()).days
    when = "today" if delta == 0 else "tomorrow" if delta == 1 else day_name(d)
    when = when if when in ("today", "tomorrow") else f"on {DAY_FULL[d.weekday()]}"
    return (f"HerdX: The next hot day at {place} is {when}. "
            "We will text you that morning with what to do.")


# ---------- C. breath check-in ----------

def sentinel(farm):
    return next(c for c in farm["cows"] if c.get("sentinel"))


def baseline_request(farm):
    who, ex = _who(farm)
    return (f"HerdX: Today is cool, so we need a normal count. At 5 PM, count the breaths of {who} "
            f"while resting in shade (one in and out of the flank is one breath), "
            f"and reply with the number, for example {ex}")


def checkin_days(week, farm):
    """Ask on hot days (T2) and borderline warm days (mean THI >= 79), plus cool days until the
    sentinel has 2 baseline counts. Ordinary warm days are skipped: the T0->T1 rise (+3-4 bpm)
    is about the size of a counting error, so those counts can't tell us anything."""
    need = max(0, 2 - len(sentinel(farm)["baseline_counts"]))
    plan = []
    for r in week.itertuples():
        if is_alert_day(r):
            plan.append((r.date, "hot", r.band))
        elif need:
            plan.append((r.date, "baseline", r.band))
            need -= 1
    return plan


def _dataset_midpoint(cow_type, table):
    """No baseline yet: midpoint of the dataset's T1 and T2 RR for this cow type (bpm)."""
    gs = [table["groups"][g] for g in groups_for(cow_type, table)]
    return sum((g["rr"]["T1"] + g["rr"]["T2"]) / 2 for g in gs) / len(gs)


def breath_reply(counts, farm, table, today=None):
    """counts: list of 30-s counts (sentinel first). Updates farm in place. Returns reply text."""
    today = today or str(date.today())
    if any(not COUNT_MIN <= c <= COUNT_MAX for c in counts):
        return ("HerdX: That count looks unusual. Please count again for 30 seconds while she rests "
                "in shade, and reply with the number, for example B 22")
    if len(counts) > 1 and max(counts) - min(counts) > MAX_SPREAD:
        return ("HerdX: Those counts are far apart. Please count all cows again in shade, "
                "and reply with the numbers, for example B 22 20 21")
    order = [sentinel(farm)] + [c for c in farm["cows"] if not c.get("sentinel")]
    if len(counts) > len(order):
        return f"HerdX: You have {len(order)} cows with us but sent {len(counts)} counts. Please send again."
    cows = order[:len(counts)]
    bpm = [2 * c for c in counts]
    pending = farm.get("pending_checkin") or {"kind": "hot"}
    farm["breath_log"].append({"date": today, "kind": pending["kind"],
                               "counts": dict(zip([c["name"] for c in cows], counts))})
    farm["pending_checkin"] = None
    def nm(c):
        return c["name"][0].upper() + c["name"][1:]
    if len(cows) == 1:
        confirm = f"Thanks. {nm(cows[0])} is breathing {bpm[0]} times a minute"
    else:
        shown = ", ".join(f"{c['name']} {b}" for c, b in zip(cows, bpm))
        confirm = f"Thanks. Breaths per minute are {shown}"

    if pending["kind"] == "baseline":
        for c, n in zip(cows, counts):
            c["baseline_counts"].append(n)
        left = max(0, 2 - len(cows[0]["baseline_counts"]))
        tail = (f"We saved this as a normal count and need {left} more on a cool day."
                if left else "Her normal count is now saved.")
        return f"HerdX: {confirm}. {tail}"

    # Hot/borderline day: rise over each cow's own baseline
    rises, thresholds = [], []
    for c, b in zip(cows, bpm):
        if c["baseline_counts"]:
            base = 2 * sum(c["baseline_counts"]) / len(c["baseline_counts"])
            rises.append(b - base)
            thresholds.append(RISE_HIGH[c["type"]] if c["type"] in RISE_HIGH else 7)
    if rises:
        rise = sum(rises) / len(rises)
        thr = sum(thresholds) / len(thresholds)
        high = rise >= thr
        ref = "her normal" if len(cows) == 1 else "normal on average"
        d = round(rise)
        note = (f", {d} more than {ref}." if d > 0 else f", {-d} less than {ref}." if d < 0
                else f", same as {ref}.")
        conf = ""
    else:  # no baseline yet -> dataset midpoint, low confidence
        mids = [_dataset_midpoint(c["type"], table) for c in cows]
        high = sum(bpm) / len(bpm) >= sum(mids) / len(mids)
        note, conf = ".", " We have no normal count yet, so this is a rough guess."
    band_ = pending.get("band")          # the forecast band of the day we asked on (None if unprompted)
    farm["breath_log"][-1].update(forecast_band=band_, high=bool(high))
    ask = MILK_ASK if band_ in ("T1", "T2") else ""   # alert days: say what to send next
    return f"HerdX: {confirm}{note} {combine(high, band_, farm, table)}{conf}{ask}"


MILK_ASK = " Tonight, send today's total milk in litres, for example M 18"
WET_NOW = "Wet them to the skin now and again in 2 hours"
SHED_TIP = "Your shed may be hotter than outside. Straw under a tin roof keeps it cooler."


def combine(high, band_, farm, table):
    """Breath count + forecast -> one verdict and what to do this evening. The count can raise a
    'very warm' day to a hot day (e.g. a hot tin-roof shed), but never lowers a hot day: one cow
    can miss a hot day (83-99% caught in simulation)."""
    if band_ == "T2":
        return (f"Heat stress is HIGH, as forecast. {WET_NOW}, and feed them in the cool evening."
                if high else
                "Heat stress is lower than forecast. One cow can miss a hot day, so keep cooling as planned.")
    if band_ == "T1":
        if high:
            p, _, _ = herd_loss(farm["herd"], "T2", table)
            return (f"Your cows are more stressed than the forecast. Treat today as a hot day, with "
                    f"about {fmt_l(p)} litres at stake{money(p, farm)}. {WET_NOW}. {SHED_TIP}")
        return "Heat stress is not high, as expected for today. Keep water full."
    return (f"Heat stress is HIGH. {WET_NOW}." if high
            else "Heat stress is not high. Keep water full.")


# ---------- D. milk feedback ----------

def milk_reply(litres, farm, today=None):
    n = n_cows(farm["herd"])
    if not 0 <= litres <= MILK_MAX_PER_COW * n:
        return (f"HerdX: {litres:g} litres from {your_cows(farm['herd'])} looks unusual. Please send today's total milk "
                "again, for example M 18")
    farm["milk_log"].append({"date": today or str(date.today()), "litres": litres})
    return (f"HerdX: Thanks. We noted {litres:g} litres today from {your_cows(farm['herd'])}. "
            "HerdX will use this to check its forecasts for your farm.")


# ---------- parser ----------

def handle_reply(text, farm, table, today=None):
    """Keyword parser: 'B 22', 'B 22 20 21', 'M 18', 'MORE', 'HELP'. Updates farm in place."""
    t = text.strip().upper()
    if t in ("HELP", "?"):
        return HELP
    if t == "MORE":
        others = [c["name"] for c in farm["cows"] if not c.get("sentinel")][:2]
        if not others:
            return "HerdX: You have 1 cow on file, so one count is all we need."
        farm["more"] = True
        return (f"HerdX: OK. On hot days, count {sentinel(farm)['name']} first, then "
                f"{' and '.join(others)}, and reply with all the numbers, for example B 22 20 21")
    m = re.fullmatch(r"B\s*((?:\d+\s*)+)", t)
    if m:
        return breath_reply([int(x) for x in m.group(1).split()], farm, table, today)
    m = re.fullmatch(r"M\s*(\d+(?:\.\d+)?)", t)
    if m:
        return milk_reply(float(m.group(1)), farm, today)
    return "HerdX: Sorry, I didn't understand. " + HELP.split(": ", 1)[1]
