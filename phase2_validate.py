from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "raw"
KEYS = ["Animal ID", "Genetic_Group", "THI_Category", "Replication_No"]
TARGET = "Milk Yield (L/day/cow)"
THI_LABELS = ["T0", "T1", "T2"]
BLOOD_FEATURES = [
    "Glucose (mmol/L)",
    "Total Protein (g/dL)",
    "Uric Acid (mg/dL)",
    "Cholesterol (mg/dL)",
    "Calcium (mg/dL)",
    "HDL (mg/dL)",
    "AST (U/I)",
    "ALT (U/I)",
    "Cortisol (µg/dL)",
]


def normalize_id(value: object) -> str:
    return str(int(float(value)))


def normalize_group(value: object) -> str:
    return re.sub(r"[^a-z0-9.]", "", str(value).strip().lower())


def normalize_thi(value: object) -> str:
    match = re.match(r"T[0-2]", str(value).strip())
    if not match:
        raise ValueError(f"Unrecognized THI category: {value!r}")
    return match.group()


def standardize_keys(frame: pd.DataFrame, group_column: str) -> pd.DataFrame:
    frame = frame.rename(
        columns={
            group_column: "Genetic_Group",
            "THI Range": "THI_Category",
            "Replication No": "Replication_No",
        }
    ).copy()
    frame["Animal ID"] = frame["Animal ID"].map(normalize_id)
    frame["Genetic_Group"] = frame["Genetic_Group"].map(normalize_group)
    frame["THI_Category"] = frame["THI_Category"].map(normalize_thi)
    frame["Replication_No"] = frame["Replication_No"].astype(str)
    return frame


def load_data(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, ...]:
    milk = standardize_keys(
        pd.read_excel(data_dir / "DMI, milk yield and composition.xlsx"),
        "Genetic Group",
    )
    physiology = standardize_keys(
        pd.read_excel(data_dir / "physiological responses.xlsx"),
        "Genetic group",
    )
    blood = standardize_keys(
        pd.read_excel(data_dir / "Blood metabolites.xlsx"),
        "Genetic Group",
    )
    return milk, physiology, blood


def summarize_joins(
    milk: pd.DataFrame, physiology: pd.DataFrame, blood: pd.DataFrame
) -> None:
    key_sets = {
        "milk": set(map(tuple, milk[KEYS].itertuples(index=False, name=None))),
        "physiology": set(
            map(tuple, physiology[KEYS].itertuples(index=False, name=None))
        ),
        "blood": set(map(tuple, blood[KEYS].itertuples(index=False, name=None))),
    }
    for left, right in (("milk", "blood"), ("milk", "physiology")):
        overlap = key_sets[left] & key_sets[right]
        print(
            f"{left} ↔ {right}: {len(overlap)} matching keys; "
            f"{len(key_sets[left] - overlap)} left-only; "
            f"{len(key_sets[right] - overlap)} right-only"
        )

    physiology_cows = set(physiology["Animal ID"])
    milk_cows = set(milk["Animal ID"])
    print(
        "Unmatched cow IDs (physiology only):",
        sorted(physiology_cows - milk_cows, key=int),
    )
    print(
        "Unmatched cow IDs (milk/blood only):",
        sorted(milk_cows - physiology_cows, key=int),
    )


def build_matched_data(
    milk: pd.DataFrame, physiology: pd.DataFrame, blood: pd.DataFrame
) -> pd.DataFrame:
    physiology_columns = KEYS + [
        "Rectal Temp (F)",
        "Pulse Rate (bpm)",
        "Respiration Rate (bpm)",
    ]
    blood_columns = KEYS + BLOOD_FEATURES
    matched = milk.merge(
        physiology[physiology_columns],
        on=KEYS,
        how="inner",
        validate="one_to_one",
    )
    return matched.merge(
        blood[blood_columns],
        on=KEYS,
        how="inner",
        validate="one_to_one",
    )


def make_regressor(features: list[str], model_name: str):
    categorical = ["Genetic_Group", "THI_Category"]
    numeric = [feature for feature in features if feature not in categorical]
    transformers = [
        ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical)
    ]
    if numeric:
        transformers.append(("numeric", "passthrough", numeric))
    preprocessing = ColumnTransformer(transformers)

    if model_name == "linear":
        estimator = LinearRegression()
    elif model_name == "xgboost":
        estimator = XGBRegressor(
            objective="reg:squarederror",
            n_estimators=150,
            max_depth=2,
            learning_rate=0.04,
            min_child_weight=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=5.0,
            random_state=42,
            n_jobs=1,
            verbosity=0,
        )
    else:
        raise ValueError(f"Unknown model: {model_name}")
    return make_pipeline(preprocessing, estimator)


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    return {
        "R2": r2_score(actual, predicted),
        "MAE": mean_absolute_error(actual, predicted),
        "RMSE": mean_squared_error(actual, predicted) ** 0.5,
    }


