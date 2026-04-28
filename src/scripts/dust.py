import logging
import os
from datetime import datetime, timedelta

import pytz
import requests
from requests.sessions import HTTPAdapter
from sqlalchemy import insert
from sqlalchemy.orm import Session
from urllib3 import Retry

from models import NoticeCategory, Notice


def fetch_dust(session: Session, notice_category: NoticeCategory):
    # 미세먼지 조회 API
    now = datetime.now(pytz.timezone('Asia/Seoul'))
    url = 'https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty'
    params = {
        'serviceKey': os.getenv('WEATHER_API_KEY'),
        'pageNo': '1',
        'numOfRows': '100',
        'returnType': 'json',
        'stationName': '호수동',
        'dataTerm': 'DAILY',
        'ver': '1.0'
    }

    with requests.Session() as s:
        retries = 5
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount('https://', adapter)
        weather_response = s.get(url, params=params, timeout=30)
        weather_result = weather_response.json()
        items = weather_result['response']['body']['items']
        if len(items) == 0:
            return None
        current_data = items[0]
        pm10_value = current_data.get('pm10Value')
        pm10_grade = current_data.get('pm10Grade')
        pm25_value = current_data.get('pm25Value')
        pm25_grade = current_data.get('pm25Grade')
        if pm10_grade is None or pm25_grade is None:
            return None
        korean_grade_dict = {
            '1': '좋음',
            '2': '보통',
            '3': '나쁨',
            '4': '매우 나뿜'
        }
        english_grade_dict = {
            '1': 'Good',
            '2': 'Moderate',
            '3': 'Poor',
            '4': 'Very Poor'
        }

        korean_dust_notice = (
            f'[미세먼지] 미세먼지: {korean_grade_dict[pm10_grade]}({pm10_value}), '
            f'초미세먼지: {korean_grade_dict[pm25_grade]}({pm25_value})'
        )
        english_dust_notice = (
            f'[Fine Dust] PM10: {english_grade_dict[pm10_grade]}({pm10_value}), '
            f'PM2.5: {english_grade_dict[pm25_grade]}({pm25_value})'
        )
        insert_notice_stmt = insert(Notice).values([
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
            }
        ])
        session.execute(insert_notice_stmt)
        logging.info("Finish to get dust data.")
        session.commit()
        return None
