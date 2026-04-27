import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

import pytz
import requests
from sqlalchemy import select, insert, delete
from sqlalchemy.orm import sessionmaker

from models import NoticeCategory, Notice
from utils.database import get_db_engine


async def main():
    connection = get_db_engine()
    session_constructor = sessionmaker(bind=connection)
    session = session_constructor()
    if session is None:
        raise RuntimeError("Failed to get db session")
    await execute_script(session)


async def execute_script(session):
    logging.info("Start to get weather data.")
    # 날씨 카테고리 검색
    notice_category_stmt = select(NoticeCategory).where(NoticeCategory.category_name == '날씨')
    notice_category = session.execute(notice_category_stmt).scalar_one_or_none()
    if notice_category is None:
        return
    # 날씨 조회 API
    now = datetime.now(pytz.timezone('Asia/Seoul'))
    url = 'https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst'
    params = {
        'serviceKey': os.getenv('WEATHER_API_KEY'),
        'pageNo': '1',
        'numOfRows': '100',
        'dataType': 'JSON',
        'base_date': now.strftime('%Y%m%d'),
        'base_time': now.strftime('%H00') if now.minute > 15 else f'{now.hour - 1}00',
        'nx': '57',
        'ny': '121'
    }

    weather_response = requests.get(url, params=params)
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
    session.close()

if __name__ == '__main__':
    asyncio.run(main())
