#!/usr/bin/env python3
"""
Database migration script for Render.com PostgreSQL.
Fixes unique constraint issues and adds detection_method column.

Usage:
    python migrate_database.py

This script will:
1. Check current database structure
2. Add detection_method column if missing
3. Drop old constraint uix_anomaly_sat_epoch
4. Create new constraint uix_anomaly_sat_epoch_method
5. Update existing records with default method='bias'
6. Verify the migration succeeded
"""

import sys
from gnss_clock.app import create_app
from gnss_clock.models import db, SatClockAnomaly

def check_current_state():
    """Check current database structure."""
    print("🔍 Checking current database state...")
    
    try:
        # Check columns
        result = db.session.execute(
            db.text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'sat_clock_anomaly'
                ORDER BY ordinal_position
            """)
        )
        
        print("\n📋 Current columns:")
        columns = {}
        for row in result:
            print(f"   • {row[0]} ({row[1]}) {'NULL' if row[2] == 'YES' else 'NOT NULL'}")
            columns[row[0]] = row[1]
        
        # Check indexes/constraints
        result = db.session.execute(
            db.text("""
                SELECT indexname, indexdef 
                FROM pg_indexes 
                WHERE tablename = 'sat_clock_anomaly'
                ORDER BY indexname
            """)
        )
        
        print("\n📋 Current indexes/constraints:")
        indexes = []
        for row in result:
            print(f"   • {row[0]}")
            indexes.append(row[0])
        
        # Check record counts
        total_records = db.session.query(SatClockAnomaly).count()
        records_with_method = db.session.query(SatClockAnomaly).filter(
            SatClockAnomaly.detection_method.isnot(None)
        ).count() if 'detection_method' in columns else 0
        
        print(f"\n📊 Statistics:")
        print(f"   Total anomaly records: {total_records}")
        print(f"   Records with detection_method: {records_with_method}")
        
        return columns, indexes
        
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        return None, None


def add_detection_method_column(columns):
    """Add detection_method column if it doesn't exist."""
    if 'detection_method' in columns:
        print("✅ Column detection_method already exists")
        return True
    
    print("\n➕ Adding detection_method column...")
    try:
        db.session.execute(
            db.text("ALTER TABLE sat_clock_anomaly ADD COLUMN detection_method VARCHAR(10) DEFAULT 'bias'")
        )
        db.session.commit()
        print("✅ Column added successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to add column: {e}")
        db.session.rollback()
        return False


def drop_old_constraint(indexes):
    """Drop old constraint uix_anomaly_sat_epoch."""
    if 'uix_anomaly_sat_epoch' not in indexes:
        print("✅ Old constraint uix_anomaly_sat_epoch does not exist")
        return True
    
    print("\n🗑️  Dropping old constraint uix_anomaly_sat_epoch...")
    try:
        # Use ALTER TABLE DROP CONSTRAINT (not DROP INDEX)
        db.session.execute(
            db.text("ALTER TABLE sat_clock_anomaly DROP CONSTRAINT IF EXISTS uix_anomaly_sat_epoch")
        )
        db.session.commit()
        print("✅ Old constraint dropped successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to drop constraint: {e}")
        db.session.rollback()
        return False


def create_new_constraint(indexes):
    """Create new constraint uix_anomaly_sat_epoch_method."""
    if 'uix_anomaly_sat_epoch_method' in indexes:
        print("✅ New constraint uix_anomaly_sat_epoch_method already exists")
        return True
    
    print("\n✨ Creating new constraint uix_anomaly_sat_epoch_method...")
    try:
        db.session.execute(
            db.text("""
                CREATE UNIQUE INDEX uix_anomaly_sat_epoch_method 
                ON sat_clock_anomaly(sat_id, epoch, detection_method)
            """)
        )
        db.session.commit()
        print("✅ New constraint created successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to create constraint: {e}")
        db.session.rollback()
        return False


def update_existing_records():
    """Update existing records without detection_method to 'bias'."""
    print("\n🔄 Updating existing records...")
    try:
        result = db.session.execute(
            db.text("""
                UPDATE sat_clock_anomaly 
                SET detection_method = 'bias'
                WHERE detection_method IS NULL
            """)
        )
        db.session.commit()
        updated = result.rowcount
        print(f"✅ Updated {updated} records with detection_method='bias'")
        return True
    except Exception as e:
        print(f"❌ Failed to update records: {e}")
        db.session.rollback()
        return False


def verify_migration():
    """Verify migration succeeded."""
    print("\n✅ Verifying migration...")
    
    try:
        # Check columns
        result = db.session.execute(
            db.text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'sat_clock_anomaly'
                AND column_name = 'detection_method'
            """)
        )
        
        if not result.first():
            print("❌ Column detection_method not found!")
            return False
        
        # Check indexes
        result = db.session.execute(
            db.text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'sat_clock_anomaly'
                AND indexname = 'uix_anomaly_sat_epoch_method'
            """)
        )
        
        if not result.first():
            print("❌ Index uix_anomaly_sat_epoch_method not found!")
            return False
        
        # Check old index is gone
        result = db.session.execute(
            db.text("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'sat_clock_anomaly'
                AND indexname = 'uix_anomaly_sat_epoch'
            """)
        )
        
        if result.first():
            print("⚠️  WARNING: Old index uix_anomaly_sat_epoch still exists!")
            return False
        
        # Check all records have detection_method
        result = db.session.execute(
            db.text("""
                SELECT COUNT(*) 
                FROM sat_clock_anomaly 
                WHERE detection_method IS NULL
            """)
        )
        
        null_count = result.scalar()
        if null_count > 0:
            print(f"⚠️  WARNING: {null_count} records still have NULL detection_method!")
            return False
        
        print("✅ Migration verified successfully!")
        print("\n📊 Final state:")
        print("   ✓ Column detection_method exists")
        print("   ✓ Index uix_anomaly_sat_epoch_method exists")
        print("   ✓ Old index uix_anomaly_sat_epoch removed")
        print("   ✓ All records have detection_method set")
        
        return True
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False


def main():
    """Run database migration."""
    print("=" * 70)
    print("🔧 GNSS Clock Detector - Database Migration")
    print("=" * 70)
    
    app = create_app()
    
    with app.app_context():
        # Step 1: Check current state
        columns, indexes = check_current_state()
        if columns is None:
            print("\n❌ Cannot proceed without checking database state")
            return False
        
        # Step 2: Add detection_method column
        if not add_detection_method_column(columns):
            print("\n❌ Migration failed at step 2")
            return False
        
        # Step 3: Drop old constraint
        if not drop_old_constraint(indexes):
            print("\n❌ Migration failed at step 3")
            return False
        
        # Step 4: Create new constraint
        if not create_new_constraint(indexes):
            print("\n❌ Migration failed at step 4")
            return False
        
        # Step 5: Update existing records
        if not update_existing_records():
            print("\n❌ Migration failed at step 5")
            return False
        
        # Step 6: Verify
        if not verify_migration():
            print("\n❌ Migration verification failed")
            return False
        
        print("\n" + "=" * 70)
        print("✅ Миграция успешно завершена!")
        print("=" * 70)
        print("\nТеперь можно:")
        print("1. Перезапустить приложение")
        print("2. Запустить ETL: python -m gnss_clock.etl --source nasa --days 3")
        print("3. Или использовать кнопку '🔄 Пересчитать методы' в UI")
        print("\n")
        
        return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
