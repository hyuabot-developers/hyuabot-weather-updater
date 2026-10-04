import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any

import pytz

from scripts.http import retrying_session


SERVICE_URL = 'https://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList'
SEOUL = pytz.timezone('Asia/Seoul')
ANSAN_NEARBY_STATION_ID = '119'  # Suwon synoptic station; confirm coverage when the key is issued.


def _response_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get('response', {})
    header = response.get('header', {})
    result_code = str(header.get('resultCode', '00'))
    if result_code != '00':
        raise RuntimeError(f'KMA warning request failed: {result_code}')
    items = response.get('body', {}).get('items', {}).get('item', [])
    if isinstance(items, dict):
        return [items]
    return items or []


def _issued_at(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return SEOUL.localize(datetime.strptime(str(value), '%Y%m%d%H%M')).isoformat()
    except ValueError:
        return None


def _classify(title: str) -> tuple[str | None, str | None, str | None]:
    kind = next((word for word in ('호우', '대설', '폭염', '한파', '강풍', '풍랑', '태풍', '건조', '안개') if word in title), None)
    level = '경보' if '경보' in title else '주의보' if '주의보' in title else None
    areas = re.findall(r'\[([^\]]+)\]', title)
    area = next((value.strip() for value in areas if any(name in value for name in ('경기', '안산', '수도권'))), None)
    return kind, level, area


def parse_weather_warnings(payload: dict[str, Any], area_filter: str = '안산') -> list[dict[str, Any]]:
    warnings = []
    seen = set()
    for item in _response_items(payload):
        title = str(item.get('title') or '').strip()
        if not title or title in seen or (area_filter and area_filter not in title):
            continue
        seen.add(title)
        kind, level, area = _classify(title)
        warnings.append({
            'title': title,
            'kind': kind,
            'level': level,
            'area': area,
            'issuedAt': _issued_at(item.get('tmFc')),
            'startsAt': None,
            'endsAt': None,
        })
    return warnings


def fetch_weather_warnings(now: datetime | None = None) -> list[dict[str, Any]] | None:
    api_key = os.getenv('WEATHER_API_KEY')
    if not api_key:
        logging.warning('Skipping weather warning API because WEATHER_API_KEY is not set.')
        return None
    current_time = now or datetime.now(SEOUL)
    params = {
        'serviceKey': api_key,
        'pageNo': '1',
        'numOfRows': '100',
        'dataType': 'JSON',
        'stnId': os.getenv('WEATHER_WARNING_STATION_ID', ANSAN_NEARBY_STATION_ID),
        'fromTmFc': (current_time - timedelta(days=1)).strftime('%Y%m%d'),
        'toTmFc': current_time.strftime('%Y%m%d'),
    }
    with retrying_session() as session:
        response = session.get(SERVICE_URL, params=params, timeout=30)
        response.raise_for_status()
        return parse_weather_warnings(response.json(), os.getenv('WEATHER_WARNING_AREA', '안산'))
