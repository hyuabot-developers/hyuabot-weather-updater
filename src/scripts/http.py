import requests
from requests.sessions import HTTPAdapter
from urllib3 import Retry


def retrying_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        read=5,
        connect=5,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session
