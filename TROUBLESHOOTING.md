# Troubleshooting Guide - Render.com Deployment

## Issue: API Not Responding

### Symptoms
```bash
curl https://gnss-clock-detector.onrender.com/api/satellites
# No response or timeout
```

### Causes & Solutions

#### 1. **Empty Database (Most Common)**

**Problem:** No data in database yet

**Solution:**
```bash
# Access Render Shell from dashboard
python -m gnss_clock.etl --source nasa --days 3
```

**Verify:**
```bash
curl https://gnss-clock-detector.onrender.com/api/etl/status
# Should show recent ETL run
```

---

#### 2. **Cold Start Delay**

**Problem:** Render free tier spins down after 15 min inactivity

**Symptoms:**
- First request times out (30-50 seconds)
- Subsequent requests work fine

**Solution:** 
- Wait ~1 minute for cold start
- Or use UptimeRobot to ping every 5 min (keeps instance warm)

---

#### 3. **FTP Blocked on Cloud Platforms**

**Problem:** FTP connections blocked by cloud provider firewall

**Symptoms:**
```
ETL failed: Connection refused
ftp.glonass-iac.ru timeout
```

**Solution:** ✅ **Already fixed!** 

The deployment now uses **NASA CDDIS only** (not FTP):
- `GNSS_DATA_SOURCE=nasa` (default for Render)
- Uses HTTPS instead of FTP
- More reliable on cloud platforms

---

#### 4. **NASA Credentials Missing**

**Problem:** NASA_EARTHDATA_USER/PASS not configured

**Symptoms:**
```
NASA ConnectionError: 401 Unauthorized
No credentials provided
```

**Solution:**

1. Register at: https://urs.earthdata.nasa.gov/users/new
2. In Render Dashboard → Environment:
   ```
   NASA_EARTHDATA_USER=your_username
   NASA_EARTHDATA_PASS=your_password
   ```
3. Redeploy (automatic on next git push)

---

#### 5. **Database Locked / Corrupted**

**Problem:** SQLite file locked or corrupted

**Symptoms:**
```
sqlite3.OperationalError: database is locked
```

**Solution:**

**Option A - Delete and recreate (loses data):**
```bash
# In Render Shell
rm db.sqlite3
python -m gnss_clock.etl --source nasa --days 3
```

**Option B - Enable WAL mode (better concurrency):**

Add to `.env`:
```
GNSS_DB_WAL_MODE=1
```

Or upgrade to PostgreSQL for production.

---

## Quick Diagnostic Commands

### Check if app is running
```bash
curl -I https://gnss-clock-detector.onrender.com/health
# Should return HTTP 200
```

### Check ETL status
```bash
curl https://gnss-clock-detector.onrender.com/api/etl/status
```

### Check database has data
```bash
curl https://gnss-clock-detector.onrender.com/api/satellites
# Returns: {"satellites": [...]} or {"satellites": []}
```

---

## Manual ETL Run (Recommended First Step)

1. **Open Render Dashboard**
2. Go to your service → **Shell** tab
3. Run:
   ```bash
   # Verify environment
   echo $GNSS_DATA_SOURCE
   # Should output: nasa
   
   # Run ETL with NASA
   python -m gnss_clock.etl --source nasa --days 3
   
   # Check result
   ls -lh db.sqlite3
   ```

4. **Test API:**
   ```bash
   curl https://gnss-clock-detector.onrender.com/api/satellites
   ```

---

## NASA CDDIS Connection Issues

### Error: 403 Forbidden

**Cause:** Proxy blocking (common on free tiers)

**Solutions:**

1. **Check credentials:**
   ```bash
   python -c "from gnss_clock.nasa_client import NasaClient; c = NasaClient(); print(c.check_credentials())"
   ```

2. **Try bearer token instead of user/pass:**
   - Login to https://urs.earthdata.nasa.gov
   - Generate Token → Copy token
   - Add to Render Environment:
     ```
     NASA_EARTHDATA_TOKEN=your_token_here
     ```

3. **Wait and retry:**
   - NASA may rate-limit (wait 1 hour)

---

### Error: Connection Reset (10054)

**Cause:** TLS handshake issues on Windows

**Solution:** Use Bearer Token method (see above)

---

## Logs Analysis

### View Logs in Real-time

Render Dashboard → **Logs** tab

Or filter by level:
```
INFO    - Normal operation
WARNING - Non-critical issues
ERROR   - Something failed
```

### Common Log Messages

**✅ Good:**
```
INFO [gnss_clock.etl] ETL started [nasa]
INFO [gnss_clock.nasa_client] Downloaded 10 files
INFO [gnss_clock.etl] ETL completed: 237468 records
```

**❌ Bad:**
```
ERROR [gnss_clock.nasa_client] NASA ConnectionError
ERROR [gnss_clock.etl] ETL failed: no files downloaded
```

---

## Environment Variables Checklist

In Render Dashboard → Environment, ensure these are set:

```bash
✅ FLASK_DEBUG=0
✅ SECRET_KEY=<random-string>
✅ GNSS_DATA_SOURCE=nasa
✅ GNSS_ETL_DAYS_BACK=3
✅ GNSS_ETL_RETAIN_DAYS=14
✅ GNSS_MAD_THRESHOLD=3.0
✅ NASA_EARTHDATA_USER=<your-username>
✅ NASA_EARTHDATA_PASS=<your-password>
```

---

## Performance Optimization

### Slow API Response

**Add connection pooling:**

Update `config.py`:
```python
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'max_overflow': 20,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}
```

### Database Too Large

**Reduce retention period:**
```
GNSS_ETL_RETAIN_DAYS=7  # Keep only 7 days instead of 14
```

**Or clean old data:**
```sql
DELETE FROM sat_clock WHERE epoch < datetime('now', '-7 days');
VACUUM;
```

---

## When All Else Fails

### Full Reset Procedure

1. **Delete database:**
   ```bash
   rm db.sqlite3
   ```

2. **Clear environment:**
   - Remove all env vars in Render Dashboard
   - Save

3. **Re-add environment variables** (see checklist above)

4. **Redeploy:**
   - Go to Renders Dashboard
   - Click "Manual Deploy"
   - Wait for build to complete

5. **Run fresh ETL:**
   ```bash
   python -m gnss_clock.etl --source nasa --days 1
   ```

---

## Getting Help

### Information to Provide

When asking for help, include:

1. **Error message** (full traceback)
2. **Recent logs** (last 50 lines)
3. **Environment variables** (without passwords!)
4. **What you tried** already

### Where to Get Help

- **GitHub Issues:** https://github.com/VinZVI/gnss-clock-detector/issues
- **Render Community:** https://community.render.com
- **Logs:** Always check first in Render Dashboard → Logs

---

## Success Indicators

You'll know it's working when:

✅ `/api/satellites` returns list of satellites  
✅ `/api/etl/status` shows recent successful ETL run  
✅ Web UI loads and shows satellite chips  
✅ Graph displays clock bias data  
✅ Anomalies are highlighted in red  

**Example success response:**
```json
{
  "satellites": [
    {"sat_id": "R01", "anomalies": 2},
    {"sat_id": "R02", "anomalies": 0}
  ]
}
```
