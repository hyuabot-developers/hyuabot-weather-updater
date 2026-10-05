import logging
import os
from datetime import datetime, timedelta
from typing import Any

import pytz
import requests
from requests.sessions import HTTPAdapter
from sqlalchemy import insert
from sqlalchemy.orm import Session
from urllib3 import Retry

from models import NoticeCategory, Notice


SERVICE_URL = 'https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty'
SEOUL = pytz.timezone('Asia/Seoul')


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _measured_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return SEOUL.localize(datetime.strptime(value, '%Y-%m-%d %H:%M')).isoformat()
    except ValueError:
        return None


def parse_air_quality(payload: dict[str, Any]) -> dict[str, Any] | None:
    items = payload.get('response', {}).get('body', {}).get('items', [])
    if isinstance(items, dict):
        current_data = items
    elif items:
        current_data = items[0]
    else:
        return None
    return {
        'pm10Value': _integer(current_data.get('pm10Value')),
        'pm10Grade': _integer(current_data.get('pm10Grade')),
        'pm25Value': _integer(current_data.get('pm25Value')),
        'pm25Grade': _integer(current_data.get('pm25Grade')),
        'khaiValue': _integer(current_data.get('khaiValue')),
        'khaiGrade': _integer(current_data.get('khaiGrade')),
        'stationName': current_data.get('stationName'),
        'measuredAt': _measured_at(current_data.get('dataTime')),
    }


def fetch_air_quality() -> dict[str, Any] | None:
    api_key = os.getenv('WEATHER_API_KEY')
    if not api_key:
        logging.warning('Skipping air quality API because WEATHER_API_KEY is not set.')
        return None
    params = {
        'serviceKey': api_key,
        'pageNo': '1',
        'numOfRows': '100',
        'returnType': 'json',
        'stationName': '호수동',
        'dataTerm': 'DAILY',
        'ver': '1.0',
    }
    with requests.Session() as session:
        retries = 5
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        session.mount('https://', HTTPAdapter(max_retries=retry))
        response = session.get(SERVICE_URL, params=params, timeout=30)
        response.raise_for_status()
        return parse_air_quality(response.json())


def publish_dust_notice(session: Session, notice_category: NoticeCategory, air_quality: dict[str, Any]) -> None:
    pm10_value = air_quality.get('pm10Value')
    pm10_grade = air_quality.get('pm10Grade')
    pm25_value = air_quality.get('pm25Value')
    pm25_grade = air_quality.get('pm25Grade')
    if pm10_grade is None or pm25_grade is None:
        return
    korean_grade_dict = {'1': '좋음', '2': '보통', '3': '나쁨', '4': '매우 나쁨'}
    english_grade_dict = {'1': 'Good', '2': 'Moderate', '3': 'Poor', '4': 'Very Poor'}
    korean_dust_notice = (
        f'[미세먼지] 미세먼지: {korean_grade_dict.get(str(pm10_grade), "정보 없음")}({pm10_value}), '
        f'초미세먼지: {korean_grade_dict.get(str(pm25_grade), "정보 없음")}({pm25_value})'
    )
    english_dust_notice = (
        f'[Fine Dust] PM10: {english_grade_dict.get(str(pm10_grade), "Unknown")}({pm10_value}), '
        f'PM2.5: {english_grade_dict.get(str(pm25_grade), "Unknown")}({pm25_value})'
    )
    now = datetime.now(SEOUL)
    session.execute(insert(Notice).values([
        {
            'title': korean_dust_notice,
            'url': '',
            'category_id': notice_category.category_id,
            'user_id': 'admin',
            'language': 'KOREAN',
            'expired_at': now + timedelta(hours=1),
        },
        {
            'title': english_dust_notice,
            'url': '',
            'category_id': notice_category.category_id,
            'user_id': 'admin',
            'language': 'ENGLISH',
            'expired_at': now + timedelta(hours=1),
        },
    ]))
    logging.info('Finish to get dust data.')
    session.commit()


def fetch_dust(session: Session, notice_category: NoticeCategory | None = None) -> dict[str, Any] | None:
    """Compatibility wrapper that preserves the previous notice insertion behavior."""
    air_quality = fetch_air_quality()
    if air_quality is not None and notice_category is not None:
        publish_dust_notice(session, notice_category, air_quality)
    return air_quality
