"""THI (NRC 1971, same formula as Pehan et al. 2026) and daily heat bands."""
import numpy as np
import pandas as pd

T1_MIN, T2_MIN, BEYOND_STUDY = 75.0, 80.0, 85.0
PEAK_HOURS = 4


def thi(temp_c, rh):
    """THI = (1.8T+32) - (0.55 - 0.0055*RH) * (1.8T - 26). Works on scalars or arrays."""
    return (1.8 * temp_c + 32) - (0.55 - 0.0055 * rh) * (1.8 * temp_c - 26)


def band(mean_thi):
    if mean_thi >= T2_MIN:
        return "T2"
    if mean_thi >= T1_MIN:
        return "T1"
    return "T0"


def hot_window(hours):
    """First..last+1 hour with THI >= 80, e.g. (11, 17) or None."""
    return (min(hours), max(hours) + 1) if hours else None


def daily_summary(hourly: pd.DataFrame) -> pd.DataFrame:
    """hourly: columns time (local), temp, rh. Returns one row per full day:
    date, mean_thi, max_thi, band, hours_ge80, hot_window, peak_window, beyond_study."""
    h = hourly.copy()
    h["time"] = pd.to_datetime(h["time"])
    h["thi"] = thi(h["temp"], h["rh"])
    h["date"] = h["time"].dt.date
    rows = []
    for d, g in h.groupby("date"):
        if len(g) < 20:          # skip partial days
            continue
        hot = sorted(g.loc[g.thi >= T2_MIN, "time"].dt.hour.tolist())
        # Peak = the hottest 4 consecutive hours -> "when to cool" in the SMS (a practical window)
        g = g.sort_values("time")
        roll = g.thi.rolling(PEAK_HOURS).mean()
        end = int(np.nanargmax(roll.values)) if roll.notna().any() else len(g) - 1
        peak = g["time"].dt.hour.iloc[max(0, end - PEAK_HOURS + 1):end + 1].tolist()
        m = float(g.thi.mean())
        rows.append({
            "date": d,
            "mean_thi": round(m, 1),
            "max_thi": round(float(g.thi.max()), 1),
            "band": band(m),
            "hours_ge80": len(hot),
            "hot_window": hot_window(hot),
            "peak_window": hot_window(peak),
            "beyond_study": m > BEYOND_STUDY,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    # Sanity checks
    assert abs(thi(25, 50) - 71.8) < 0.1          # mild
    assert band(74.9) == "T0" and band(75) == "T1" and band(80) == "T2"
    print("THI 32C/75% =", round(thi(32, 75), 1), "->", band(thi(32, 75)))
