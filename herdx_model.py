from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "raw" / "DMI, milk yield and composition.xlsx"
MODEL_PATH = ROOT / "models" / "milk_yield_model.joblib"
FEATURE_COLUMNS = ["Genetic_Group", "THI_Category"]
TARGET_COLUMN = "Milk Yield (L/day/cow)"
MODEL_SCHEMA_VERSION = 1

GENETIC_GROUPS = {
    "local": "Local",
    "hf50": "HF50",
    "hf62.5": "HF62.5",
    "hf75": "HF75",
    "hf87.5": "HF87.5",
}


def normalize_genetic_group(value: object) -> str:
    key = re.sub(r"[^a-z0-9.]", "", str(value).strip().lower())
    try:
        return GENETIC_GROUPS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown genetic group: {value!r}") from exc


def normalize_thi_category(value: object) -> str:
    match = re.match(r"^(T[0-2])", str(value).strip())
    if not match:
        raise ValueError(f"Unknown THI category: {value!r}")
    return match.group(1)


def prepare_training_data(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    required = {"Genetic Group", "THI Range", TARGET_COLUMN}
    missing_columns = required - set(frame.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    features = pd.DataFrame(
        {
            "Genetic_Group": frame["Genetic Group"].map(normalize_genetic_group),
            "THI_Category": frame["THI Range"].map(normalize_thi_category),
        }
    )
    target = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce")
    if features.isna().any().any() or target.isna().any():
        raise ValueError("Training data contains missing or non-numeric values")
    if target.empty:
        raise ValueError("Training data contains no observations")
    return features, target


def create_model():
    return make_pipeline(
        OneHotEncoder(handle_unknown="error"),
        LinearRegression(),
    )


def train_and_save(
    data_path: Path = DATA_PATH, model_path: Path = MODEL_PATH
) -> dict[str, Any]:
    raw = pd.read_excel(data_path)
    features, target = prepare_training_data(raw)
    pipeline = create_model()
    pipeline.fit(features[FEATURE_COLUMNS], target)

    artifact = {
        "schema_version": MODEL_SCHEMA_VERSION,
        "features": FEATURE_COLUMNS,
        "target": TARGET_COLUMN,
        "training_rows": len(features),
        "pipeline": pipeline,
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    return artifact


def load_model(model_path: Path = MODEL_PATH) -> dict[str, Any]:
    artifact = joblib.load(model_path)
    if artifact.get("schema_version") != MODEL_SCHEMA_VERSION:
        raise ValueError("Unsupported model artifact schema version")
    if artifact.get("features") != FEATURE_COLUMNS:
        raise ValueError("Model artifact feature schema does not match this code")
    return artifact


def predict_milk_yield(
    genetic_group: object,
    thi_category: object,
    artifact: dict[str, Any] | None = None,
) -> float:
    if artifact is None:
        artifact = load_model()
    features = pd.DataFrame(
        [
            {
                "Genetic_Group": normalize_genetic_group(genetic_group),
                "THI_Category": normalize_thi_category(thi_category),
            }
        ],
        columns=FEATURE_COLUMNS,
    )
    return float(artifact["pipeline"].predict(features)[0])
