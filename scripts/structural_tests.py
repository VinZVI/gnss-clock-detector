"""
Структурные тесты репозитория (Evaluator-слой).
Проверяют инварианты, которые должны выполняться всегда.
Запуск: python scripts/structural_tests.py
"""
import ast, sys, re, pathlib

ERRORS = []

def check(condition, msg):
    if not condition:
        ERRORS.append(f"FAIL: {msg}")

# 1. AGENTS.md ≤ 100 строк
agents = pathlib.Path("AGENTS.md")
check(agents.exists(), "AGENTS.md не найден")
if agents.exists():
    n = len(agents.read_text(encoding="utf-8").splitlines())
    check(n <= 100, f"AGENTS.md {n} строк > 100 (Harness-правило: карта, не инструкция)")

# 2. Обязательные docs/
for doc in ["ARCHITECTURE.md", "ADR.md", "MODULE_MAP.md",
            "DATA_SOURCES.md", "ETL_PIPELINE.md", "API_REFERENCE.md"]:
    check(pathlib.Path(f"docs/{doc}").exists(), f"docs/{doc} не найден")

# 3. Секреты защищены .gitignore
gitignore = pathlib.Path(".gitignore")
check(gitignore.exists(), ".gitignore не найден")
if gitignore.exists():
    gi = gitignore.read_text(encoding="utf-8")
    for secret in [".env", "db.sqlite3", ".token_cache"]:
        check(secret in gi, f"{secret} не защищён .gitignore")

# 4. Каждый модуль имеет docstring
src = pathlib.Path("src/gnss_clock")
if src.exists():
    for py in src.glob("*.py"):
        if py.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
            has_doc = (tree.body and
                       isinstance(tree.body[0], ast.Expr) and
                       isinstance(tree.body[0].value, ast.Constant))
            check(has_doc, f"{py.name}: нет docstring на уровне модуля")
        except SyntaxError:
            check(False, f"{py.name}: SyntaxError")

# 5. NASA_TIMEOUT >= 60
config_path = src / "config.py"
if config_path.exists():
    ct = config_path.read_text(encoding="utf-8")
    m = re.search(r'NASA_TIMEOUT\s*=.*?(\d+)', ct)
    if m:
        check(int(m.group(1)) >= 60,
              f"NASA_TIMEOUT={m.group(1)} < 60 (риск worker timeout на Render)")

# 6. pyproject.toml содержит версию
pp = pathlib.Path("pyproject.toml")
check(pp.exists(), "pyproject.toml не найден")
if pp.exists():
    vm = re.search(r'version\s*=\s*"(\d+\.\d+\.\d+)"', pp.read_text(encoding="utf-8"))
    check(vm is not None, "Версия не найдена в pyproject.toml")

# 7. .token_cache в .gitignore
if gitignore.exists():
    check(".token_cache" in gitignore.read_text(encoding="utf-8"),
          ".token_cache с JWT-токеном NASA не защищён .gitignore!")

print()
if ERRORS:
    for e in ERRORS:
        print(e)
    print(f"\n{len(ERRORS)} ошибок")
    sys.exit(1)
else:
    print(f"✓ Структурные тесты OK (0 ошибок)")
