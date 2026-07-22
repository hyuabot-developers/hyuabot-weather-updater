from datetime import datetime

import pytz

from scripts.forecast import build_home_forecast, latest_forecast_base


SEOUL = pytz.timezone('Asia/Seoul')


def item(category: str, value: str, hour: str) -> dict[str, str]:
    return {
        'category': category,
        'fcstValue': value,
        'fcstDate': '20260721',
        'fcstTime': hour,
    }


def test_latest_forecast_base_uses_previous_day_before_first_release():
    now = SEOUL.localize(datetime(2026, 7, 21, 1, 30))

    assert latest_forecast_base(now) == SEOUL.localize(datetime(2026, 7, 20, 23, 0))


def test_latest_forecast_base_keeps_same_day_forecast_after_23_release():
    now = SEOUL.localize(datetime(2026, 7, 21, 23, 30))

    assert latest_forecast_base(now) == SEOUL.localize(datetime(2026, 7, 21, 20, 0))


def test_build_home_forecast_prioritizes_upcoming_rain():
    now = SEOUL.localize(datetime(2026, 7, 21, 14, 35))
    issued_at = SEOUL.localize(datetime(2026, 7, 21, 14, 0))
    items = [
        item('TMP', '29', '1400'), item('SKY', '1', '1400'), item('PTY', '0', '1400'), item('POP', '10', '1400'),
        item('TMP', '28', '1500'), item('SKY', '3', '1500'), item('PTY', '0', '1500'), item('POP', '30', '1500'),
        item('TMP', '26', '1600'), item('SKY', '4', '1600'), item('PTY', '1', '1600'), item('POP', '70', '1600'),
        item('TMN', '23', '0600'), item('TMX', '31', '1500'),
    ]

    result = build_home_forecast(items, issued_at, now)

    assert result['currentTemperature'] == 29
    assert result['minimumTemperature'] == 23
    assert result['maximumTemperature'] == 31
    assert result['precipitationProbabilityMax'] == 70
    assert result['precipitationStartAt'] == '2026-07-21T16:00:00+09:00'
    assert result['precipitationType'] == 'RAIN'
    assert result['primaryCondition'] == 'RAIN'
