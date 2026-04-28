import logging
import os
import re
from datetime import datetime, timedelta

import pytz
import requests
from requests.sessions import HTTPAdapter
from sqlalchemy import insert, delete
from sqlalchemy.orm import Session
from urllib3 import Retry

from models import NoticeCategory, Notice


def fetch_weather(session: Session, notice_category: NoticeCategory):
    # 날씨 조회 API
    now = datetime.now(pytz.timezone('Asia/Seoul'))
    url = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst'
    params = {
        'serviceKey': os.getenv('WEATHER_API_KEY'),
        'pageNo': '1',
        'numOfRows': '100',
        'dataType': 'JSON',
        'base_date': now.strftime('%Y%m%d'),
        'base_time': now.strftime('%H00') if now.minute > 15 else f'{now.hour - 1:02d}00',
        'nx': '57',
        'ny': '121'
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
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        weather_response = s.get(url, params=params, timeout=30)
        weather_result = weather_response.json()
        items = weather_result['response']['body']['items']['item']
        current_weather = {}
        for item in items:
            if item['category'] in ['PTY', 'T1H', 'RN1']:
                current_weather[item['category']] = item['obsrValue']
        if current_weather.get('PTY') == '0':
            weather_icon = '☀️'
        elif current_weather.get('PTY') == '2':
            weather_icon = '🌨️'
        else:
            weather_icon = '🌧️'
        korean_weather_notice = f'[날씨] {weather_icon} / 현재 온도:{current_weather["T1H"]}℃'
        english_weather_notice = f'[Weather] {weather_icon} / Temp:{current_weather["T1H"]}℃'
        if (
            current_weather.get('RN1') is not None and
            re.match(r"^-?\d+\.\d+$", current_weather['RN1']) and
            float(current_weather['RN1']) > 0
        ):
            korean_weather_notice += f' / 강수량:{current_weather["RN1"]}mm'
            english_weather_notice += f' / Rain:{current_weather["RN1"]}mm'
        delete_notice_stmt = delete(Notice).where(Notice.category_id == notice_category.category_id)
        insert_notice_stmt = insert(Notice).values([
            {
                'title': korean_weather_notice,
                'url': '',
                'category_id': notice_category.category_id,
                'user_id': 'admin',
                'language': 'KOREAN',
                'expired_at': now + timedelta(hours=1),
            },
            {
                'title': english_weather_notice,
                'url': '',
                'category_id': notice_category.category_id,
                'user_id': 'admin',
                'language': 'ENGLISH',
                'expired_at': now + timedelta(hours=1),
            }
        ])
        session.execute(delete_notice_stmt)
        session.execute(insert_notice_stmt)
        logging.info("Finish to get weather data.")
        session.commit()
