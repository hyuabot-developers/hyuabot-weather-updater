import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import pytz
import redis
import requests
from requests.sessions import HTTPAdapter
from urllib3 import Retry


SERVICE_URL = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst'
FORECAST_BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
SEOUL = pytz.timezone('Asia/Seoul')
GRID_X = '57'
GRID_Y = '121'
DEFAULT_REDIS_KEY = 'weather:home:erica'
REDIS_TTL_SECONDS = 4 * 60 * 60
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


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        read=5,
        connect=5,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


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
    with _session() as session:
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


def publish_home_forecast(now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.now(SEOUL)
    issued_at, items = fetch_village_forecast(current_time)
    payload = build_home_forecast(items, issued_at, current_time)
    client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', '6379')),
        decode_responses=True,
    )
    key = os.getenv('WEATHER_FORECAST_REDIS_KEY', DEFAULT_REDIS_KEY)
    client.set(key, json.dumps(payload, ensure_ascii=False, separators=(',', ':')), ex=REDIS_TTL_SECONDS)
    logging.info('Published structured home forecast from %s to %s.', issued_at.isoformat(), key)
    return payload
