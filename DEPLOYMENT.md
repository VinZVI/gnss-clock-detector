# 🚀 Render.com Deployment Guide

## Quick Start

### 1. Push to Main Branch

```bash
git push origin main
```

### 2. Deploy to Render

1. Go to https://render.com and sign up/login
2. Click **New +** → **Web Service**
3. Connect your GitHub repository: `VinZVI/gnss-clock-detector`
4. Configure:

| Setting | Value |
|---------|-------|
| Name | `gnss-clock-detector` |
| Region | Frankfurt (eu-central-1) |
| Branch | `main` |
| Root Directory | *(leave empty)* |
| Runtime | `Python` |
| Build Command | `bash render-build.sh` |
| Start Command | `gunicorn wsgi:app --bind 0.0.0.0:$PORT` |
| Instance Type | **Free** |

5. Add Environment Variables:

```env
FLASK_DEBUG=0
SECRET_KEY=<generate-random-key>
GNSS_DATA_SOURCE=ftp
GNSS_ETL_DAYS_BACK=3
GNSS_ETL_RETAIN_DAYS=14
GNSS_MAD_THRESHOLD=3.0
NASA_EARTHDATA_USER=<your-nasa-username>
NASA_EARTHDATA_PASS=<your-nasa-password>
```

6. Click **Create Web Service**

### 3. Initial ETL Setup

After deployment completes:

1. Open **Shell** tab in Render dashboard
2. Run initial ETL:
   ```bash
   python -m gnss_clock.etl --source ftp --days 3
   ```

### 4. Verify Deployment

- Web UI: `https://gnss-clock-detector.onrender.com`
- API: `https://gnss-clock-detector.onrender.com/api/satellites`
- ETL Status: `https://gnss-clock-detector.onrender.com/api/etl/status`

---

## What Changed in v0.3.0

### Python & Dependencies

**Before (v0.2.0):**
- Python >=3.9 (later >=3.11)
- Flask 3.0
- NumPy 1.26
- requests 2.31
- werkzeug 3.0

**After (v0.3.0):**
- ✅ Python >=3.12
- ✅ Flask 3.1
- ✅ NumPy 2.0
- ✅ requests 2.32
- ✅ werkzeug 3.1
- ✅ gunicorn 23.0 (production WSGI server)

### New Files

```
render.yaml              # Render.com service configuration
render-build.sh          # Build script using uv
.github/workflows/       # CI/CD automation
  └── etl-daily.yml      # Daily ETL scheduler
```

### Updated Files

- **pyproject.toml**: Updated dependencies and Python version
- **README.md**: Added Render.com deployment instructions
- **wsgi.py**: Already compatible (no changes needed)

---

## Automated ETL Options

### Option 1: GitHub Actions (Recommended)

The included `.github/workflows/etl-daily.yml` runs ETL daily at 3 AM UTC.

**Setup:**

1. Add secrets to GitHub repository:
   - Settings → Secrets and variables → Actions
   - Add `SECRET_KEY`, `NASA_USER`, `NASA_PASS`

2. Enable workflow:
   - Actions tab → Enable workflows

3. Manual trigger:
   - Actions → Daily ETL → Run workflow

**Pros:**
- Free on public repositories
- Easy to configure
- Built-in scheduling
- Version controlled

**Cons:**
- Requires Git LFS for large databases
- Database must be committed back to repo

### Option 2: Render Cron Job (Paid Plans Only)

Render supports cron jobs on paid plans ($7+/month):

```yaml
services:
  - type: web
    name: gnss-clock-detector
    env: python
    buildCommand: bash render-build.sh
    startCommand: gunicorn wsgi:app --bind 0.0.0.0:$PORT
    
  - type: cron
    name: daily-etl
    env: python
    buildCommand: bash render-build.sh
    command: python -m gnss_clock.etl --source ftp --days 1
    schedule: "0 3 * * *"
```

### Option 3: External Scheduler + HTTP Endpoint

Add endpoint to `app.py`:

```python
@app.route('/api/admin/run-etl', methods=['POST'])
def run_etl():
    """Trigger ETL via HTTP call"""
    if not verify_api_key():
        abort(403)
    
    from .etl import run_etl
    result = run_etl(source='ftp', days_back=1)
    return jsonify({'status': 'ok', 'result': result})
```

Then use:
- UptimeRobot (free, 5-min intervals)
- Zapier / Make.com
- AWS EventBridge

---

## Database Persistence Strategies

### Strategy 1: Git LFS (Small Databases < 100 MB)

```bash
# Install Git LFS
git lfs install

# Track database
git lfs track db.sqlite3

# Commit
git add .gitattributes db.sqlite3
git commit -m "Add database tracking"
git push
```

**Limitations:**
- 1 GB bandwidth/month on free tier
- 1 GB storage on free tier
- Good for ~14 days of data

### Strategy 2: External Database (Production)

Upgrade to PostgreSQL for production:

