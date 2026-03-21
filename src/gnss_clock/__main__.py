"""python -m gnss_clock → подсказка по командам."""
print("""
Доступные команды:
  python -m gnss_clock.etl              # запустить ETL (FTP)
  python -m gnss_clock.etl --test       # ETL с тестовыми данными
  python -m gnss_clock.ftp_client       # диагностика FTP-структуры
  python -m gnss_clock.ftp_client 7     # диагностика за 7 дней
""")
