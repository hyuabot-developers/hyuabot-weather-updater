import logging
import os
from datetime import datetime, timedelta
from typing import Any

import pytz

from scripts.http import retrying_session


SERVICE_URL = 'https://apis.data.go.kr/1360000/LivingWthrIdxServiceV4/getUVIdxV4'
SEOUL = pytz.timezone('Asia/Seoul')
ANSAN_AREA_NO = '4127100000'


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get('response', {})
    header = response.get('header', {})
    result_code = str(header.get('resultCode', '00'))
    if result_code != '00':
        raise RuntimeError(f'KMA UV index request failed: {result_code}')
    items = response.get('body', {}).get('items', {}).get('item', [])
    return [items] if isinstance(items, dict) else items or []


def _grade(value: int) -> str:
    if value < 3:
        return '낮음'
    if value < 6:
        return '보통'
    if value < 8:
        return '높음'
    if value < 11:
        return '매우 높음'
    return '위험'


def parse_uv_index(payload: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    items = _items(payload)
    if not items:
        return None
    item = items[0]
    # KMA returns the current value plus forecasts at three-hour offsets.
    candidates = []
    for offset in (0, 3, 6, 9, 12):
        raw = item.get(f'h{offset}')
        if raw is None:
            continue
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            continue
        forecast_at = now + timedelta(hours=offset)
        candidates.append((forecast_at, value))
    if not candidates:
        return None
    forecast_at, value = candidates[0]
    return {'value': value, 'grade': _grade(value), 'forecastAt': forecast_at.isoformat()}


def fetch_uv_index(now: datetime | None = None) -> dict[str, Any] | None:
    api_key = os.getenv('WEATHER_API_KEY')
    if not api_key:
        logging.warning('Skipping UV index API because WEATHER_API_KEY is not set.')
        return None
    current_time = now or datetime.now(SEOUL)
    params = {
        'serviceKey': api_key,
        'pageNo': '1',
        'numOfRows': '10',
        'dataType': 'JSON',
        'areaNo': os.getenv('WEATHER_UV_AREA_NO', ANSAN_AREA_NO),
        'time': current_time.strftime('%Y%m%d%H'),
        'day': 'today',
    }
    with retrying_session() as session:
        response = session.get(SERVICE_URL, params=params, timeout=30)
        response.raise_for_status()
        return parse_uv_index(response.json(), current_time)
