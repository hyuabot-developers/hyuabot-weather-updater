import logging
from datetime import datetime, timedelta

import pytz
from sqlalchemy import insert, delete
from sqlalchemy.orm import Session

from models import NoticeCategory, Notice
from scripts.observations import WeatherObservation, fetch_kma_observation


def fetch_weather(
    session: Session,
    notice_category: NoticeCategory,
    observation: WeatherObservation | None = None,
):
    now = datetime.now(pytz.timezone('Asia/Seoul'))
    current = observation or fetch_kma_observation(now)
    if current.precipitation_type == 'NONE':
        weather_icon = '☀️'
    elif current.precipitation_type in {'SLEET', 'SNOW'}:
        weather_icon = '🌨️'
    else:
        weather_icon = '🌧️'
    temperature = current.temperature if current.temperature is not None else '--'
    korean_weather_notice = f'[날씨] {weather_icon} / 현재 온도:{temperature}℃'
    english_weather_notice = f'[Weather] {weather_icon} / Temp:{temperature}℃'
    if current.precipitation_amount is not None and current.precipitation_amount > 0:
        korean_weather_notice += f' / 강수량:{current.precipitation_amount:g}mm'
        english_weather_notice += f' / Rain:{current.precipitation_amount:g}mm'
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
