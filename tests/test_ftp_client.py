import datetime
from gnss_clock.ftp_client import _candidates_status

def test_candidates_status_format():
    dt = datetime.datetime(2026, 4, 25)
    candidates = _candidates_status(dt)
    
    # Ожидаем YYMMDD: 260425
    names = [c[0] for c in candidates]
    assert "Const_260425.glo" in names
    assert "Stark_260425.hlt" in names
    
    # Проверка на смену года
    dt2 = datetime.datetime(2025, 12, 31)
    candidates2 = _candidates_status(dt2)
    names2 = [c[0] for c in candidates2]
    assert "Const_251231.glo" in names2

def test_candidates_status_padding():
    dt = datetime.datetime(2026, 1, 5)
    candidates = _candidates_status(dt)
    names = [c[0] for c in candidates]
    assert "Const_260105.glo" in names
