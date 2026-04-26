"""Тесты маршрута /satellite/<sat_id> и API спутника."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from gnss_clock.app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_satellite_page_returns_200(client):
    res = client.get("/satellite/R01")
    assert res.status_code == 200


def test_satellite_page_returns_html(client):
    res = client.get("/satellite/G01")
    assert b"<!DOCTYPE html>" in res.data


def test_satellite_page_any_id(client):
    for sat in ("G01", "R09", "E11", "C05"):
        res = client.get(f"/satellite/{sat}")
        assert res.status_code == 200, f"Ожидали 200 для {sat}"


def test_satellite_meta_missing_returns_404(client):
    res = client.get("/api/satellites/NOTEXIST/meta")
    assert res.status_code == 404


def test_satellite_history_missing_returns_empty(client):
    res = client.get("/api/satellites/NOTEXIST/history")
    assert res.status_code == 200
    assert res.get_json() == []


def test_root_returns_200(client):
    res = client.get("/")
    assert res.status_code == 200
