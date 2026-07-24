import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import Any

import pytz
import redis

from scripts.http import retrying_session
from scripts.observations import WeatherObservation
from scripts.open_meteo import fetch_all_model_forecasts


SERVICE_URL = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst'
FORECAST_BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
SEOUL = pytz.timezone('Asia/Seoul')
GRID_X = '57'
GRID_Y = '121'
DEFAULT_REDIS_KEY = 'weather:home:erica'
DEFAULT_SHADOW_REDIS_KEY = 'weather:home:erica:shadow'
DEFAULT_EVALUATION_REDIS_KEY = 'weather:home:erica:evaluation'
REDIS_TTL_SECONDS = 4 * 60 * 60
EVALUATION_TTL_SECONDS = 15 * 24 * 60 * 60
EVALUATION_MAX_ENTRIES = 720
PAYLOAD_FRESHNESS = timedelta(hours=2)


def latest_forecast_base(now: datetime) -> datetime:
    available_at = now - timedelta(minutes=15)
    candidates = [hour for hour in FORECAST_BASE_HOURS if hour <= available_at.hour]
    if candidates:
        latest_hour = candidates[-1]
        # The 23:00 release starts at midnight on the following day. Keep the
        # 20:00 release for the final hour of today's summary.
        if latest_hour == 23:
            latest_hour = 20
        return available_at.replace(hour=latest_hour, minute=0, second=0, microsecond=0)
    previous_day = available_at - timedelta(days=1)
    return previous_day.replace(hour=FORECAST_BASE_HOURS[-1], minute=0, second=0, microsecond=0)


def fetch_village_forecast(now: datetime) -> tuple[datetime, list[dict[str, Any]]]:
    base = latest_forecast_base(now)
    params = {
        'serviceKey': os.environ['WEATHER_API_KEY'],
        'pageNo': '1',
        'numOfRows': '1000',
        'dataType': 'JSON',
        'base_date': base.strftime('%Y%m%d'),
        'base_time': base.strftime('%H%M'),
        'nx': GRID_X,
        'ny': GRID_Y,
    }
    with retrying_session() as session:
        response = session.get(SERVICE_URL, params=params, timeout=30)
        response.raise_for_status()
        body = response.json()['response']
    result_code = str(body['header']['resultCode'])
    if result_code != '00':
        raise RuntimeError(f'KMA forecast request failed: {result_code}')
    return base, body['body']['items']['item']


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _precipitation_type(value: Any) -> str:
    return {
        '0': 'NONE',
        '1': 'RAIN',
        '2': 'SLEET',
        '3': 'SNOW',
        '5': 'RAIN',
        '6': 'SLEET',
        '7': 'SNOW',
    }.get(str(value), 'NONE')


def _sky_condition(value: Any) -> str:
    return {
        '1': 'CLEAR',
        '3': 'MOSTLY_CLOUDY',
        '4': 'CLOUDY',
    }.get(str(value), 'CLOUDY')


def build_home_forecast(items: list[dict[str, Any]], issued_at: datetime, now: datetime) -> dict[str, Any]:
    hourly_by_time: dict[datetime, dict[str, Any]] = {}
    daily_minimum: float | None = None
    daily_maximum: float | None = None

    for item in items:
        forecast_at = SEOUL.localize(datetime.strptime(
            f"{item['fcstDate']}{item['fcstTime']}",
            '%Y%m%d%H%M',
        ))
        if forecast_at.date() != now.date():
            continue
        category = item['category']
        value = item['fcstValue']
        hour = hourly_by_time.setdefault(forecast_at, {'forecastAt': forecast_at.isoformat()})
        if category == 'TMP':
            hour['temperature'] = _number(value)
        elif category == 'TMN':
            daily_minimum = _number(value)
        elif category == 'TMX':
            daily_maximum = _number(value)
        elif category == 'SKY':
            hour['condition'] = _sky_condition(value)
        elif category == 'PTY':
            hour['precipitationType'] = _precipitation_type(value)
        elif category == 'POP':
            hour['precipitationProbability'] = int(float(value))
        elif category == 'PCP':
            hour['precipitationAmount'] = _number(value)

    current_hour = now.replace(minute=0, second=0, microsecond=0)
    all_today = [hourly_by_time[key] for key in sorted(hourly_by_time)]
    remaining = [hour for hour in all_today if datetime.fromisoformat(hour['forecastAt']) >= current_hour]
    if not remaining:
        raise RuntimeError('KMA response did not include a remaining forecast for today')

    temperatures = [hour['temperature'] for hour in all_today if hour.get('temperature') is not None]
    if daily_minimum is None and temperatures:
        daily_minimum = min(temperatures)
    if daily_maximum is None and temperatures:
        daily_maximum = max(temperatures)

    precipitation_hours = [hour for hour in remaining if hour.get('precipitationType', 'NONE') != 'NONE']
    first_precipitation = precipitation_hours[0] if precipitation_hours else None
    if first_precipitation:
        primary_condition = first_precipitation['precipitationType']
    else:
        conditions = Counter(hour.get('condition', 'CLOUDY') for hour in remaining)
        primary_condition = conditions.most_common(1)[0][0]

    probabilities = [hour.get('precipitationProbability', 0) for hour in remaining]
    current_temperature = remaining[0].get('temperature')
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return {
        'version': 1,
        'campus': 'ERICA',
        'issuedAt': issued_at.isoformat(),
        'generatedAt': now.isoformat(),
        'expiresAt': min(now + PAYLOAD_FRESHNESS, end_of_day).isoformat(),
        'date': now.date().isoformat(),
        'currentTemperature': current_temperature,
        'minimumTemperature': daily_minimum,
        'maximumTemperature': daily_maximum,
        'precipitationProbabilityMax': max(probabilities, default=0),
        'precipitationStartAt': first_precipitation['forecastAt'] if first_precipitation else None,
        'precipitationType': first_precipitation['precipitationType'] if first_precipitation else 'NONE',
        'primaryCondition': primary_condition,
        'hourly': remaining,
    }


