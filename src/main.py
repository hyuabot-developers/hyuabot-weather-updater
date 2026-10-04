import asyncio
import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from models import NoticeCategory
from scripts.dust import fetch_air_quality, publish_dust_notice
from scripts.forecast import publish_home_forecast
from scripts.living_index import fetch_uv_index
from scripts.observations import fetch_kma_observation
from scripts.weather import fetch_weather
from scripts.warning import fetch_weather_warnings
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
    notice_category_stmt = select(NoticeCategory).where(NoticeCategory.category_name == '날씨')
    notice_category = session.execute(notice_category_stmt).scalar_one_or_none()
    extras = {}
    observation = None
    if os.getenv('WEATHER_API_KEY'):
        try:
            observation = fetch_kma_observation()
        except Exception:
            logging.warning('Skipping KMA observation API after a failure.', exc_info=True)
        try:
            air_quality = fetch_air_quality()
            if air_quality is not None:
                extras['airQuality'] = air_quality
                if notice_category is not None:
                    publish_dust_notice(session, notice_category, air_quality)
        except Exception:
            logging.warning('Skipping air quality API after a failure.', exc_info=True)
        try:
            warnings = fetch_weather_warnings()
            if warnings is not None:
                extras['warnings'] = warnings
        except Exception:
            logging.warning('Skipping weather warning API after a failure.', exc_info=True)
        try:
            uv_index = fetch_uv_index()
            if uv_index is not None:
                extras['uvIndex'] = uv_index
        except Exception:
            logging.warning('Skipping UV index API after a failure.', exc_info=True)
        if observation is not None:
            try:
                publish_home_forecast(observation=observation, extras=extras)
            except Exception:
                logging.warning('Skipping home forecast publication after a failure.', exc_info=True)
    else:
        logging.warning('Skipping KMA, air quality, warning, and UV APIs because WEATHER_API_KEY is not set.')
    try:
        if notice_category is not None:
            if observation is not None:
                fetch_weather(session, notice_category, observation)
            else:
                logging.warning('Skipping weather notice because no KMA observation is available.')
    finally:
        session.close()
if __name__ == '__main__':
    asyncio.run(main())
