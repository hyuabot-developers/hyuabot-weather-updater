# hyuabot-weather-updater

A batch job that fetches real-time weather observations from the Korea Meteorological Administration (KMA) open API and writes bilingual (Korean/English) weather notices into the HYUabot PostgreSQL database.

## Overview

The updater runs as a one-shot process (designed for a CronJob or similar scheduler). On each run it:

1. Looks up the `날씨` (Weather) notice category in the database.
2. Calls the KMA Ultra-Short-Term Observation API (`getUltraSrtNcst`) for the grid point covering Hanyang University ERICA campus (`nx=57, ny=121`).
3. Extracts three observation values:

   | Code  | Meaning                                                |
   |-------|--------------------------------------------------------|
   | `PTY` | Precipitation type (0=clear, 2=snow/sleet, other=rain) |
   | `T1H` | Current temperature (°C)                               |
   | `RN1` | Hourly precipitation (mm)                              |

4. Builds a short notice string in both Korean and English, appending rainfall amount when non-zero.
5. Deletes all existing weather notices for that category and inserts the two new ones, each expiring in 1 hour.

### Example output

| Language | Format                                                           |
|----------|------------------------------------------------------------------|
| Korean   | `[날씨] ☀️/현재 온도:18.0℃` or `[날씨] 🌧️/현재 온도:12.0℃/강수량:3mm`          |
| English  | `[Weather] ☀️/Temp:18.0℃` or `[Weather] 🌧️/Temp:12.0℃/Rain:3mm` |

Weather icons: ☀️ (clear) · 🌧️ (rain) · 🌨️ (snow/sleet)

## Architecture

```
src/
├── main.py          # Entry point; fetches weather and upserts notices
├── models.py        # SQLAlchemy ORM models (NoticeCategory, Notice)
└── utils/
    └── database.py  # PostgreSQL engine factory (psycopg3 + SQLAlchemy)
```

### Database tables used

**`notice_category`**

| Column          | Type        | Description            |
|-----------------|-------------|------------------------|
| `category_id`   | integer PK  |                        |
| `category_name` | varchar(20) | Matched against `'날씨'` |

**`notices`**

| Column        | Type              | Description                      |
|---------------|-------------------|----------------------------------|
| `notice_id`   | integer PK (auto) |                                  |
| `title`       | varchar(100)      | Weather notice text              |
| `url`         | varchar(200)      | Empty string for weather notices |
| `expired_at`  | timestamptz       | Current time + 1 hour            |
| `category_id` | integer FK        | References `notice_category`     |
| `user_id`     | varchar(20)       | Always `'admin'`                 |
| `language`    | varchar(10)       | `'KOREAN'` or `'ENGLISH'`        |

## Requirements

- Python ≥ 3.12
- PostgreSQL (any recent version)
- KMA Open Data Portal API key ([https://www.data.go.kr](https://www.data.go.kr))

## Environment Variables

| Variable            | Description               |
|---------------------|---------------------------|
| `WEATHER_API_KEY`   | KMA open data service key |
| `POSTGRES_ID`       | PostgreSQL username       |
| `POSTGRES_PASSWORD` | PostgreSQL password       |
| `POSTGRES_HOST`     | PostgreSQL host           |
| `POSTGRES_PORT`     | PostgreSQL port           |
| `POSTGRES_DB`       | PostgreSQL database name  |

## Running Locally

```bash
# Install
pip install -e .

# Set environment variables
export WEATHER_API_KEY=your_api_key
export POSTGRES_ID=postgres
export POSTGRES_PASSWORD=password
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=hyuabot

# Run
cd src
python main.py
```

## Docker

The image is built with a multi-stage Alpine build (Python 3.14). The container exits after a single run — schedule it externally (Kubernetes CronJob, Docker run via cron, etc.).

```bash
# Build
docker build -t hyuabot-weather-updater .

# Run
docker run --rm \
  -e WEATHER_API_KEY=your_api_key \
  -e POSTGRES_ID=postgres \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_HOST=host.docker.internal \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=hyuabot \
  hyuabot-weather-updater
```

## Development

### Install dev dependencies

```bash
pip install -e .[lint]        # flake8
pip install -e .[typecheck]   # mypy
pip install -e .[test]        # pytest
```

### Lint

```bash
python -m flake8 src/ tests/
```

### Type check

```bash
python -m mypy src/ tests/
```

### Test

```bash
python -m pytest -m 'not integration' -v
```

Tests run against a PostgreSQL instance at `localhost:25432` (see CI configuration).

## CI/CD

| Workflow | Trigger | Jobs |
|----------|---------|------|
| `default.yml` | Push to any branch except `main` | lint, typecheck, test |
| `deploy.yml` | PR merged to `main` (or manual dispatch) | Docker build → push to `localhost:5000` |

CI runners are self-hosted (`X64 Linux` for code checks, `ARM64 Linux` for the Docker build).

## Notes

- The base time sent to the KMA API is the current hour when `minute > 15`, otherwise the previous hour. This accounts for the ~10-minute publication delay of KMA observation data.
- The updater does nothing and exits cleanly if no `날씨` category row exists in the database.

## License

GPLv3
