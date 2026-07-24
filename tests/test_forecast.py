from datetime import datetime

import pytz

from scripts.forecast import (
    build_consensus_forecast,
    build_home_forecast,
    latest_forecast_base,
)
from scripts.observations import WeatherObservation


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


def model(name: str, hours: list[dict]) -> dict:
    return {
        'source': name,
        'hourly': hours,
    }


def forecast_hour(
    hour: int,
    temperature: float,
    precipitation_type: str = 'NONE',
    probability: int | None = None,
    amount: float = 0,
    weather_code: int = 0,
) -> dict:
    return {
        'forecastAt': f'2026-07-21T{hour:02d}:00:00+09:00',
        'temperature': temperature,
        'precipitationProbability': probability,
        'precipitationAmount': amount,
        'precipitationType': precipitation_type,
        'weatherCode': weather_code,
    }


def test_build_consensus_forecast_requires_two_of_three_models_for_rain():
    now = SEOUL.localize(datetime(2026, 7, 21, 14, 35))
    observation = WeatherObservation(
        observed_at=SEOUL.localize(datetime(2026, 7, 21, 14, 0)),
        temperature=29,
        precipitation_type='NONE',
        precipitation_amount=0,
    )
    forecasts = [
        model('JMA_MSM', [
            forecast_hour(14, 30),
            forecast_hour(15, 29, 'RAIN', amount=1, weather_code=61),
        ]),
        model('ECMWF_IFS', [
            forecast_hour(14, 28, probability=10),
            forecast_hour(15, 27, 'RAIN', 70, 2, 61),
        ]),
        model('GFS_GLOBAL', [
            forecast_hour(14, 29, probability=20),
            forecast_hour(15, 28, probability=30),
        ]),
    ]

    result = build_consensus_forecast(forecasts, observation, {}, now)

    assert result['version'] == 2
    assert result['currentTemperature'] == 29
    assert result['currentPrecipitationType'] == 'NONE'
    assert result['precipitationStartAt'] == '2026-07-21T15:00:00+09:00'
    assert result['precipitationEndAt'] == '2026-07-21T16:00:00+09:00'
    assert result['precipitationType'] == 'RAIN'
    assert result['precipitationConfidence'] == 'MEDIUM'
    assert result['availableModelCount'] == 3
    assert result['agreeingModelCount'] == 2
    assert result['hourly'][0]['temperature'] == 29


def test_build_consensus_forecast_uses_observation_for_current_precipitation():
    now = SEOUL.localize(datetime(2026, 7, 21, 14, 35))
    observation = WeatherObservation(
        observed_at=SEOUL.localize(datetime(2026, 7, 21, 14, 0)),
        temperature=26,
        precipitation_type='RAIN',
        precipitation_amount=3,
    )
    forecasts = [
        model('JMA_MSM', [forecast_hour(14, 29)]),
        model('ECMWF_IFS', [forecast_hour(14, 28)]),
        model('GFS_GLOBAL', [forecast_hour(14, 30)]),
    ]

    result = build_consensus_forecast(forecasts, observation, {}, now)

    assert result['currentTemperature'] == 26
    assert result['currentPrecipitationType'] == 'RAIN'
    assert result['currentPrecipitationAmount'] == 3
    assert result['primaryCondition'] == 'RAIN'
    assert result['precipitationStartAt'] is None
