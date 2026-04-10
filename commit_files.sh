git add README.md
git add src/gnss_clock/ftp_client.py
git add src/gnss_clock/app.py
git add src/gnss_clock/analytics.py
git add src/gnss_clock/models.py
git add src/gnss_clock/etl.py
git add src/gnss_clock/static/index.html
git add tests/test_etl.py
git add tests/test_nasa_client.py
git commit -m "feat: add rapid/final support and analytics UI

- fixed FTP client to properly parse rapid/final directory conventions
- updated etl data models to store product tags
- created analytics module to track satellite stability metrics
- restored dark theme UI and integrated new JS API routes
- improved dates and auto-scaling charting functionality"
