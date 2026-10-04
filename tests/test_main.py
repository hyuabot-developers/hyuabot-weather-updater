import asyncio
from unittest.mock import Mock

import main


def test_execute_script_publishes_available_fixture_fields_and_closes_session(monkeypatch):
    monkeypatch.setenv('WEATHER_API_KEY', 'fixture-key')
    session = Mock()
    notice_category = object()
    session.execute.return_value.scalar_one_or_none.return_value = notice_category
    fetch_weather = Mock()
    fetch_air_quality = Mock(return_value={'pm10Value': 18})
    publish_dust_notice = Mock()
    fetch_weather_warnings = Mock(return_value=[])
    fetch_uv_index = Mock(return_value={'value': 2})
    observation = object()
    publish_home_forecast = Mock()
    monkeypatch.setattr(main, 'fetch_kma_observation', Mock(return_value=observation))
    monkeypatch.setattr(main, 'publish_home_forecast', publish_home_forecast)
    monkeypatch.setattr(main, 'fetch_weather', fetch_weather)
    monkeypatch.setattr(main, 'fetch_air_quality', fetch_air_quality)
    monkeypatch.setattr(main, 'publish_dust_notice', publish_dust_notice)
    monkeypatch.setattr(main, 'fetch_weather_warnings', fetch_weather_warnings)
    monkeypatch.setattr(main, 'fetch_uv_index', fetch_uv_index)

    asyncio.run(main.execute_script(session))

    fetch_weather.assert_called_once_with(session, notice_category, observation)
    fetch_air_quality.assert_called_once_with()
    publish_dust_notice.assert_called_once_with(session, notice_category, {'pm10Value': 18})
    publish_home_forecast.assert_called_once_with(
        observation=observation,
        extras={'airQuality': {'pm10Value': 18}, 'warnings': [], 'uvIndex': {'value': 2}},
    )
    session.close.assert_called_once_with()


def test_execute_script_skips_weather_apis_without_key(monkeypatch):
    monkeypatch.delenv('WEATHER_API_KEY', raising=False)
    session = Mock()
    session.execute.return_value.scalar_one_or_none.return_value = object()
    observation = Mock()
    publisher = Mock()
    weather_notice = Mock()
    monkeypatch.setattr(main, 'fetch_kma_observation', observation)
    monkeypatch.setattr(main, 'publish_home_forecast', publisher)
    monkeypatch.setattr(main, 'fetch_weather', weather_notice)

    asyncio.run(main.execute_script(session))

    observation.assert_not_called()
    publisher.assert_not_called()
    weather_notice.assert_not_called()
    session.close.assert_called_once_with()
