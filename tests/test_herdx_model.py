import tempfile
import unittest
from pathlib import Path

import pandas as pd

from herdx_model import (
    load_model,
    normalize_genetic_group,
    normalize_thi_category,
    predict_milk_yield,
    train_and_save,
)


class HerdXModelTests(unittest.TestCase):
    def test_normalizes_group_and_thi_labels(self):
        self.assertEqual(normalize_genetic_group("HF_62.5"), "HF62.5")
        self.assertEqual(normalize_genetic_group("Local"), "Local")
        self.assertEqual(normalize_thi_category("T2 (≥80)"), "T2")

    def test_rejects_unknown_categories(self):
        with self.assertRaises(ValueError):
            normalize_genetic_group("unknown")
        with self.assertRaises(ValueError):
            normalize_thi_category("T3")

    def test_saved_pipeline_can_be_loaded_for_inference(self):
        training = pd.DataFrame(
            {
                "Genetic Group": [
                    "Local",
                    "Local",
                    "Local",
                    "HF50",
                    "HF50",
                    "HF50",
                ],
                "THI Range": ["T0", "T1", "T2", "T0", "T1", "T2"],
                "Milk Yield (L/day/cow)": [3.0, 2.5, 2.0, 5.0, 4.5, 4.0],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "milk.xlsx"
            model_path = Path(temp_dir) / "model.joblib"
            training.to_excel(data_path, index=False)
            train_and_save(data_path, model_path)
            loaded = load_model(model_path)

        prediction = predict_milk_yield("HF_50", "T1 (75-80)", loaded)
        self.assertTrue(pd.notna(prediction))
        self.assertIsInstance(prediction, float)


if __name__ == "__main__":
    unittest.main()
