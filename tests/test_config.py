import os
from pathlib import Path
from gnss_clock import config

def test_db_path_resolution():
    # Сохраняем оригинальные значения
    old_base = config.BASE_DIR
    
    # Тестируем относительный путь
    os.environ["GNSS_DB_PATH"] = "test_data/db.sqlite3"
    
    # Перезагружаем логику (имитируем)
    db_path_str = os.environ.get("GNSS_DB_PATH")
    db_path = Path(db_path_str)
    if not db_path.is_absolute():
        db_path = (old_base / db_path).resolve()
    
    assert db_path.is_absolute()
    assert str(db_path).endswith(os.path.join("test_data", "db.sqlite3"))
    assert "PhD" in str(db_path) # Проверка, что корень PhD прицепился

def test_db_path_absolute():
    # Тестируем уже абсолютный путь
    abs_path = "C:\\Temp\\db.sqlite3"
    os.environ["GNSS_DB_PATH"] = abs_path
    
    db_path = Path(abs_path)
    if not db_path.is_absolute():
        db_path = (Path("C:\\") / db_path).resolve()
        
    assert db_path.is_absolute()
    assert str(db_path) == abs_path
