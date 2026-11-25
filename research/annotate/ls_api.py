"""Minimal Label Studio REST client (push tasks, pull a project's JSON export).

LABEL_STUDIO_URL and LABEL_STUDIO_API_KEY come from research/.env. Legacy tokens use the "Token"
scheme; set LABEL_STUDIO_AUTH_SCHEME=Bearer for personal access tokens.
"""
import os

import requests

from common.io import load_env


def _session():
    load_env()
    url = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080").rstrip("/")
    key = os.environ.get("LABEL_STUDIO_API_KEY")
    if not key:
        raise SystemExit("set LABEL_STUDIO_API_KEY in research/.env (Account & Settings in Label Studio)")
    s = requests.Session()
    s.headers["Authorization"] = f"{os.environ.get('LABEL_STUDIO_AUTH_SCHEME', 'Token')} {key}"
    return url, s


def push_tasks(project_id: int, tasks: list[dict]) -> dict:
    url, s = _session()
    r = s.post(f"{url}/api/projects/{project_id}/import", json=tasks, timeout=120)
    r.raise_for_status()
    return r.json()


def pull_export(project_id: int) -> list[dict]:
    url, s = _session()
    r = s.get(f"{url}/api/projects/{project_id}/export", params={"exportType": "JSON"}, timeout=300)
    r.raise_for_status()
    return r.json()