def evaluate_regressors(
    frame: pd.DataFrame, label: str, features: list[str]
) -> list[dict[str, object]]:
    actual = frame[TARGET].to_numpy(dtype=float)
    groups = frame["Animal ID"].to_numpy()
    logo = LeaveOneGroupOut()
    predictions = {
        "global-mean baseline": np.empty(len(frame)),
        "genetic-group baseline": np.empty(len(frame)),
        "linear regression": np.empty(len(frame)),
        "XGBoost": np.empty(len(frame)),
    }

    for train_index, test_index in logo.split(frame, actual, groups):
        train = frame.iloc[train_index]
        test = frame.iloc[test_index]
        train_mean = train[TARGET].mean()
        predictions["global-mean baseline"][test_index] = train_mean

        group_means = train.groupby("Genetic_Group")[TARGET].mean()
        predictions["genetic-group baseline"][test_index] = (
            test["Genetic_Group"].map(group_means).fillna(train_mean).to_numpy()
        )
        for model_name, key in (
            ("linear", "linear regression"),
            ("xgboost", "XGBoost"),
        ):
            model = make_regressor(features, model_name)
            model.fit(train[features], train[TARGET])
            predictions[key][test_index] = model.predict(test[features])

    rows = []
    for name, predicted in predictions.items():
        rows.append(
            {
                "dataset": label,
                "model": name,
                **regression_metrics(actual, predicted),
            }
        )
    return rows


def evaluate_respiration(physiology: pd.DataFrame) -> None:
    values = physiology[["Respiration Rate (bpm)"]].to_numpy(dtype=float)
    labels = physiology["THI_Category"].to_numpy()
    groups = physiology["Animal ID"].to_numpy()
    predictions = np.empty(len(physiology), dtype=object)
    logo = LeaveOneGroupOut()

    for train_index, test_index in logo.split(values, labels, groups):
        classifier = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=1000, random_state=42),
        )
        classifier.fit(values[train_index], labels[train_index])
        predictions[test_index] = classifier.predict(values[test_index])

    matrix = confusion_matrix(labels, predictions, labels=THI_LABELS)
    print("\nRespiration-only, leave-one-cow-out THI classification")
    print("Confusion matrix (rows=actual, columns=predicted; T0,T1,T2):")
    print(matrix)

    actual_t2 = labels == "T2"
    predicted_t2 = predictions == "T2"
    true_positive = int(np.sum(actual_t2 & predicted_t2))
    false_negative = int(np.sum(actual_t2 & ~predicted_t2))
    false_positive = int(np.sum(~actual_t2 & predicted_t2))
    true_negative = int(np.sum(~actual_t2 & ~predicted_t2))
    sensitivity = true_positive / (true_positive + false_negative)
    specificity = true_negative / (true_negative + false_positive)
    precision = true_positive / (true_positive + false_positive)
    print(
        "T2 vs T0/T1: "
        f"sensitivity={sensitivity:.3f}, specificity={specificity:.3f}, "
        f"precision={precision:.3f}"
    )


def main() -> None:
    milk, physiology, blood = load_data()
    print("Rows / missing cells:")
    for name, frame in (
        ("milk", milk),
        ("physiology", physiology),
        ("blood", blood),
    ):
        print(f"  {name}: {len(frame)} rows, {int(frame.isna().sum().sum())} missing")
    summarize_joins(milk, physiology, blood)

    matched = build_matched_data(milk, physiology, blood)
    print(f"\nMatched records for sensor/measurement comparisons: {len(matched)}")
    cat_features = ["Genetic_Group", "THI_Category"]
    model_a_features = cat_features
    model_b_features = cat_features + [
        "Rectal Temp (F)",
        "Respiration Rate (bpm)",
    ]
    model_c_features = (
        model_b_features
        + ["Pulse Rate (bpm)", "DMI (kg)"]
        + BLOOD_FEATURES
    )

    results = []
    results.extend(evaluate_regressors(milk, "A: all 50 cows", model_a_features))
    results.extend(
        evaluate_regressors(matched, "A: matched 45 cows", model_a_features)
    )
    results.extend(
        evaluate_regressors(matched, "B: matched 45 cows", model_b_features)
    )
    results.extend(
        evaluate_regressors(matched, "C: matched 45 cows", model_c_features)
    )
    print("\nLOCO milk-yield prediction metrics (out-of-fold predictions):")
    print(
        pd.DataFrame(results)
        .set_index(["dataset", "model"])
        .round(3)
        .to_string()
    )

    evaluate_respiration(physiology)
    print(
        "\nInterpretation limits: no numeric THI, weather, barn sensor, "
        "date/time, or location fields are available. Model B/C inputs have "
        "no timestamps, so their availability before a future milk-yield "
        "prediction cannot be established from these files."
    )


if __name__ == "__main__":
    main()
