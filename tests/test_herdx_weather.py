import unittest
from urllib.error import URLError
from unittest.mock import patch

from herdx_weather import (
    WeatherServiceError,
    _get_json,
    calculate_thi,
    categorize_thi,
    fetch_next_forecast,
    simulate_barn_reading,
)


class HerdXWeatherTests(unittest.TestCase):
    def test_thi_formula_and_boundary_handling(self):
        self.assertAlmostEqual(calculate_thi(25, 70), 73.82)
        self.assertEqual(categorize_thi(75), "T0")
        self.assertEqual(categorize_thi(75.01), "T1")
        self.assertEqual(categorize_thi(80), "T2")

    def test_rejects_invalid_weather_inputs(self):
        with self.assertRaises(ValueError):
            calculate_thi(25, 101)
        with self.assertRaises(ValueError):
            categorize_thi(float("nan"))

    @patch("herdx_weather._get_json")
    def test_fetches_next_hourly_forecast(self, get_json):
        get_json.side_effect = [
            {
                "results": [
                    {
                        "name": "Savar",
                        "country": "Bangladesh",
                        "latitude": 23.85,
                        "longitude": 90.26,
                    }
                ]
            },
            {
                "current": {"time": "2026-11-14T10:00"},
                "hourly": {
                    "time": ["2026-11-14T10:00", "2026-11-14T11:00"],
                    "temperature_2m": [25, 26],
                    "relative_humidity_2m": [70, 65],
                },
            },
        ]

        result = fetch_next_forecast("Savar", "BD")

        self.assertEqual(result["forecast_time"], "2026-11-14T11:00")
        self.assertAlmostEqual(result["thi"], calculate_thi(26, 65))
        self.assertFalse(result["simulated"])
        self.assertIn("not a barn measurement", result["source"])
        forecast_url = get_json.call_args_list[1].args[0]
        self.assertIn("temperature_unit=celsius", forecast_url)

    def test_rejects_missing_forecast_locations(self):
        with patch("herdx_weather._get_json", return_value={"results": []}):
            with self.assertRaises(WeatherServiceError):
                fetch_next_forecast("unknown place")

    @patch("herdx_weather.urlopen", side_effect=URLError("offline"))
    def test_reports_api_connection_failures(self, _urlopen):
        with self.assertRaisesRegex(WeatherServiceError, "Could not reach Open-Meteo"):
            _get_json("https://example.test")

    def test_simulated_reading_is_labeled(self):
        result = simulate_barn_reading(25, 70)
        self.assertTrue(result["simulated"])
        self.assertIn("Simulated", result["source"])
        self.assertEqual(result["thi_category"], "T0")


if __name__ == "__main__":
    unittest.main()