def _weather_condition(code: int | None) -> str:
    if code is None:
        return 'CLOUDY'
    if code == 0:
        return 'CLEAR'
    if code in {1, 2}:
        return 'MOSTLY_CLOUDY'
    if code == 3 or 45 <= code <= 48:
        return 'CLOUDY'
    if code in {66, 67}:
        return 'SLEET'
    if 71 <= code <= 77:
        return 'SNOW'
    if 51 <= code <= 65 or 80 <= code <= 82 or code >= 95:
        return 'RAIN'
    return 'CLOUDY'


def _confidence(agreeing: int, available: int) -> str:
    if available >= 3 and agreeing == available:
        return 'HIGH'
    if agreeing >= 2:
        return 'MEDIUM'
    return 'LOW'


def build_consensus_forecast(
    forecasts: list[dict[str, Any]],
    observation: WeatherObservation,
    failures: dict[str, str],
    now: datetime,
) -> dict[str, Any]:
    by_time: dict[str, list[dict[str, Any]]] = {}
    source_status = []
    for forecast in forecasts:
        source_status.append({'source': forecast['source'], 'status': 'AVAILABLE'})
        for hour in forecast['hourly']:
            forecast_at = datetime.fromisoformat(hour['forecastAt'])
            if forecast_at.date() == now.date() and forecast_at >= now.replace(minute=0, second=0, microsecond=0):
                by_time.setdefault(hour['forecastAt'], []).append(hour)
    source_status.extend(
        {'source': source, 'status': 'FAILED', 'error': error}
        for source, error in failures.items()
    )
    if not by_time:
        raise RuntimeError('Model forecasts did not include a remaining forecast for today')

    hourly: list[dict[str, Any]] = []
    for forecast_at_value in sorted(by_time):
        entries = by_time[forecast_at_value]
        temperatures = [entry['temperature'] for entry in entries if entry.get('temperature') is not None]
        probabilities = [
            entry['precipitationProbability']
            for entry in entries
            if entry.get('precipitationProbability') is not None
        ]
        precipitation_entries = [
            entry for entry in entries
            if entry.get('precipitationType', 'NONE') != 'NONE'
            or (entry.get('precipitationAmount') or 0) >= 0.1
        ]
        type_counts = Counter(
            entry.get('precipitationType', 'NONE')
            for entry in precipitation_entries
            if entry.get('precipitationType', 'NONE') != 'NONE'
        )
        agreeing = len(precipitation_entries)
        available = len(entries)
        threshold = 2 if available >= 3 else 1
        has_precipitation = agreeing >= threshold
        precipitation_type = (
            type_counts.most_common(1)[0][0]
            if has_precipitation and type_counts
            else 'NONE'
        )
        code_counts = Counter(
            entry.get('weatherCode')
            for entry in entries
            if entry.get('weatherCode') is not None
        )
        weather_code = code_counts.most_common(1)[0][0] if code_counts else None
        condition = precipitation_type if precipitation_type != 'NONE' else _weather_condition(weather_code)
        hourly.append({
            'forecastAt': forecast_at_value,
            'temperature': round(median(temperatures), 1) if temperatures else None,
            'precipitationProbability': round(median(probabilities)) if probabilities else None,
            'precipitationType': precipitation_type,
            'condition': condition,
            'agreeingModelCount': agreeing,
            'availableModelCount': available,
            'confidence': _confidence(agreeing, available) if has_precipitation else None,
        })

    precipitation_hours = [hour for hour in hourly if hour['precipitationType'] != 'NONE']
    first_precipitation = precipitation_hours[0] if precipitation_hours else None
    precipitation_end_at = None
    if first_precipitation is not None:
        start_index = hourly.index(first_precipitation)
        final = first_precipitation
        for hour in hourly[start_index + 1:]:
            previous_at = datetime.fromisoformat(final['forecastAt'])
            current_at = datetime.fromisoformat(hour['forecastAt'])
            if hour['precipitationType'] == 'NONE' or current_at - previous_at > timedelta(hours=1):
                break
            final = hour
        precipitation_end_at = (
            datetime.fromisoformat(final['forecastAt']) + timedelta(hours=1)
        ).isoformat()

    temperatures = [hour['temperature'] for hour in hourly if hour.get('temperature') is not None]
    probabilities = [
        hour['precipitationProbability']
        for hour in hourly
        if hour.get('precipitationProbability') is not None
    ]
    primary_condition = (
        observation.precipitation_type
        if observation.precipitation_type != 'NONE'
        else hourly[0]['condition']
    )
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return {
        'version': 2,
        'campus': 'ERICA',
        'issuedAt': now.isoformat(),
        'generatedAt': now.isoformat(),
        'forecastUpdatedAt': now.isoformat(),
        'expiresAt': min(now + PAYLOAD_FRESHNESS, end_of_day).isoformat(),
        'date': now.date().isoformat(),
        'observedAt': observation.observed_at.isoformat(),
        'currentTemperature': observation.temperature,
        'currentPrecipitationType': observation.precipitation_type,
        'currentPrecipitationAmount': observation.precipitation_amount,
        'minimumTemperature': min(temperatures) if temperatures else None,
        'maximumTemperature': max(temperatures) if temperatures else None,
        'precipitationProbabilityMax': max(probabilities, default=0),
        'precipitationStartAt': first_precipitation['forecastAt'] if first_precipitation else None,
        'precipitationEndAt': precipitation_end_at,
        'precipitationType': first_precipitation['precipitationType'] if first_precipitation else 'NONE',
        'precipitationConfidence': first_precipitation['confidence'] if first_precipitation else None,
        'availableModelCount': len(forecasts),
        'agreeingModelCount': first_precipitation['agreeingModelCount'] if first_precipitation else 0,
        'primaryCondition': primary_condition,
        'sources': source_status,
        'hourly': hourly,
        'attribution': 'Weather forecast data by Open-Meteo.com',
    }


