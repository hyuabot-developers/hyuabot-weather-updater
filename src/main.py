import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from models import NoticeCategory
from scripts.dust import fetch_dust
from scripts.forecast import publish_home_forecast
from scripts.observations import fetch_kma_observation
from scripts.weather import fetch_weather
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
    observation = fetch_kma_observation()
    forecast_error: Exception | None = None
    try:
        publish_home_forecast(observation=observation)
    except Exception as error:
        logging.exception("Failed to publish the structured home forecast.")
        forecast_error = error
    try:
        # 날씨 카테고리 검색
        notice_category_stmt = select(NoticeCategory).where(NoticeCategory.category_name == '날씨')
        notice_category = session.execute(notice_category_stmt).scalar_one_or_none()
        if notice_category is not None:
            fetch_weather(session, notice_category, observation)
            fetch_dust(session, notice_category)
    finally:
        session.close()
    if forecast_error is not None:
        raise forecast_error

if __name__ == '__main__':
    asyncio.run(main())
