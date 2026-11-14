# HerdX

HerdX is a dairy-farmer assistant focused on heat stress and group-level milk-yield estimates. This workspace currently contains the research-data validation and baseline model.

## Local research workflow

Place the four provided files in `data/raw/` using these names:

- `metadata.docx`
- `physiological responses.xlsx`
- `DMI, milk yield and composition.xlsx`
- `Blood metabolites.xlsx`

The raw files are git-ignored. Set up the Python environment and run the grouped validation:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python phase2_validate.py
```

XGBoost on macOS also requires the OpenMP runtime (`brew install libomp`).

Train and save the selected one-hot linear-regression pipeline with:

```bash
.venv/bin/python train_milk_model.py
```

The saved artifact includes both the encoder and estimator. Core model inference expects a genetic-group label and a study THI category. The optional weather integration below calculates an estimated THI category from forecast data.

## Weather and shared-sensor inputs

`herdx_weather.py` uses Open-Meteo geocoding and hourly forecast endpoints to get the next hourly 2 m temperature and relative humidity, calculate THI, categorize it, and call the saved milk-yield model. The THI formula is `0.8*T + (RH/100)*(T - 14.4) + 46.4`, where `T` is °C and `RH` is percent. Boundary handling is explicit: THI ≤75 → T0, 75 < THI < 80 → T1, and THI ≥80 → T2. This resolves the overlapping endpoints in the provided category descriptions as a code convention; the workbook contains categories only, so the original study's numeric boundary assignment remains unverified.

Open-Meteo's 2 m forecast is ambient forecast data, not a barn sensor reading. The simulated sensor helper marks its values as simulated. Open-Meteo API use and attribution requirements should be checked before any commercial deployment.

Sources: [Open-Meteo Forecast API](https://open-meteo.com/en/docs), [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api), [dairy THI formula reference](https://veterinaryhandbook.com.au/ContentSection.aspx?id=51).

## Current validation notes

The leave-one-cow-out results and limitations are tracked in GitHub issues #1 and #2. The data contain categorical THI only, no timestamps or barn/weather measurements, and the physiological workbook has an unresolved cow-ID mismatch with the milk/blood workbooks. Do not interpret these results as validation on live weather or sensor readings.
