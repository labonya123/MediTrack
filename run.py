import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from config import HOST, PORT, DEBUG, USE_CLOUD, SYNC_INTERVAL_SECONDS


def main():
    print("\n" + "="*55)
    print("  🏥  MediTrack — Emergency Medical Record System")
    print("  Version 3.0.0 — Cloud Sync Enabled")
    print("="*55)

    app = create_app()

    with app.app_context():
        try:
            from app.database.seed_data import seed_all
            seed_all()
        except Exception as e:
            print(f"⚠️  Seed warning: {e}")

    print(f"\n✅ MediTrack is running!")
    print(f"🌐 Open: http://localhost:{PORT}")
    print(f"\n🔑 Test Accounts:")
    print(f"   Admin:     admin / admin123")
    print(f"   Doctor:    dr_sharma / doctor123")
    print(f"   Paramedic: paramedic1 / para123")
    print(f"   Patient:   rahul_kumar / patient123")
    if USE_CLOUD:
        print(f"\n☁️  Cloud sync ON — syncing every {SYNC_INTERVAL_SECONDS}s")
    else:
        print(f"\n💾 Local mode — set USE_CLOUD=True in .env to enable cloud sync")
    print(f"\n⏹  Press CTRL+C to stop")
    print("="*55 + "\n")

    app.run(host=HOST, port=PORT, debug=DEBUG)


if __name__ == '__main__':
    main()