import asyncio
from unittest.mock import Mock

import pytest

import main


def test_execute_script_propagates_home_forecast_failure(monkeypatch):
    session = Mock()
    notice_category = object()
    session.execute.return_value.scalar_one_or_none.return_value = notice_category
    fetch_weather = Mock()
    fetch_dust = Mock()

    def fail_to_publish():
        raise RuntimeError('forecast publish failed')

    monkeypatch.setattr(main, 'publish_home_forecast', fail_to_publish)
    monkeypatch.setattr(main, 'fetch_weather', fetch_weather)
    monkeypatch.setattr(main, 'fetch_dust', fetch_dust)

    with pytest.raises(RuntimeError, match='forecast publish failed'):
        asyncio.run(main.execute_script(session))

    fetch_weather.assert_called_once_with(session, notice_category)
    fetch_dust.assert_called_once_with(session, notice_category)
    session.close.assert_called_once_with()
