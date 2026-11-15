"""Build HerdX loss table from the Pehan et al. 2026 dataset -> loss_table.json.

Loss = T0 mean milk - band mean milk (L/day/cow), per genetic group.
95% CI = cow-level bootstrap (resample the 10 cows in a group with replacement).
Physio file is linked to the milk file by row position (organizers confirmed;
physio IDs are milk IDs - 1).

Usage: python loss_table.py [DATA_DIR] [--out loss_table.json]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

DEFAULT_DIR = os.path.expanduser(
    "~/Downloads/Physiological responses, Dry matter Intake, milk y")
MILK_FILE = "DMI, milk yield and composition.xlsx"
PHYS_FILE = "physiological responses.xlsx"
GROUPS = ["Local", "HF_50", "HF_62.5", "HF_75", "HF_87.5"]
BANDS = ["T0", "T1", "T2"]
N_BOOT = 10_000
SEED = 42

# Plain-language herd types -> dataset groups
HERD_TYPES = {
    "deshi": ["Local"],
    "half-bred": ["HF_50", "HF_62.5"],
    "high-bred": ["HF_75", "HF_87.5"],
}


def norm_group(g):
    # milk file: "HF50"; physio file: "HF_50" -> both become "HF_50"
    g = str(g).strip().replace(" ", "").replace("_", "").replace("%", "")
    if g.lower().startswith("local"):
        return "Local"
    return "HF_" + g[2:]


def load(data_dir):
    milk = pd.read_excel(os.path.join(data_dir, MILK_FILE))
    phys = pd.read_excel(os.path.join(data_dir, PHYS_FILE))
    assert len(milk) == len(phys) == 750, "expected 750 rows in each file"
    df = pd.DataFrame({
        "cow": milk["Animal ID"].astype(int),
        "group": milk["Genetic Group"].map(norm_group),
        "band": milk["THI Range"].astype(str).str[:2],
        "milk": milk["Milk Yield (L/day/cow)"].astype(float),
        "rr": phys["Respiration Rate (bpm)"].astype(float).values,
    })
    # Row-position link check: same group/band/rep order in both files
    assert (phys["Genetic group"].map(norm_group).values == df["group"].values).all()
    assert (phys["THI Range"].astype(str).str[:2].values == df["band"].values).all()
    assert (phys["Replication No"].values == milk["Replication No"].values).all()
    assert set(df["group"]) == set(GROUPS), set(df["group"])
    df["cow"] = df["group"] + "_" + df["cow"].astype(str)  # cow IDs repeat across groups
    return df


def boot_ci(cow_means, band, rng):
    """cow_means: DataFrame index=cow, columns=bands. Loss = T0 - band."""
    m = cow_means[["T0", band]].to_numpy()
    idx = rng.integers(0, len(m), size=(N_BOOT, len(m)))
    s = m[idx]                                   # (N_BOOT, n_cows, 2)
    losses = s[..., 0].mean(1) - s[..., 1].mean(1)
    lo, hi = np.percentile(losses, [2.5, 97.5])
    return float(lo), float(hi)


def build(df):
    rng = np.random.default_rng(SEED)
    out = {"groups": {}}
    for g in GROUPS:
        d = df[df.group == g]
        milk_cm = d.pivot_table(index="cow", columns="band", values="milk", aggfunc="mean")
        rr_mean = d.groupby("band")["rr"].mean()
        means = d.groupby("band")["milk"].mean()
        entry = {
            "n_cows": int(milk_cm.shape[0]),
            "milk": {b: round(float(means[b]), 3) for b in BANDS},
            "rr": {b: round(float(rr_mean[b]), 1) for b in BANDS},
            "loss": {"T0": 0.0},
            "loss_ci": {"T0": [0.0, 0.0]},
        }
        for b in ["T1", "T2"]:
            entry["loss"][b] = round(float(means["T0"] - means[b]), 3)
            entry["loss_ci"][b] = [round(x, 3) for x in boot_ci(milk_cm, b, rng)]
        out["groups"][g] = entry
    out["herd_types"] = HERD_TYPES
    out["meta"] = {
        "units": "L/day/cow; loss = T0 mean - band mean",
        "ci": f"cow-level bootstrap 95% percentile, {N_BOOT} resamples, seed {SEED}",
        "bands": "daily-mean THI: T0 <75, T1 75-80, T2 >=80 (NRC 1971)",
        "source": "Pehan et al. 2026, Animal - Open Space 5:100139",
    }
    return out


def print_table(t):
    print(f"{'Group':<9}{'T0 milk':>8}  {'T1 loss [95% CI]':<22}{'T2 loss [95% CI]':<22}{'RR T0->T2':>10}")
    for g, e in t["groups"].items():
        c1, c2 = e["loss_ci"]["T1"], e["loss_ci"]["T2"]
        print(f"{g:<9}{e['milk']['T0']:>8.2f}  "
              f"{e['loss']['T1']:.2f} [{c1[0]:.2f}-{c1[1]:.2f}]{'':<6}"
              f"{e['loss']['T2']:.2f} [{c2[0]:.2f}-{c2[1]:.2f}]{'':<6}"
              f"{e['rr']['T0']:.1f}->{e['rr']['T2']:.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", nargs="?", default=DEFAULT_DIR)
    ap.add_argument("--out", default="loss_table.json")
    a = ap.parse_args()
    table = build(load(a.data_dir))
    with open(a.out, "w") as f:
        json.dump(table, f, indent=2)
    print_table(table)
    print(f"\nSaved {a.out}")
