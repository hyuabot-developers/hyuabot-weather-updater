import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytz

from scripts.http import retrying_session


SERVICE_URL = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst'
SEOUL = pytz.timezone('Asia/Seoul')
GRID_X = '57'
GRID_Y = '121'


@dataclass(frozen=True)
class WeatherObservation:
    observed_at: datetime
    temperature: float | None
    precipitation_type: str
    precipitation_amount: float | None


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


def latest_observation_base(now: datetime) -> datetime:
    available_at = now - timedelta(minutes=15)
    return available_at.replace(minute=0, second=0, microsecond=0)


def fetch_kma_observation(now: datetime | None = None) -> WeatherObservation:
    current_time = now or datetime.now(SEOUL)
    base = latest_observation_base(current_time)
    params = {
        'serviceKey': os.environ['WEATHER_API_KEY'],
        'pageNo': '1',
        'numOfRows': '100',
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
        raise RuntimeError(f'KMA observation request failed: {result_code}')
    values = {
        item['category']: item['obsrValue']
        for item in body['body']['items']['item']
        if item['category'] in {'PTY', 'T1H', 'RN1'}
    }
    return WeatherObservation(
        observed_at=base,
        temperature=_number(values.get('T1H')),
        precipitation_type=_precipitation_type(values.get('PTY')),
        precipitation_amount=_number(values.get('RN1')),
    )
