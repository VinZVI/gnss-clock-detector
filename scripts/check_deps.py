"""
Линтер архитектурных зависимостей.
Проверяет, что ни один модуль не импортирует из слоя выше своего.
Запуск: python scripts/check_deps.py
"""
import ast, sys, pathlib

LAYERS = {
    "config":       1,
    "models":       2,
    "utils":        3,
    "gps_time":     3,
    "parsers":      3,
    "detector":     4,
    "analytics":    4,
    "ftp_client":   5,
    "nasa_client":  5,
    "etl":          6,
    "app":          7,
}

errors = []
src = pathlib.Path("src/gnss_clock")

for pyfile in src.glob("*.py"):
    module = pyfile.stem
    if module not in LAYERS or module.startswith("_"):
        continue
    my_layer = LAYERS[module]

    try:
        tree = ast.parse(pyfile.read_text(encoding="utf-8"))
    except SyntaxError as e:
        errors.append(f"SyntaxError в {pyfile.name}: {e}")
        continue

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        mod_str = getattr(node, "module", "") or ""
        # Смотрим только на внутренние импорты пакета
        for dep, dep_layer in LAYERS.items():
            if dep == module:
                continue
            # Прямой импорт: from .detector import ... или from gnss_clock.detector
            if dep in mod_str or (
                hasattr(node, "names") and
                any(a.name == dep for a in getattr(node, "names", []))
            ):
                if dep_layer > my_layer:
                    errors.append(
                        f"ОШИБКА [{pyfile.name}] слой={my_layer}: "
                        f"импортирует '{dep}' (слой={dep_layer}). "
                        f"Нарушение правила: слой N → только слои < N.\n"
                        f"  Решение: перенесите зависимость или пересмотрите слой."
                    )

if errors:
    print("\n".join(errors))
    sys.exit(1)

print(f"✓ Зависимости OK ({len(LAYERS)} модулей, 0 нарушений)")
