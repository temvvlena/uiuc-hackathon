"""Static evidence charts (PNG) for the video -> charts/

  python charts.py            # all charts (regional chart fetches 10 yrs of history once, cached in data/)
  python charts.py a b        # only some: a = model comparison, b = RR by grade, c = regional

Weather data by Open-Meteo.com (ERA5 reanalysis via the Historical API).
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from forecast import fetch_history
from thi import daily_summary

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "charts")
DATA = os.path.join(HERE, "data")

# Reference palette (dataviz skill): text inks, surface, blue ordinal ramp, orange pair
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0"
BLUE = "#2a78d6"
BLUE_RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"]   # Local -> HF87.5
T1_COLOR, T2_COLOR = "#f5b48f", "#c94a17"                              # warm / hot (one hue)

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.size": 13, "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": GRID,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 17, "axes.titleweight": "bold", "axes.titlelocation": "left",
})

SOURCE = "Data: Pehan et al. 2026, Animal – Open Space 5:100139 (BLRI Savar, 50 cows)"


def _save(fig, name, note=SOURCE):
    fig.text(0.01, -0.04, note, fontsize=10, color=MUTED, ha="left", va="top")
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("saved", path)


def _title(ax, title, subtitle):
    ax.set_title(title, pad=34, loc="left", x=0)
    ax.text(0, 1.03, subtitle, transform=ax.transAxes, color=INK2, fontsize=12, va="bottom")


# ---------- (a) model comparison ----------

# Leave-one-cow-out (50 folds), milk yield L/day. Source: c2-data-profile.md item 7.
MODELS = [  # label, MAE, R2
    ("Heat index (THI) only", 1.99, -0.02),
    ("HerdX lookup table\n(cow type × heat band)", 0.47, 0.95),
    ("Random forest\n(all 16 features + blood)", 0.51, 0.94),
    ("Gradient boosting\n(all 16 features + blood)", 0.53, 0.93),
]
NOISE_FLOOR = 0.46


def chart_model_comparison():
    fig, ax = plt.subplots(figsize=(11, 5.6))
    labels = [m[0] for m in MODELS][::-1]
    mae = [m[1] for m in MODELS][::-1]
    r2 = [m[2] for m in MODELS][::-1]
    colors = [BLUE if "HerdX" in l else "#b9b8b2" for l in labels]
    bars = ax.barh(labels, mae, color=colors, height=0.6, edgecolor=SURFACE, linewidth=2)
    for b, v, r in zip(bars, mae, r2):
        ax.text(v + 0.03, b.get_y() + b.get_height() / 2, f"{v:.2f} L   R² {r:.2f}",
                va="center", color=INK, fontsize=12)
    ax.axvline(NOISE_FLOOR, color=INK2, ls="--", lw=1.5)
    ax.set_ylim(-0.75, 3.45)
    ax.text(NOISE_FLOOR + 0.03, -0.7, f"noise floor {NOISE_FLOOR} L (day-to-day variation)",
            color=INK2, fontsize=11, va="bottom")
    ax.set_xlim(0, 2.5)
    ax.set_xlabel("Average error predicting a cow's daily milk (L/day) — lower is better")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
    _title(ax, "The simplest model is already at the noise floor", "Leave-one-cow-out test, 50 cows. Blood and physiology add nothing over cow type + heat band.")
    _save(fig, "a_model_comparison.png")


# ---------- (b) respiration rate by grade ----------

GROUP_LABEL = {"Local": "Deshi (local)", "HF_50": "HF 50%", "HF_62.5": "HF 62.5%",
               "HF_75": "HF 75%", "HF_87.5": "HF 87.5%"}


def chart_rr_by_grade():
    with open(os.path.join(HERE, "loss_table.json")) as f:
        t = json.load(f)["groups"]
    fig, ax = plt.subplots(figsize=(10, 6))
    x = [0, 1, 2]
    ends = []
    for (g, e), c in zip(t.items(), BLUE_RAMP):
        y = [e["rr"][b] for b in ["T0", "T1", "T2"]]
        ax.plot(x, y, color=c, lw=2.5, marker="o", ms=8, markeredgecolor=SURFACE, markeredgewidth=2)
        ends.append([y[-1], f"{GROUP_LABEL[g]}  {y[-1]:.0f} (+{y[-1] - y[0]:.0f})", c, y[-1]])
    # de-collide end labels
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 1.1)
    for yy, lab, c, y0 in ends:
        ax.text(2.13, yy, lab, va="center", fontsize=12, color=INK)
        ax.plot([2.03, 2.11], [y0, yy], color=c, lw=1.5)
    ax.set_xticks(x, ["Cool\n(THI <75)", "Warm\n(75–80)", "Hot\n(≥80)"])
    ax.set_xlim(-0.15, 2.9)
    ax.set_ylabel("Respiration rate (breaths/min)")
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    _title(ax, "Breathing rises with heat — most in high-bred cows", "Mean respiration rate by cow type and heat band. "
             "A hot-day rise of ~8–13 breaths/min is countable by eye.")
    _save(fig, "b_rr_by_grade.png")


# ---------- (c) regional comparison ----------

LOCATIONS = [  # name, lat, lon
    ("Savar, BD", 23.858, 90.266),
    ("Sirajganj, BD", 24.457, 89.708),
    ("Chattogram, BD", 22.356, 91.783),
    ("Rangpur, BD", 25.746, 89.275),
    ("Anand, India", 22.556, 72.951),
    ("Nyeri, Kenya (highland)", -0.420, 36.947),
]
YEARS = (2015, 2024)


def history_daily(name, lat, lon):
    """Daily THI summary for 10 years, cached as CSV."""
    os.makedirs(DATA, exist_ok=True)
    slug = name.split(",")[0].lower().replace(" ", "_")
    path = os.path.join(DATA, f"history_{slug}.csv")
    if not os.path.exists(path):
        print(f"fetching {name} {YEARS[0]}-{YEARS[1]} ...")
        h = fetch_history(lat, lon, f"{YEARS[0]}-01-01", f"{YEARS[1]}-12-31")
        daily_summary(h)[["date", "mean_thi", "max_thi", "band"]].to_csv(path, index=False)
    d = pd.read_csv(path, parse_dates=["date"])
    return d


def regional_table():
    with open(os.path.join(HERE, "loss_table.json")) as f:
        t = json.load(f)["groups"]
    hb = {b: sum(t[g]["loss"][b] for g in ["HF_75", "HF_87.5"]) / 2 for b in ["T1", "T2"]}
    rows, savar = [], None
    for name, lat, lon in LOCATIONS:
        d = history_daily(name, lat, lon)
        years = d.date.dt.year.nunique()
        t1 = (d.band == "T1").sum() / years
        t2 = (d.band == "T2").sum() / years
        rows.append({"location": name, "T1_days": t1, "T2_days": t2,
                     "L_per_highbred_cow_yr": t1 * hb["T1"] + t2 * hb["T2"]})
        if name.startswith("Savar"):
            savar = d
    df = pd.DataFrame(rows).sort_values(["T2_days", "T1_days"], ascending=False)
    df.round(1).to_csv(os.path.join(OUT, "c_regional_table.csv"), index=False)
    print(df.round(1).to_string(index=False))
    return df, savar


def chart_regional():
    os.makedirs(OUT, exist_ok=True)
    df, savar = regional_table()
    note = (f"Weather data by Open-Meteo.com (ERA5), {YEARS[0]}–{YEARS[1]}; daily-mean THI (NRC 1971). "
            "Loss: HerdX table, high-bred cow (HF75–87.5).")

    # c1: days per year by band + litres at stake
    fig, ax = plt.subplots(figsize=(11, 5.8))
    y = range(len(df))[::-1]
    ax.barh(y, df.T2_days, color=T2_COLOR, height=0.6, edgecolor=SURFACE, linewidth=2, label="Hot days (THI ≥80)")
    ax.barh(y, df.T1_days, left=df.T2_days, color=T1_COLOR, height=0.6, edgecolor=SURFACE,
            linewidth=2, label="Warm days (75–80)")
    for yy, r in zip(y, df.itertuples()):
        tot = r.T1_days + r.T2_days
        ax.text(tot + 4, yy, f"{r.T2_days:.0f} hot + {r.T1_days:.0f} warm  →  ~{r.L_per_highbred_cow_yr:.0f} L/cow/yr",
                va="center", fontsize=12, color=INK)
    ax.set_yticks(list(y), df.location)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, 365 + 60)
    ax.set_xlabel("Days per year (10-year average)")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False, fontsize=12)
    _title(ax, "Where heat management matters most", "Milk at stake per high-bred cow per year, from each place's weather history.")
    _save(fig, "c_regional_days.png", note)

    # c2: Savar monthly share of hot days -> should reproduce the paper's Jul–Oct hot season
    m = savar.assign(month=savar.date.dt.month).groupby("month").band.apply(
        lambda s: pd.Series({"T2": (s == "T2").mean() * 100, "T1": (s == "T1").mean() * 100})).unstack()
    fig, ax = plt.subplots(figsize=(11, 5.2))
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ax.bar(m.index, m.T2, color=T2_COLOR, width=0.7, edgecolor=SURFACE, linewidth=2, label="Hot (THI ≥80)")
    ax.bar(m.index, m.T1, bottom=m.T2, color=T1_COLOR, width=0.7, edgecolor=SURFACE, linewidth=2,
           label="Warm (75–80)")
    ax.axvspan(6.5, 10.5, color=GRID, alpha=0.6, zorder=0)
    ax.text(8.5, 103, "Study's hot band (T2): Jul–Oct", ha="center", color=INK2, fontsize=12)
    ax.set_xticks(range(1, 13), months)
    ax.set_ylim(0, 112)
    ax.set_ylabel("% of days")
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", frameon=False, fontsize=12)
    _title(ax, "Savar's hot season lines up with the study's, about a month earlier",
           "% of days by heat band, Savar, 10-yr average. Outdoor weather vs the study's in-barn sensors.")
    _save(fig, "c_savar_seasons.png", note)


if __name__ == "__main__":
    which = sys.argv[1:] or ["a", "b", "c"]
    if "a" in which:
        chart_model_comparison()
    if "b" in which:
        chart_rr_by_grade()
    if "c" in which:
        chart_regional()
