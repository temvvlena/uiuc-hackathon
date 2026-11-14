import math
import unittest

from herdx_weather import predict_from_forecast


class HerdXE2ETests(unittest.TestCase):
    def test_location_forecast_to_milk_yield_prediction(self):
        result = predict_from_forecast("Dhaka", "Local", country_code="BD")

        self.assertEqual(result["genetic_group"], "Local")
        self.assertTrue(result["forecast_time"])
        self.assertTrue(math.isfinite(result["temperature_c"]))
        self.assertGreaterEqual(result["relative_humidity_pct"], 0)
        self.assertLessEqual(result["relative_humidity_pct"], 100)
        self.assertTrue(math.isfinite(result["thi"]))
        self.assertIn(result["thi_category"], {"T0", "T1", "T2"})
        self.assertTrue(
            math.isfinite(result["predicted_milk_yield_l_per_day_per_cow"])
        )
        self.assertFalse(result["simulated"])
        self.assertIn("not a barn measurement", result["source"])
        self.assertIn("not validated", result["interpretation"])


if __name__ == "__main__":
    unittest.main()
