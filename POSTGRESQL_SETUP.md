# PostgreSQL Setup Guide for Render.com

## Why PostgreSQL?

**SQLite Issues on Cloud:**
- ❌ File-based (ephemeral storage on cloud)
- ❌ Database deleted when container restarts
- ❌ No concurrent writes (locking issues)
- ❌ Not suitable for production

**PostgreSQL Benefits:**
- ✅ Persistent storage (survives restarts)
- ✅ Automatic backups
- ✅ Better concurrency
- ✅ Production-ready
- ✅ Free tier available on Render

---

## Quick Setup (5 minutes)

### Step 1: Create PostgreSQL Database on Render

1. Go to **Render Dashboard** → your service
2. Click **"Add Database"** button
3. Configure:
   ```
   Name: gnss-clock-db
   Region: Frankfurt (same as your web service)
   Plan: Free ($0/month)
   Database Type: PostgreSQL
   Version: 14 or later
   ```
4. Click **"Create Database"**
5. Wait ~2-3 minutes for provisioning

---

### Step 2: Get Connection String

After database is created:

1. In Render Dashboard, click on your database
2. Copy the **"Internal Database URL"**:
   ```
   postgresql://user:password@hostname:5432/dbname?sslmode=require
   ```

**Important:** Use **Internal** URL (not External) for same-region services!

---

### Step 3: Configure Environment Variables

In Render Dashboard → **Environment** tab:

```bash
# Add these variables:

GNSS_DB_TYPE=postgresql
DATABASE_URL=postgresql://user:pass@hostname:5432/dbname?sslmode=require

# Optional: disable admin ETL endpoint if you want manual control only
# GNSS_DISABLE_ADMIN_ETL=true
```

**Save changes!**

---

### Step 4: Redeploy

Render will automatically redeploy when you save environment variables.

Wait for build to complete (~2-3 minutes).

---

### Step 5: Run Initial ETL

After deployment:

1. Open **Shell** tab in Render Dashboard
2. Verify database connection:
   ```bash
   python -c "from gnss_clock import config; print('DB Type:', config.DB_TYPE)"
   # Should output: DB Type: postgresql
   ```

3. Run ETL:
   ```bash
   python -m gnss_clock.etl --source nasa --days 3
   ```

4. Check API:
   ```bash
   curl https://gnss-clock-detector.onrender.com/api/satellites
   ```

---

## Migration from SQLite to PostgreSQL

If you already have data in SQLite and want to migrate:

### Option 1: Manual Export/Import

```bash
# Download SQLite database locally
# Export to JSON
python -c "
import sqlite3, json
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()
cursor.execute('SELECT * FROM sat_clock')
data = cursor.fetchall()
with open('backup.json', 'w') as f:
    json.dump(data, f)
"

# Then import to PostgreSQL (custom script needed)
```

### Option 2: Fresh Start (Recommended)

Just run fresh ETL with PostgreSQL:
```bash
python -m gnss_clock.etl --source nasa --days 7
```

Since data is from public APIs, easy to reload!

---

## Cost Estimation

### Render Free Tier Includes:

- **Web Services:** 750 hours/month (~24/7)
- **Database:** 
  - Storage: 1 GB
  - Bandwidth: Unlimited
  - CPU: Shared
  - RAM: 256 MB

**Your app should fit comfortably in free tier!**

### When to Upgrade:

- Database > 1 GB (unlikely for 14 days of data)
- Need more concurrent connections
- Want dedicated CPU/RAM

**Starter Plan:** $7/month for database

---

## Performance Optimization

### Connection Pooling (Already Configured!)

The app includes these optimizations:

```python
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,      # Test connections before use
    'pool_recycle': 3600,       # Recycle after 1 hour
}
```

### Indexes (Automatic)

SQLAlchemy creates indexes on:
- `sat_id` column
- `epoch` column
- Foreign keys

### Query Optimization

Avoid:
```python
# Don't load all records at once!
SatClock.query.all()
```

Use:
```python
# Paginate results
SatClock.query.limit(1000).all()

# Or use date ranges
SatClock.query.filter(
    SatClock.epoch >= start_date,
    SatClock.epoch <= end_date
).all()
```

