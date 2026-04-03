# 🔧 Исправление проблем с базой данных на Render.com

## Диагностика проблем

Из логов деплоя видно несколько проблем:

1. **Конфликт индексов**: Старый `uix_anomaly_sat_epoch` конфликтует с новым `uix_anomaly_sat_epoch_method`
2. **Незавершенные транзакции**: Ошибки ALTER TABLE оставляют транзакцию в broken state
3. **Неправильная последовательность**: Попытка удалить constraint через DROP INDEX

## Быстрое решение (рекомендуется)

### Шаг 1: Загрузите скрипт миграции

Скопируйте файл `migrate_database.py` в корень вашего репозитория.

### Шаг 2: Запустите миграцию через Render Shell

1. Откройте **Render Dashboard** → ваш сервис
2. Перейдите во вкладку **Shell**
3. Выполните:

```bash
python migrate_database.py
```

Скрипт автоматически:
- Проверит структуру базы
- Добавит колонку `detection_method`
- Удалит старый constraint
- Создаст новый unique index
- Обновит существующие записи

### Шаг 3: Проверьте результат

Скрипт покажет:
```
✅ Миграция успешно завершена!

Теперь можно:
1. Перезапустить приложение
2. Запустить ETL: python -m gnss_clock.etl --source nasa --days 3
```

### Шаг 4: Запустите ETL

```bash
python -m gnss_clock.etl --source nasa --days 3
```

---

## Альтернативное решение: Пересоздание базы

Если миграция не помогла, можно пересоздать базу данных:

### ⚠️ ВНИМАНИЕ: Это удалит все данные!

```bash
# В Render Shell
psql $DATABASE_URL -c "DROP TABLE IF EXISTS sat_clock_anomaly CASCADE"
psql $DATABASE_URL -c "DROP TABLE IF EXISTS sat_clock CASCADE"
psql $DATABASE_URL -c "DROP TABLE IF EXISTS etl_log CASCADE"

# Перезапустить приложение (автоматически создаст таблицы)
# Render Dashboard → Manual Deploy → Deploy latest commit

# Затем запустить ETL
python -m gnss_clock.etl --source nasa --days 3
```

---

## Проверка работы приложения

После миграции проверьте:

1. **API работает:**
   ```bash
   curl https://gnss-clock-detector.onrender.com/api/satellites
   ```

2. **ETL статус:**
   ```bash
   curl https://gnss-clock-detector.onrender.com/api/etl/status
   ```

3. **Web UI:**
   Откройте https://gnss-clock-detector.onrender.com

---

## Почему возникла проблема?

1. **Автоматическая миграция в app.py не сработала** из-за:
   - Попытки удалить constraint как index
   - Неправильного порядка операций
   - Отсутствия проверок существования

2. **PostgreSQL строже SQLite**:
   - SQLite позволяет DROP INDEX IF EXISTS для constraint
   - PostgreSQL требует ALTER TABLE DROP CONSTRAINT

3. **Транзакции не откатывались**:
   - После ошибки ALTER TABLE транзакция оставалась broken
   - Последующие команды не выполнялись

---

## Долгосрочное решение

Скрипт `migrate_database.py` добавлен в репозиторий и может использоваться:

1. **При первом деплое** на новом сервере
2. **После обновления** схемы базы данных
3. **Для отладки** проблем с индексами

Рекомендуется:
- Запускать после каждого значительного изменения схемы БД
- Использовать в CI/CD pipeline перед запуском приложения
- Хранить в репозитории для документации

---

## Troubleshooting

### Ошибка: "relation does not exist"

Значит таблицы не созданы. Решение:
```bash
python -c "
from gnss_clock.app import create_app
from gnss_clock.models import db
app = create_app()
with app.app_context():
    db.create_all()
print('✓ Tables created')
"
```

### Ошибка: "duplicate key value violates unique constraint"

Значит есть дубликаты в данных. Решение:
```bash
# Найти дубликаты
psql $DATABASE_URL -c "
SELECT sat_id, epoch, detection_method, COUNT(*) 
FROM sat_clock_anomaly 
GROUP BY sat_id, epoch, detection_method 
HAVING COUNT(*) > 1
"

# Удалить дубликаты (оставив по одной записи)
psql $DATABASE_URL -c "
DELETE FROM sat_clock_anomaly a
USING sat_clock_anomaly b
WHERE a.id < b.id
AND a.sat_id = b.sat_id
AND a.epoch = b.epoch
AND a.detection_method = b.detection_method
"
```

### Проверить структуру базы

```bash
psql $DATABASE_URL -c "
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'sat_clock_anomaly'
ORDER BY ordinal_position
"

psql $DATABASE_URL -c "
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'sat_clock_anomaly'
"
```

---

## Мониторинг после исправления

После успешной миграции отслеживайте:

1. **Логи приложения** в Render Dashboard
2. **Количество записей** в БД:
   ```sql
   SELECT COUNT(*) FROM sat_clock;
   SELECT COUNT(*) FROM sat_clock_anomaly;
   ```
3. **Работу ETL**:
   ```bash
   curl https://gnss-clock-detector.onrender.com/api/etl/status | jq
   ```

---

## Дополнительные ресурсы

- [PostgreSQL UNIQUE Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)
- [SQLAlchemy Migrations](https://docs.sqlalchemy.org/en/latest/core/metadata.html)
- [Render PostgreSQL Docs](https://render.com/docs/databases)
