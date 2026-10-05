import json
from datetime import datetime
from pathlib import Path

import pytz

from scripts.dust import _measured_at, parse_air_quality
from scripts.forecast import _snow_amount
from scripts.living_index import parse_uv_index
from scripts.warning import parse_weather_warnings


FIXTURES = Path(__file__).parent / 'fixtures'
SEOUL = pytz.timezone('Asia/Seoul')


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_air_quality_measurement_time_is_iso8601_with_korean_offset():
    assert _measured_at('2026-10-04 10:00') == '2026-10-04T10:00:00+09:00'


def test_air_quality_fixture_maps_all_numeric_values_and_station():
    assert parse_air_quality(fixture('air_quality.json')) == {
        'pm10Value': 18,
        'pm10Grade': 1,
        'pm25Value': 9,
        'pm25Grade': 1,
        'khaiValue': 42,
        'khaiGrade': 1,
        'stationName': '호수동',
        'measuredAt': '2026-10-04T10:00:00+09:00',
    }


def test_snowfall_strings_map_to_centimetres():
    assert _snow_amount('적설없음') == 0.0
    assert _snow_amount('1cm 미만') == 0.5
    assert _snow_amount('0.5cm 미만') == 0.5
    assert _snow_amount('2.5cm') == 2.5
    assert _snow_amount('불명') is None


def test_weather_warning_fixture_maps_title_area_and_issue_time():
    warnings = parse_weather_warnings(fixture('weather_warning.json'))

    assert warnings == [{
        'title': '[안산] 호우주의보 발표',
        'kind': '호우',
        'level': '주의보',
        'area': '안산',
        'issuedAt': '2026-10-04T10:30:00+09:00',
        'startsAt': None,
        'endsAt': None,
    }]


def test_uv_index_fixture_returns_nearest_three_hour_period():
    now = SEOUL.localize(datetime(2026, 10, 4, 10, 30))

    result = parse_uv_index(fixture('uv_index.json'), now)

    assert result == {
        'value': 2,
        'grade': '낮음',
        'forecastAt': '2026-10-04T10:30:00+09:00',
    }
