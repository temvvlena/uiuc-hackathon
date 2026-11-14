from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from herdx_model import predict_milk_yield


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 10


class WeatherServiceError(RuntimeError):
    pass


def calculate_thi(temperature_c: float, relative_humidity_pct: float) -> float:
    if not math.isfinite(temperature_c):
        raise ValueError("Temperature must be a finite number")
    if not math.isfinite(relative_humidity_pct) or not 0 <= relative_humidity_pct <= 100:
        raise ValueError("Relative humidity must be between 0 and 100 percent")
    return (
        0.8 * temperature_c
        + (relative_humidity_pct / 100) * (temperature_c - 14.4)
        + 46.4
    )


def categorize_thi(thi: float) -> str:
    if not math.isfinite(thi):
        raise ValueError("THI must be a finite number")
    if thi <= 75:
        return "T0"
    if thi < 80:
        return "T1"
    return "T2"


def _get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "HerdX/0.1"})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read())
    except HTTPError as exc:
        raise WeatherServiceError(
            f"Open-Meteo returned HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise WeatherServiceError("Could not reach Open-Meteo") from exc
    except TimeoutError as exc:
        raise WeatherServiceError("Open-Meteo request timed out") from exc
    except json.JSONDecodeError as exc:
        raise WeatherServiceError("Open-Meteo returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise WeatherServiceError("Open-Meteo returned an unexpected response")
    return data


def geocode_location(
    location: str, country_code: str | None = None
) -> dict[str, Any]:
    if not location.strip():
        raise ValueError("Location must not be empty")
    params = {"name": location.strip(), "count": 1, "language": "en", "format": "json"}
    if country_code:
        params["countryCode"] = country_code.upper()
    payload = _get_json(f"{GEOCODING_URL}?{urlencode(params)}")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise WeatherServiceError(f"No forecast location found for {location!r}")
    result = results[0]
    try:
        latitude = float(result["latitude"])
        longitude = float(result["longitude"])
        name = str(result["name"])
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherServiceError("Open-Meteo returned invalid location data") from exc
    return {
        "name": name,
        "country": result.get("country"),
        "latitude": latitude,
        "longitude": longitude,
    }


def fetch_next_forecast(
    location: str, country_code: str | None = None
) -> dict[str, Any]:
    resolved = geocode_location(location, country_code)
    params = {
        "latitude": resolved["latitude"],
        "longitude": resolved["longitude"],
        "current": "temperature_2m,relative_humidity_2m",
        "hourly": "temperature_2m,relative_humidity_2m",
        "forecast_days": 2,
        "timezone": "auto",
        "temperature_unit": "celsius",
    }
    payload = _get_json(f"{FORECAST_URL}?{urlencode(params)}")
    current_time = payload.get("current", {}).get("time")
    hourly = payload.get("hourly", {})
    times = hourly.get("time")
    temperatures = hourly.get("temperature_2m")
    humidities = hourly.get("relative_humidity_2m")
    if not isinstance(current_time, str):
        raise WeatherServiceError("Open-Meteo response has no current local time")
    if not all(isinstance(values, list) for values in (times, temperatures, humidities)):
        raise WeatherServiceError("Open-Meteo response has incomplete hourly data")
    if not (len(times) == len(temperatures) == len(humidities)):
        raise WeatherServiceError("Open-Meteo hourly arrays have different lengths")

    next_index = next(
        (i for i, time in enumerate(times) if isinstance(time, str) and time > current_time),
        None,
    )
    if next_index is None:
        raise WeatherServiceError("No future hourly forecast is available")
    try:
        temperature_c = float(temperatures[next_index])
        humidity_pct = float(humidities[next_index])
    except (TypeError, ValueError) as exc:
        raise WeatherServiceError("Open-Meteo forecast contains invalid values") from exc

    thi = calculate_thi(temperature_c, humidity_pct)
    return {
        "location": resolved,
        "forecast_time": times[next_index],
        "temperature_c": temperature_c,
        "relative_humidity_pct": humidity_pct,
        "thi": thi,
        "thi_category": categorize_thi(thi),
        "source": "Open-Meteo hourly forecast at 2 m; not a barn measurement",
        "simulated": False,
    }


def simulate_barn_reading(
    temperature_c: float, relative_humidity_pct: float
) -> dict[str, Any]:
    thi = calculate_thi(temperature_c, relative_humidity_pct)
    return {
        "temperature_c": temperature_c,
        "relative_humidity_pct": relative_humidity_pct,
        "thi": thi,
        "thi_category": categorize_thi(thi),
        "source": "Simulated shared-barn sensor reading",
        "simulated": True,
    }


def predict_from_forecast(
    location: str,
    genetic_group: str,
    country_code: str | None = None,
) -> dict[str, Any]:
    weather = fetch_next_forecast(location, country_code)
    prediction = predict_milk_yield(genetic_group, weather["thi_category"])
    return {
        **weather,
        "genetic_group": genetic_group,
        "predicted_milk_yield_l_per_day_per_cow": prediction,
        "interpretation": (
            "Research-model estimate using forecast-derived THI category; "
            "not validated against measured barn conditions."
        ),
    }
