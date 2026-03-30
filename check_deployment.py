#!/usr/bin/env python3
"""
Quick diagnostic script to check deployment status on Render.com

Usage:
    python check_deployment.py
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def check_environment():
    """Check environment variables"""
    print("=" * 60)
    print("ENVIRONMENT CHECK")
    print("=" * 60)
    
    env_vars = {
        'GNSS_DB_TYPE': 'Database type',
        'DATABASE_URL': 'PostgreSQL connection string',
        'GNSS_DATA_SOURCE': 'Data source (ftp/nasa)',
        'NASA_EARTHDATA_USER': 'NASA username',
        'FLASK_DEBUG': 'Debug mode',
        'SECRET_KEY': 'Secret key',
    }
    
    for var, desc in env_vars.items():
        value = os.environ.get(var, 'NOT SET')
        if value == 'NOT SET':
            print(f"❌ {var:30s} : {desc}")
        elif var in ['DATABASE_URL', 'SECRET_KEY', 'NASA_EARTHDATA_PASS']:
            # Hide sensitive values
            print(f"✅ {var:30s} : {'*' * 8}")
        else:
            print(f"✅ {var:30s} : {value}")
    print()

def check_database_config():
    """Check database configuration"""
    print("=" * 60)
    print("DATABASE CONFIGURATION")
    print("=" * 60)
    
    try:
        from gnss_clock import config
        
        print(f"DB Type: {config.DB_TYPE}")
        print(f"DB URI:  {'postgresql://' + config.DATABASE_URI.split('://')[1] if 'postgresql' in config.DATABASE_URI else config.DATABASE_URI}")
        
        # Test connection
        from gnss_clock.app import create_app
        from gnss_clock.models import db
        
        app = create_app()
        with app.app_context():
            # Try to connect
            db.session.execute(db.text("SELECT 1"))
            print("✅ Database connection successful!")
            
            # Check tables
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            print(f"📊 Tables found: {len(tables)}")
            for table in tables[:5]:  # Show first 5
                print(f"   - {table}")
            if len(tables) > 5:
                print(f"   ... and {len(tables) - 5} more")
                
    except Exception as e:
        print(f"❌ Database error: {e}")
    print()

def check_api_endpoints(base_url="https://gnss-clock-detector.onrender.com"):
    """Check API endpoints"""
    print("=" * 60)
    print(f"API ENDPOINTS ({base_url})")
    print("=" * 60)
    
    import requests
    
    endpoints = [
        ("/", "Web UI"),
        ("/api/satellites", "Satellite list"),
        ("/api/etl/status", "ETL logs"),
        ("/api/admin/etl/status", "Background ETL status"),
        ("/api/sources/status", "Source status"),
    ]
    
    for endpoint, name in endpoints:
        try:
            url = base_url + endpoint
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                print(f"✅ {name:30s} : {endpoint}")
            else:
                print(f"⚠️  {name:30s} : HTTP {resp.status_code}")
        except requests.exceptions.Timeout:
            print(f"⏱️  {name:30s} : Timeout (cold start?)")
        except Exception as e:
            print(f"❌ {name:30s} : {str(e)[:50]}")
    print()

def main():
    """Main diagnostic"""
    print("\n🔍 GNSS Clock Detector - Deployment Diagnostic\n")
    
    # Check environment
    check_environment()
    
    # Check database
    check_database_config()
    
    # Check API (optional)
    if '--no-api' not in sys.argv:
        check_api_endpoints()
    
    print("=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)
    print("\n💡 Tips:")
    print("  - If DATABASE_URL missing, add PostgreSQL on Render")
    print("  - If API timeouts, wait for cold start (~30-60s)")
    print("  - Run ETL via UI button or Shell: python -m gnss_clock.etl --source nasa --days 3")
    print()

if __name__ == "__main__":
    main()
