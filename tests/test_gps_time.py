"""Тесты утилит времени: YYYYDDD каталог + YYMMDDHR имя файла."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime
from gnss_clock.gps_time import (
    date_to_dir, dir_to_date, slot_for, file_tag, file_stem, slots_to_fetch
)


# ── Каталог YYYYDDD ────────────────────────────────────────────────────────

def test_date_to_dir_known():
    """20 марта 2026 = DOY 079."""
    assert date_to_dir(datetime(2026, 3, 20)) == "26079"

def test_date_to_dir_jan1():
    assert date_to_dir(datetime(2026, 1, 1)) == "26001"

def test_date_to_dir_dec31():
    assert date_to_dir(datetime(2026, 12, 31)) == "26365"

def test_dir_to_date_roundtrip():
    for s in ["26071", "26072", "26073", "26074", "26075", "26076", "26077", "26078", "26079"]:
        dt = dir_to_date(s)
        assert date_to_dir(dt) == s, f"roundtrip failed for {s}"

def test_dir_listing_matches():
    """Проверяем соответствие даты из листинга FTP."""
    expected = {
        "26071": datetime(2026, 3, 12),
        "26072": datetime(2026, 3, 13),
        "26079": datetime(2026, 3, 20),
    }
    for code, date in expected.items():
        assert dir_to_date(code).date() == date.date(), f"{code} → {dir_to_date(code)}"


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
    """Файлы из листинга: Stark_26032000, Stark_26032006, Stark_26032012."""
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
    """1 день = 4 слота (24/6)."""
    from datetime import timezone
    now = datetime(2026, 3, 20, 10, 45, tzinfo=timezone.utc)
    slots = slots_to_fetch(days_back=1, now=now)
    assert len(slots) == 4

def test_slots_order():
    """Первый слот — текущий, потом убывает."""
    from datetime import timezone
    now = datetime(2026, 3, 20, 10, 45, tzinfo=timezone.utc)
    slots = slots_to_fetch(days_back=1, now=now)
    # текущий слот = 06
    assert slots[0][1] == 6
    # предыдущий = 00 того же дня
    assert slots[1][1] == 0
    # ещё раньше = 18 предыдущего дня
    assert slots[2][1] == 18

def test_slots_7days():
    assert len(slots_to_fetch(days_back=7)) == 7 * 4