1. Add Render PostgreSQL database
2. Update environment variables:
   ```env
   GNSS_DB_TYPE=mysql
   DATABASE_URL=${{PostgreSQL.DATABASE_URL}}
   ```
3. Modify `config.py` to use `DATABASE_URL`

**Benefits:**
- Persistent storage
- Automatic backups
- Better performance
- No Git LFS needed

### Strategy 3: S3 Backup + Restore

Use GitHub Actions to backup/restore from S3:

```yaml
- name: Download database from S3
  uses: aws-actions/configure-aws-credentials@v4
  with:
    aws-access-key-id: ${{ secrets.AWS_KEY }}
    aws-secret-access-key: ${{ secrets.AWS_SECRET }}
    aws-region: us-east-1
- run: aws s3 cp s3://my-bucket/db.sqlite3 ./db.sqlite3

- name: Upload database to S3
  run: aws s3 cp ./db.sqlite3 s3://my-bucket/db-latest.sqlite3
```

---

## Troubleshooting

### Build Fails

**Error:** `gunicorn: command not found`

**Solution:** Ensure `gunicorn>=23.0` is in `pyproject.toml` dependencies

---

### Port Binding Error

**Error:** `Address already in use` or timeout

**Solution:** Use `$PORT` environment variable:
```bash
gunicorn wsgi:app --bind 0.0.0.0:$PORT
```

---

### Database Locked

**Error:** `database is locked`

**Causes:**
- Multiple concurrent writes
- Long-running queries

**Solutions:**
1. Enable WAL mode in SQLite:
   ```python
   app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
       'connect_args': {'timeout': 30},
       'pool_pre_ping': True,
   }
   ```

2. Upgrade to PostgreSQL

---

### ETL Not Running

**Check logs:**
```bash
# Render Shell
tail -f logs/current.log
```

**Manual trigger:**
```bash
python -m gnss_clock.etl --source ftp --days 1
```

**Verify environment:**
```bash
printenv | grep GNSS
```

---

## Cost Estimation

### Free Tier (Render)

- **Compute:** 750 hours/month (enough for 24/7)
- **Bandwidth:** 100 GB/month
- **Storage:** Limited by instance (ephemeral)
- **Total:** $0/month

**Best for:**
- Development/testing
- Low-traffic demos
- Personal projects

### Paid Tier (Render)

- **Instance:** Starter ($7/month)
- **Database:** PostgreSQL (free tier available)
- **Total:** ~$7-15/month

**Best for:**
- Production use
- Multiple users
- Persistent storage needs

### PythonAnywhere Comparison

- **Free:** Not suitable (FTP blocked)
- **Hacker ($5/month):** Unrestricted internet
- **Total:** $5/month

**Best for:**
- Simple deployments
- Users familiar with platform

---

## Performance Optimization

### 1. Enable Connection Pooling

```python
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'max_overflow': 20,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}
```

### 2. Add Caching

Use Flask-Caching with Redis:

```python
from flask_caching import Cache
cache = Cache(app, config={'CACHE_TYPE': 'redis'})

@app.route('/api/clock-series')
@cache.cached(timeout=300)
def get_clock_series():
    # ...
```

### 3. Optimize Queries

Add indexes to frequently queried columns:

```python
class SatClock(db.Model):
    __table_args__ = (
        db.Index('idx_sat_epoch', 'sat_id', 'epoch'),
        db.Index('idx_epoch', 'epoch'),
    )
```

---

## Security Checklist

- [ ] Set strong `SECRET_KEY` (use `secrets.token_hex(32)`)
- [ ] Set `FLASK_DEBUG=0` in production
- [ ] Use environment variables for credentials
- [ ] Enable HTTPS (automatic on Render)
- [ ] Implement rate limiting for API endpoints
- [ ] Add authentication for admin endpoints
- [ ] Regular dependency updates (`uv pip install --upgrade`)
- [ ] Database backups configured

---

## Monitoring

### Health Check Endpoint

Add to `app.py`:

```python
@app.route('/health')
def health():
    """Health check for monitoring"""
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'healthy'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500
```

### Uptime Monitoring

1. **UptimeRobot** (free):
   - Monitor `/health` endpoint every 5 min
   - Email/SMS alerts

2. **Render Built-in Metrics**:
   - Dashboard shows CPU, memory, request count
   - Logs available in real-time

3. **Sentry Integration**:
   ```python
   import sentry_sdk
   sentry_sdk.init(
       dsn=os.environ.get('SENTRY_DSN'),
       traces_sample_rate=1.0,
   )
   ```

---

## Next Steps

1. ✅ Deploy to Render (free tier)
2. ✅ Configure automated ETL via GitHub Actions
3. ✅ Set up monitoring (UptimeRobot)
4. ⏭️ Add authentication for admin endpoints
5. ⏭️ Implement database backup strategy
6. ⏭️ Consider PostgreSQL upgrade for production

---

## Support

- **Documentation:** See [README.md](README.md)
- **Issues:** GitHub Issues
- **Render Docs:** https://render.com/docs
