"""Тесты утилит времени: YYYYDDD каталог + YYMMDDHR имя файла + GPS-неделя NASA."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone
from gnss_clock.gps_time import (
    date_to_dir, dir_to_date, slot_for, file_tag, file_stem, slots_to_fetch,
    utc_to_gps_week, nasa_file_stem, nasa_slots_to_fetch,
)


# ── Каталог YYYYDDD ────────────────────────────────────────────────────────

def test_date_to_dir_known():
    assert date_to_dir(datetime(2026, 3, 20)) == "26079"

def test_date_to_dir_jan1():
    assert date_to_dir(datetime(2026, 1, 1)) == "26001"

def test_date_to_dir_dec31():
    assert date_to_dir(datetime(2026, 12, 31)) == "26365"

def test_dir_to_date_roundtrip():
    for s in ["26071", "26072", "26073", "26074", "26075", "26076", "26077", "26078", "26079"]:
        dt = dir_to_date(s)
        assert date_to_dir(dt) == s

def test_dir_listing_matches():
    expected = {
        "26071": datetime(2026, 3, 12),
        "26072": datetime(2026, 3, 13),
        "26079": datetime(2026, 3, 20),
    }
    for code, date in expected.items():
        assert dir_to_date(code).date() == date.date()


# ── Слоты ─────────────────────────────────────────────────────────────────

def test_slot_for():
    assert slot_for(datetime(2026, 3, 20,  0, 30)) ==  0
    assert slot_for(datetime(2026, 3, 20,  6,  0)) ==  6
    assert slot_for(datetime(2026, 3, 20, 11, 59)) ==  6
    assert slot_for(datetime(2026, 3, 20, 12,  0)) == 12
    assert slot_for(datetime(2026, 3, 20, 18,  0)) == 18
    assert slot_for(datetime(2026, 3, 20, 23, 59)) == 18


# ── Имена файлов YYMMDDHR ─────────────────────────────────────────────────

def test_file_tag_matches_listing():
    dt = datetime(2026, 3, 20)
    assert file_tag(dt,  0) == "26032000"
    assert file_tag(dt,  6) == "26032006"
    assert file_tag(dt, 12) == "26032012"

def test_file_stem_normal():
    dt = datetime(2026, 3, 20)
    assert file_stem("Stark", dt,  0)        == "Stark_26032000"
    assert file_stem("Stark", dt,  6)        == "Stark_26032006"
    assert file_stem("Stark", dt,  0, True)  == "Stark_1D_26032000"
    assert file_stem("Stark", dt, 12, True)  == "Stark_1D_26032012"


# ── slots_to_fetch ────────────────────────────────────────────────────────

def test_slots_count():
    now = datetime(2026, 3, 20, 10, 45, tzinfo=timezone.utc)
    slots = slots_to_fetch(days_back=1, now=now)
    assert len(slots) == 4

def test_slots_order():
    now = datetime(2026, 3, 20, 10, 45, tzinfo=timezone.utc)
    slots = slots_to_fetch(days_back=1, now=now)
    assert slots[0][1] == 6    # текущий слот 06
    assert slots[1][1] == 0    # предыдущий 00
    assert slots[2][1] == 18   # вчера 18

def test_slots_7days():
    assert len(slots_to_fetch(days_back=7)) == 7 * 4


# ── GPS-неделя (NASA) ─────────────────────────────────────────────────────

def test_gps_epoch():
    """GPS epoch (6 Jan 1980) → неделя 0, день 0."""
    w, d = utc_to_gps_week(datetime(1980, 1, 6, tzinfo=timezone.utc))
    assert w == 0 and d == 0

def test_gps_week_known():
    """20 марта 2026 (пятница) → GPS неделя 2410, DOW 5."""
    w, d = utc_to_gps_week(datetime(2026, 3, 20, tzinfo=timezone.utc))
    assert w == 2410
    assert d == 5   # пятница (0=вс … 5=пт … 6=сб)

def test_nasa_file_stem_igu():
    # GPS неделя 2410, DOW 5 (20 марта 2026, пятница)
    assert nasa_file_stem("igu", 2410, 5, 0)  == "igu24105_00"
    assert nasa_file_stem("igu", 2410, 5, 6)  == "igu24105_06"
    assert nasa_file_stem("igu", 2410, 5, 12) == "igu24105_12"

def test_nasa_file_stem_igr():
    """IGR (rapid) — нет суффикса слота."""
    assert nasa_file_stem("igr", 2410, 5, 0) == "igr24105"

def test_nasa_slots_igu():
    """IGU: 4 слота × days_back."""
    now   = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    slots = nasa_slots_to_fetch(1, product="igu", now=now)
    assert len(slots) == 4
    # Первый слот — текущий (06h)
    assert slots[0][2] == 6

def test_nasa_slots_igr():
    """IGR: 1 слот в сутки."""
    now   = datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc)
    slots = nasa_slots_to_fetch(3, product="igr", now=now)
    assert len(slots) == 3
    assert all(s[2] == 0 for s in slots)