---

## Troubleshooting

### Error: DATABASE_URL required

**Problem:** Missing environment variable

**Solution:**
```bash
# In Render Dashboard → Environment
DATABASE_URL=postgresql://...
```

---

### Error: relation "sat_clock" does not exist

**Problem:** Tables not created yet

**Solution:**
```bash
# In Render Shell
python -c "
from gnss_clock.app import create_app
from gnss_clock.models import db
app = create_app()
with app.app_context():
    db.create_all()
print('Tables created!')
"
```

---

### Error: connection refused

**Problem:** Wrong database URL or firewall

**Solutions:**
1. Verify DATABASE_URL is correct (copy-paste error?)
2. Ensure database and web service are in same region
3. Check Render dashboard for database status

---

### Slow Queries

**Symptoms:** API takes >5 seconds

**Solutions:**
1. Reduce data retention:
   ```
   GNSS_ETL_RETAIN_DAYS=7
   ```

2. Add composite index (run in psql):
   ```sql
   CREATE INDEX idx_sat_epoch ON sat_clock (sat_id, epoch);
   ```

3. Enable query logging to identify bottlenecks:
   ```bash
   # In Render Environment
   SQLALCHEMY_ECHO=true
   ```

---

## Backup & Restore

### Automatic Backups (Render Managed)

Render automatically backs up PostgreSQL:
- Daily backups retained for 7 days
- Can restore to any point in time
- Accessible via Render Dashboard

### Manual Backup

```bash
# In Render Shell
pg_dump $DATABASE_URL > backup.sql
```

### Manual Restore

```bash
# Upload backup.sql to Render Shell
psql $DATABASE_URL < backup.sql
```

---

## Monitoring

### Check Database Size

```bash
# In Render Shell
psql $DATABASE_URL -c "
SELECT 
  pg_size_pretty(pg_database_size(current_database())) as size
;"
```

### Check Connection Count

```bash
psql $DATABASE_URL -c "
SELECT count(*) as active_connections 
FROM pg_stat_activity;
"
```

### Render Dashboard Metrics

Monitor:
- **CPU Usage** (should be <80%)
- **Memory Usage** (should be <200 MB)
- **Disk Usage** (should be <900 MB)
- **Connections** (should be <50)

---

## Security Best Practices

✅ **Already Done:**
- SSL/TLS encryption (`?sslmode=require`)
- Password authentication
- Internal network only (not exposed to internet)

🔒 **Additional Recommendations:**

1. **Rotate credentials periodically:**
   - Render Dashboard → Database → Rotate Credentials
   
2. **Limit admin access:**
   ```bash
   GNSS_DISABLE_ADMIN_ETL=true
   ```

3. **Use secrets management:**
   - Store credentials in Render Secrets
   - Not in git or .env files

---

## Alternative: External PostgreSQL

If you prefer external provider:

### Options:

1. **Supabase** (Free tier, excellent)
   - https://supabase.com
   - 500 MB free, auto-backups

2. **Neon** (Serverless, generous free tier)
   - https://neon.tech
   - 0.5 GB free, branching

3. **AWS RDS** (Free tier 12 months)
   - 750 hours/month
   - More complex setup

### Configuration:

Same process, just use their connection string:
```bash
DATABASE_URL=postgresql://user:pass@host.region.rds.amazonaws.com:5432/dbname
```

---

## Summary

**Current Status:**
- ✅ App supports both SQLite and PostgreSQL
- ✅ Auto-detects via `GNSS_DB_TYPE` env var
- ✅ Connection pooling configured
- ✅ Error handling improved

**Recommended Setup:**
- **Development:** SQLite (local, fast, simple)
- **Production:** PostgreSQL (Render managed, persistent, reliable)

**Next Steps:**
1. Create PostgreSQL database on Render (2 min)
2. Add `DATABASE_URL` to environment (1 min)
3. Redeploy (automatic, 3 min)
4. Run initial ETL (5 min)
5. **Done!** 🎉

Total time: ~10 minutes for production-ready database!
