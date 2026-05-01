"""Тесты парсеров .glo и .hlt файлов ГЛОНАСС-ИАЦ."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gnss_clock.status_parsers import parse_glo, parse_hlt

# ── Образец .glo ──────────────────────────────────────────────────────────
GLO_SAMPLE = """\
# Комментарий
R01  1  730  2  ГЛО-М  26.01.01  04.12.11  04.12.11  активен
R09  9  801  3  ГЛО-К  26.01.01  14.03.14  14.03.14  активен
G01  1  000  0  GPS-IIF 26.01.01  25.05.11  25.05.11  активен
BADLINE
"""

# ── Образец .hlt ──────────────────────────────────────────────────────────
HLT_SAMPLE = """\
# History
R01 18.04.26 00:00:00 19.04.26 00:00:00 0
R01 20.04.26 00:00:00 21.04.26 12:00:00 1
R09 18.04.26 00:00:00 19.04.26 00:00:00 3
BADLINE
"""


# ── parse_glo ─────────────────────────────────────────────────────────────

def test_glo_parses_glonass():
    results = parse_glo(GLO_SAMPLE)
    ids = [r["sat_id"] for r in results]
    assert "R01" in ids
    assert "R09" in ids

def test_glo_parses_gps():
    results = parse_glo(GLO_SAMPLE)
    g01 = next(r for r in results if r["sat_id"] == "G01")
    assert g01["system"] == "GPS"

def test_glo_skips_bad_lines():
    results = parse_glo(GLO_SAMPLE)
    ids = [r["sat_id"] for r in results]
    assert "BADLINE" not in ids

def test_glo_skips_comments():
    results = parse_glo(GLO_SAMPLE)
    assert all(not r["sat_id"].startswith("#") for r in results)

def test_glo_glonass_plane():
    results = parse_glo(GLO_SAMPLE)
    r01 = next(r for r in results if r["sat_id"] == "R01")
    # слот 1 → плоскость 1
    assert r01["plane"] == 1
    r09 = next(r for r in results if r["sat_id"] == "R09")
    # слот 9 → плоскость 2
    assert r09["plane"] == 2

def test_glo_required_fields():
    results = parse_glo(GLO_SAMPLE)
    for r in results:
        assert "sat_id" in r
        assert "system" in r
        assert "slot" in r
        assert "sat_num" in r
    
    r01 = next(r for r in results if r["sat_id"] == "R01")
    assert r01["sat_num"] == "730"

def test_glo_empty():
    assert parse_glo("") == []
    assert parse_glo("# only comment") == []


# ── parse_hlt ─────────────────────────────────────────────────────────────

def test_hlt_parses_records():
    results = parse_hlt(HLT_SAMPLE)
    assert len(results) == 3

def test_hlt_status_codes():
    results = parse_hlt(HLT_SAMPLE)
    codes = {r["status_code"] for r in results}
    assert 0 in codes
    assert 1 in codes
    assert 3 in codes

def test_hlt_epochs_are_datetime():
    from datetime import datetime
    results = parse_hlt(HLT_SAMPLE)
    for r in results:
        assert isinstance(r["start_epoch"], datetime)
        assert isinstance(r["end_epoch"], datetime)

def test_hlt_skips_bad_lines():
    results = parse_hlt(HLT_SAMPLE)
    assert all(r["sat_id"] != "BADLINE" for r in results)

def test_hlt_skips_comments():
    results = parse_hlt(HLT_SAMPLE)
    assert all(not r["sat_id"].startswith("#") for r in results)

def test_hlt_epoch_values():
    from datetime import datetime
    results = parse_hlt(HLT_SAMPLE)
    r = next(r for r in results if r["sat_id"] == "R01" and r["status_code"] == 0)
    assert r["start_epoch"] == datetime(2026, 4, 18, 0, 0, 0)
    assert r["end_epoch"]   == datetime(2026, 4, 19, 0, 0, 0)

def test_hlt_empty():
    assert parse_hlt("") == []
