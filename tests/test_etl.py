import pytest
from unittest.mock import MagicMock, patch
from gnss_clock.etl import _get_product_type_from_filename, run_etl

def test_get_product_type_from_filename():
    assert _get_product_type_from_filename("igs22954.clk_30s") == "final"
    assert _get_product_type_from_filename("igr22954.clk") == "rapid"
    assert _get_product_type_from_filename("igu22954_12.clk") == "ultra"
    assert _get_product_type_from_filename("UNKNOWN.txt") == "ultra"

@patch("gnss_clock.etl._get_app")
@patch("gnss_clock.etl.ftp_iter")
@patch("gnss_clock.etl.parse_file")
@patch("gnss_clock.etl._load_clocks")
@patch("gnss_clock.etl._purge_old_data")
@patch("gnss_clock.etl._already_loaded_files")
def test_run_etl_success(mock_loaded, mock_purge, mock_load, mock_parse, mock_iter, mock_get_app):
    # Настройка моков
    mock_app = MagicMock()
    mock_get_app.return_value = mock_app
    mock_loaded.return_value = set()

    # Имитируем один файл в FTP (filename, content, subdir)
    mock_iter.return_value = [("test.clk", "file content", "rapid")]
    mock_parse.return_value = [{"satellite": "G01", "clock": 0.0001}]
    mock_load.return_value = 1

    # Мокаем контекст приложения Flask и БД
    with patch("gnss_clock.models.EtlLog"), \
         patch("gnss_clock.models.db"):
        stats = run_etl(days_back=1)

        assert stats["files_processed"] == 1
        assert stats["records_new"] == 1
        assert len(stats["errors"]) == 0
        mock_load.assert_called_once()
        mock_purge.assert_called_once()
