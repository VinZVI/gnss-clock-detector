"""Тесты NASA CDDIS клиента (без реальной сети)."""

import sys, os, gzip, io, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch, MagicMock


# ── URL-генерация ─────────────────────────────────────────────────────────

def test_candidate_urls_igs3():
    """GPS-неделя >= 2238 → IGS3-имена в приоритете."""
    from gnss_clock.nasa_client import _candidate_urls

    with patch("gnss_clock.nasa_client.config") as cfg:
        cfg.NASA_PRODUCT  = "igu"
        cfg.NASA_BASE_URL = "https://cddis.nasa.gov/archive/gnss/products"

        # Неделя 2410, DOW 5 (пт), слот 06 → 20 марта 2026 06:00 UTC
        candidates = _candidate_urls(2410, 5, 6)
        fnames = [fname for _, fname in candidates]

        # Первые — IGS3-формат (теперь используем OPSULT вместо IGS0)
        assert any("OPSULT" in f for f in fnames), f"IGS3 not found: {fnames}"
        # Есть и legacy как запасной
        assert any("igu2410" in f for f in fnames), f"legacy not found: {fnames}"


def test_candidate_urls_legacy():
    """GPS-неделя < 2238 → только legacy-имена."""
    from gnss_clock.nasa_client import _candidate_urls

    with patch("gnss_clock.nasa_client.config") as cfg:
        cfg.NASA_PRODUCT  = "igu"
        cfg.NASA_BASE_URL = "https://cddis.nasa.gov/archive/gnss/products"

        candidates = _candidate_urls(2100, 3, 0)
        fnames = [fname for _, fname in candidates]
        assert all("igu2100" in f for f in fnames)
        assert not any("IGS0OPSULT" in f for f in fnames)


# ── IGS3 имена ────────────────────────────────────────────────────────────

def test_igs3_name_clk():
    """IGS3 CLK для 20 марта 2026, слот 06."""
    from gnss_clock.nasa_client import _igs3_name
    from datetime import datetime, timezone

    dt = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    names = _igs3_name(dt, 6, "CLK")
    name = names[0] # берём первый из списка для проверки
    # DOY 079, год 2026
    assert "2026079" in name
    assert name.endswith(".CLK.gz")
    assert "CLK" in name


def test_igs3_name_sp3():
    from gnss_clock.nasa_client import _igs3_name
    from datetime import datetime, timezone

    dt = datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc)
    names = _igs3_name(dt, 0, "SP3")
    name = names[0]
    assert "2026079" in name
    assert name.endswith(".SP3.gz")


# ── Декомпрессия ──────────────────────────────────────────────────────────

def test_decompress_gz():
    from gnss_clock.nasa_client import _decompress
    text = "AS G01  2026 03 20 00 00  0.0  1   1.0D-09\n"
    buf  = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(text.encode())
    assert "AS G01" in _decompress(buf.getvalue(), "file.CLK.gz")


def test_decompress_plain():
    from gnss_clock.nasa_client import _decompress
    text = "AS G01  test\n"
    assert _decompress(text.encode(), "file.clk") == text


# ── HTTP 404 → None ───────────────────────────────────────────────────────

def test_download_404_returns_none():
    from gnss_clock.nasa_client import _download_url

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    session = MagicMock()
    session.get.return_value = mock_resp

    with patch("gnss_clock.nasa_client.config") as cfg:
        cfg.NASA_TIMEOUT = 30
        assert _download_url(session, "https://x.com/missing.gz", "missing.gz") is None


# ── HTTP 401 → сброс кеша ────────────────────────────────────────────────

def test_download_401_clears_cache():
    from gnss_clock import nasa_client
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as td:
        cache = pathlib.Path(td) / ".token_cache"
        cache.write_text('{"token":"t","expires_ts":9999999999}')

        original_cache = nasa_client._TOKEN_CACHE
        nasa_client._TOKEN_CACHE = cache

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        session = MagicMock()
        session.get.return_value = mock_resp

        with patch("gnss_clock.nasa_client.config") as cfg:
            cfg.NASA_TIMEOUT = 30
            nasa_client._download_url(session, "https://x.com/f.gz", "f.gz")

        nasa_client._TOKEN_CACHE = original_cache
        assert not cache.exists()


# ── Bearer token: кеш ────────────────────────────────────────────────────

def test_token_from_cache():
    from gnss_clock import nasa_client
    import tempfile, pathlib

    with tempfile.TemporaryDirectory() as td:
        cache = pathlib.Path(td) / ".token_cache"
        cache.write_text(json.dumps({
            "token":      "cached_tok",
            "expires_ts": time.time() + 30 * 86400,
        }))
        original = nasa_client._TOKEN_CACHE
        nasa_client._TOKEN_CACHE = cache

        with patch("gnss_clock.nasa_client.config") as cfg:
            cfg.NASA_TOKEN = ""
            cfg.NASA_USER  = "u"
            cfg.NASA_PASS  = "p"
            tok = nasa_client._get_bearer_token()

        nasa_client._TOKEN_CACHE = original
        assert tok == "cached_tok"


def test_manual_token_skips_api():
    """NASA_EARTHDATA_TOKEN задан → EDL API не вызывается."""
    from gnss_clock import nasa_client

    with patch("gnss_clock.nasa_client.config") as cfg:
        cfg.NASA_TOKEN = "manual_tok"
        with patch("requests.post") as mock_post:
            tok = nasa_client._get_bearer_token()
            mock_post.assert_not_called()
    assert tok == "manual_tok"


# ── Нет кредов → пустой итератор ─────────────────────────────────────────

def test_iter_no_credentials_yields_nothing():
    from gnss_clock.nasa_client import iter_new_files

    with patch("gnss_clock.nasa_client.config") as cfg:
        cfg.NASA_USER    = ""
        cfg.NASA_PASS    = ""
        cfg.NASA_TOKEN   = ""
        cfg.ETL_DAYS_BACK = 1
        assert list(iter_new_files(days_back=1)) == []


# ── check_credentials без настроек ───────────────────────────────────────

def test_check_no_config():
    from gnss_clock.nasa_client import check_credentials

    with patch("gnss_clock.nasa_client.config") as cfg:
        cfg.NASA_USER  = ""
        cfg.NASA_PASS  = ""
        cfg.NASA_TOKEN = ""
        result = check_credentials()

    assert result["ok"] is False
    assert result["auth_method"] == "none"
