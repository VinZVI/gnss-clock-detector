"""
Общие утилиты проекта.
"""

import gzip
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def decompress(data: bytes, filename: str) -> Optional[str]:
    """Распаковывает .gz / .Z / несжатые файлы в строку UTF-8."""
    lo = filename.lower()

    if lo.endswith(".z"):
        try:
            import unlzw3
            return unlzw3.unlzw(data).decode("utf-8", errors="replace")
        except ImportError:
            logger.warning("unlzw3 не установлен, пробуем gzip-fallback для %s", filename)
        except Exception as exc:
            logger.warning("unlzw3 ошибка %s: %s, пробуем gzip-fallback", filename, exc)
        try:
            return gzip.decompress(data).decode("utf-8", errors="replace")
        except Exception:
            logger.error("Не удалось распаковать %s. pip install unlzw3", filename)
            return None

    if lo.endswith(".gz"):
        try:
            return gzip.decompress(data).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.error("gzip ошибка %s: %s", filename, exc)
            return None

    # файл не сжат
    return data.decode("utf-8", errors="replace")
