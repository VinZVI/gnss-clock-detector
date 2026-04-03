"""
Manual fix for duplicate index issue on Render.com PostgreSQL.
Run this once to drop the old constraint and recreate properly.
"""
import os
from gnss_clock.app import create_app
from gnss_clock.models import db

def fix_unique_constraint():
    """Drop old index and create new one with detection_method column."""
    app = create_app()
    
    with app.app_context():
        print("🔧 Fixing sat_clock_anomaly unique constraint...")
        
        # Step 1: Check existing indexes
        print("\n📋 Current indexes:")
        try:
            result = db.session.execute(
                db.text("""
                    SELECT indexname, indexdef 
                    FROM pg_indexes 
                    WHERE tablename = 'sat_clock_anomaly'
                    ORDER BY indexname
                """)
            )
            for row in result:
                print(f"   {row[0]}: {row[1][:100]}...")
        except Exception as e:
            print(f"   ⚠️  Could not list indexes: {e}")
        
        # Step 2: Drop old index if exists
        print("\n🗑️  Dropping old index uix_anomaly_sat_epoch...")
        try:
            db.session.execute(db.text("DROP INDEX IF EXISTS uix_anomaly_sat_epoch"))
            db.session.commit()
            print("   ✅ Old index dropped successfully")
        except Exception as e:
            print(f"   ⚠️  Failed to drop old index: {e}")
            db.session.rollback()
        
        # Step 3: Drop new index if it exists (to recreate)
        print("\n🗑️  Dropping new index if exists...")
        try:
            db.session.execute(db.text("DROP INDEX IF EXISTS uix_anomaly_sat_epoch_method"))
            db.session.commit()
            print("   ✅ New index dropped (will recreate)")
        except Exception as e:
            print(f"   ⚠️  Failed to drop new index: {e}")
            db.session.rollback()
        
        # Step 4: Create new unique index with detection_method
        print("\n✨ Creating new unique index (sat_id, epoch, detection_method)...")
        try:
            db.session.execute(
                db.text("""
                    CREATE UNIQUE INDEX uix_anomaly_sat_epoch_method 
                    ON sat_clock_anomaly(sat_id, epoch, detection_method)
                """)
            )
            db.session.commit()
            print("   ✅ New index created successfully!")
        except Exception as e:
            print(f"   ❌ Failed to create new index: {e}")
            db.session.rollback()
            return False
        
        # Step 5: Verify
        print("\n✅ Verification - Final indexes:")
        try:
            result = db.session.execute(
                db.text("""
                    SELECT indexname 
                    FROM pg_indexes 
                    WHERE tablename = 'sat_clock_anomaly'
                    ORDER BY indexname
                """)
            )
            indexes = [row[0] for row in result]
            for idx in indexes:
                print(f"   • {idx}")
            
            if 'uix_anomaly_sat_epoch_method' in indexes and 'uix_anomaly_sat_epoch' not in indexes:
                print("\n🎉 SUCCESS! Constraint fixed correctly.")
                return True
            else:
                print("\n⚠️  WARNING: Indexes may not be correct!")
                return False
                
        except Exception as e:
            print(f"   ⚠️  Could not verify: {e}")
            return False

if __name__ == "__main__":
    success = fix_unique_constraint()
    exit(0 if success else 1)
