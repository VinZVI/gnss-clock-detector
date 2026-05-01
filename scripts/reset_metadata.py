
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gnss_clock.app import create_app
from gnss_clock.models import db, SatelliteMeta, SatelliteStatusHistory, SatelliteOrbitHistory, EtlLog

def reset_metadata():
    app = create_app()
    with app.app_context():
        print("Cleaning up metadata and status history...")
        
        # 1. Delete actual data
        n_status = db.session.query(SatelliteStatusHistory).delete()
        n_orbit  = db.session.query(SatelliteOrbitHistory).delete()
        n_meta   = db.session.query(SatelliteMeta).delete()
        
        # 2. Reset ETL logs for these file types so they can be re-downloaded/re-parsed
        n_logs = db.session.query(EtlLog).filter(
            (EtlLog.ftp_file.like('%.glo')) |
            (EtlLog.ftp_file.like('%.gps')) |
            (EtlLog.ftp_file.like('%.bds')) |
            (EtlLog.ftp_file.like('%.gal')) |
            (EtlLog.ftp_file.like('%.qzs')) |
            (EtlLog.ftp_file.like('%.oe')) |
            (EtlLog.ftp_file.like('%.hlt'))
        ).delete(synchronize_session=False)
        
        db.session.commit()
        
        print(f"Removed:")
        print(f"  - {n_meta} satellite passports")
        print(f"  - {n_status} health history records")
        print(f"  - {n_orbit} orbital history records")
        print(f"  - {n_logs} ETL log entries reset")
        print("\nSuccess. Now run ETL to reload data:")
        print("uv run python -m gnss_clock.etl --source ftp --days 30")

if __name__ == "__main__":
    if input("This will wipe all satellite metadata. Continue? (y/n): ").lower() == 'y':
        reset_metadata()
    else:
        print("Cancelled.")