def publish_home_forecast(
    now: datetime | None = None,
    observation: WeatherObservation | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(SEOUL)
    issued_at, items = fetch_village_forecast(current_time)
    legacy_payload = build_home_forecast(items, issued_at, current_time)
    current_observation = observation
    if current_observation is None:
        from scripts.observations import fetch_kma_observation
        current_observation = fetch_kma_observation(current_time)
    forecasts, failures = fetch_all_model_forecasts()
    ensemble_payload = build_consensus_forecast(
        forecasts,
        current_observation,
        failures,
        current_time,
    )
    client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', '6379')),
        decode_responses=True,
    )
    key = os.getenv('WEATHER_FORECAST_REDIS_KEY', DEFAULT_REDIS_KEY)
    shadow_key = os.getenv('WEATHER_FORECAST_SHADOW_REDIS_KEY', DEFAULT_SHADOW_REDIS_KEY)
    evaluation_key = os.getenv('WEATHER_FORECAST_EVALUATION_REDIS_KEY', DEFAULT_EVALUATION_REDIS_KEY)
    mode = os.getenv('HOME_WEATHER_ENSEMBLE_MODE', 'shadow').lower()
    primary_payload = ensemble_payload if mode == 'active' else legacy_payload
    client.set(
        key,
        json.dumps(primary_payload, ensure_ascii=False, separators=(',', ':')),
        ex=REDIS_TTL_SECONDS,
    )
    client.set(
        shadow_key,
        json.dumps(ensemble_payload, ensure_ascii=False, separators=(',', ':')),
        ex=REDIS_TTL_SECONDS,
    )
    evaluation = {
        'generatedAt': current_time.isoformat(),
        'observation': {
            'observedAt': current_observation.observed_at.isoformat(),
            'temperature': current_observation.temperature,
            'precipitationType': current_observation.precipitation_type,
            'precipitationAmount': current_observation.precipitation_amount,
        },
        'legacy': {
            'precipitationStartAt': legacy_payload['precipitationStartAt'],
            'precipitationType': legacy_payload['precipitationType'],
        },
        'ensemble': {
            'precipitationStartAt': ensemble_payload['precipitationStartAt'],
            'precipitationType': ensemble_payload['precipitationType'],
            'precipitationConfidence': ensemble_payload['precipitationConfidence'],
            'availableModelCount': ensemble_payload['availableModelCount'],
            'agreeingModelCount': ensemble_payload['agreeingModelCount'],
        },
        'failures': failures,
    }
    client.lpush(
        evaluation_key,
        json.dumps(evaluation, ensure_ascii=False, separators=(',', ':')),
    )
    client.ltrim(evaluation_key, 0, EVALUATION_MAX_ENTRIES - 1)
    client.expire(evaluation_key, EVALUATION_TTL_SECONDS)
    logging.info(
        'Published %s home forecast to %s and ensemble diagnostics to %s.',
        mode,
        key,
        shadow_key,
    )
    return primary_payload
