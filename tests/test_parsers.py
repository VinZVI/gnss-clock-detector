"""Тесты парсеров SP3 и RINEX CLK."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gnss_clock.parsers import parse_sp3, parse_rinex_clk, parse_file

# ── Минимальный SP3-c сэмпл ────────────────────────────────────────────────
SP3_SAMPLE = """\
#cP2026  3 20  0  0  0.00000000      96 ORBIT IGS14 HLM  IGS
## 2603      0.000000000   900.00000000 19437 0.0000000000000
+   32   G01G02G03G04G05G06G07G08G09G10G11G12G13G14G15G16
+        G17G18G19G20G21G22G23G24G25G26G27G28G29G30G31G32
++         0  0  0  0  0  0  0  0  0  0  0  0  0  0  0  0
%c G  cc GPS ccc cccc cccc cccc cccc ccccc ccccc ccccc ccccc
%f  1.2500000  1.025000000  0.00000000000  0.000000000000000
%i    0    0    0    0      0      0      0      0         0
%i    0    0    0    0      0      0      0      0         0
/* END OF HEADER
*  2026  3 20  0  0  0.00000000
PG01  12345.678901  -23456.789012   34567.890123      1.234567
PG02  -9876.543210   12345.678901  -45678.901234     -0.000001
PR01   1111.222222    2222.333333    3333.444444  999999.999999
*  2026  3 20  0 15  0.00000000
PG01  12345.100000  -23456.100000   34567.100000      1.300000
EOF
"""

# ── RINEX CLK — реальный формат GLONASS-IAC:
#   - Fortran D-нотация (D-03 вместо E-03)
#   - Windows CRLF (\r\n)
#   - Строки AR (станции) — должны игнорироваться
RINEX_CLK_SAMPLE = (
    "     2.00           C                       RINEX VERSION / TYPE\r\n"
    "                                            END OF HEADER\r\n"
    "AS G01  2026 03 19 00 00  0.000000  1    1.234567890000D-09\r\n"
    "AS G02  2026 03 19 00 05  0.000000  1   -9.876543210000D-10\r\n"
    "AS R01  2026 03 19 00 00  0.000000  1    5.000000000000D-09\r\n"
    "AR NRC1 2026 03 19 00 00  0.000000  1    6.318976833840D-09\r\n"
)


def test_sp3_basic():
    records = parse_sp3(SP3_SAMPLE)
    assert len(records) == 3, f"Ожидали 3 записи, получили {len(records)}"
    sat_ids = {r["sat_id"] for r in records}
    assert "G01" in sat_ids
    assert "G02" in sat_ids
    # R01 с 999999 должен быть отфильтрован
    assert "R01" not in sat_ids


def test_sp3_units():
    """clock_bias в SP3 — мкс; мы конвертируем в нс (*1000)."""
    records = parse_sp3(SP3_SAMPLE)
    g01 = next(r for r in records if r["sat_id"] == "G01" and r["epoch"].minute == 0)
    # 1.234567 мкс → 1234.567 нс
    assert abs(g01["clock_bias"] - 1234.567) < 0.001


def test_rinex_clk_basic():
    records = parse_rinex_clk(RINEX_CLK_SAMPLE)
    assert len(records) == 3, f"Ожидали 3 (AS), получили {len(records)}"
    sat_ids = {r["sat_id"] for r in records}
    assert {"G01", "G02", "R01"} == sat_ids


def test_rinex_clk_ignores_ar():
    """Строки AR (station receiver) должны игнорироваться."""
    records = parse_rinex_clk(RINEX_CLK_SAMPLE)
    assert all(r["sat_id"] != "NRC1" for r in records)


def test_rinex_clk_d_notation():
    """Fortran D-нотация: 1.234567890000D-09 с → 1.23456789 нс."""
    records = parse_rinex_clk(RINEX_CLK_SAMPLE)
    g01 = next(r for r in records if r["sat_id"] == "G01")
    assert abs(g01["clock_bias"] - 1.23456789) < 1e-6


def test_rinex_clk_crlf():
    """CRLF не должен влиять на парсинг."""
    # Файл с CRLF и без — результат одинаковый
    sample_lf = RINEX_CLK_SAMPLE.replace("\r\n", "\n")
    r_crlf = parse_rinex_clk(RINEX_CLK_SAMPLE)
    r_lf   = parse_rinex_clk(sample_lf)
    assert len(r_crlf) == len(r_lf)
    assert abs(r_crlf[0]["clock_bias"] - r_lf[0]["clock_bias"]) < 1e-12


def test_rinex_clk_units():
    """clock_bias в RINEX — секунды; конвертируем в нс (*1e9)."""
    records = parse_rinex_clk(RINEX_CLK_SAMPLE)
    g02 = next(r for r in records if r["sat_id"] == "G02")
    # -9.876543210000D-10 с → -0.987654321 нс
    assert abs(g02["clock_bias"] - (-0.987654321)) < 1e-6


def test_dispatch_clk():
    records = parse_file(RINEX_CLK_SAMPLE, "Stark_26031900.clk")
    assert len(records) == 3


def test_dispatch_clk_z():
    records = parse_file(RINEX_CLK_SAMPLE, "Stark_26031900.clk.Z")
    assert len(records) == 3


def test_dispatch_sp3():
    records = parse_file(SP3_SAMPLE, "Stark_26032000.sp3")
    assert len(records) == 3
