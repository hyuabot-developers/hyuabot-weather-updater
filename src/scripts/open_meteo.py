from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytz

from scripts.http import retrying_session


BASE_URL = 'https://api.open-meteo.com'
SEOUL = pytz.timezone('Asia/Seoul')
CAMPUS_LATITUDE = 37.2964
CAMPUS_LONGITUDE = 126.835
HOURLY_VARIABLES = (
    'temperature_2m',
    'precipitation_probability',
    'precipitation',
    'rain',
    'snowfall',
    'weather_code',
)


@dataclass(frozen=True)
class ForecastSource:
    name: str
    path: str
    model: str


SOURCES = (
    ForecastSource('JMA_MSM', '/v1/jma', 'jma_msm'),
    ForecastSource('ECMWF_IFS', '/v1/ecmwf', 'ecmwf_ifs025'),
    ForecastSource('GFS_GLOBAL', '/v1/gfs', 'gfs_global'),
)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _at(values: list[Any] | None, index: int) -> Any:
    if values is None or index >= len(values):
        return None
    return values[index]


def _precipitation_type(rain: float | None, snowfall: float | None, code: int | None) -> str:
    if snowfall is not None and snowfall > 0 and rain is not None and rain > 0:
        return 'SLEET'
    if snowfall is not None and snowfall > 0:
        return 'SNOW'
    if rain is not None and rain > 0:
        return 'RAIN'
    if code in {66, 67}:
        return 'SLEET'
    if code is not None and (51 <= code <= 65 or 80 <= code <= 82 or code >= 95):
        return 'RAIN'
    if code is not None and 71 <= code <= 77:
        return 'SNOW'
    return 'NONE'


def fetch_model_forecast(source: ForecastSource) -> dict[str, Any]:
    params: dict[str, str | float | int] = {
        'latitude': CAMPUS_LATITUDE,
        'longitude': CAMPUS_LONGITUDE,
        'models': source.model,
        'hourly': ','.join(HOURLY_VARIABLES),
        'timezone': 'Asia/Seoul',
        'forecast_days': 2,
    }
    with retrying_session() as session:
        response = session.get(f'{BASE_URL}{source.path}', params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()

    hourly = payload['hourly']
    normalized = []
    for index, timestamp in enumerate(hourly['time']):
        rain = _number(_at(hourly.get('rain'), index))
        snowfall = _number(_at(hourly.get('snowfall'), index))
        precipitation = _number(_at(hourly.get('precipitation'), index))
        code_value = _number(_at(hourly.get('weather_code'), index))
        code = int(code_value) if code_value is not None else None
        probability_value = _number(_at(hourly.get('precipitation_probability'), index))
        normalized.append({
            'forecastAt': SEOUL.localize(datetime.fromisoformat(timestamp)).isoformat(),
            'temperature': _number(_at(hourly.get('temperature_2m'), index)),
            'precipitationProbability': (
                int(probability_value) if probability_value is not None else None
            ),
            'precipitationAmount': precipitation,
            'precipitationType': _precipitation_type(rain, snowfall, code),
            'weatherCode': code,
        })
    return {
        'source': source.name,
        'latitude': payload.get('latitude'),
        'longitude': payload.get('longitude'),
        'generationTimeMs': payload.get('generationtime_ms'),
        'hourly': normalized,
    }


def fetch_all_model_forecasts() -> tuple[list[dict[str, Any]], dict[str, str]]:
    forecasts = []
    failures = {}
    for source in SOURCES:
        try:
            forecasts.append(fetch_model_forecast(source))
        except Exception as error:
            failures[source.name] = f'{type(error).__name__}: {error}'
    if not forecasts:
        raise RuntimeError('All Open-Meteo forecast sources failed')
    return forecasts, failures
