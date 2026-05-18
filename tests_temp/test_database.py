# test_database.py
# Tests that all database tables create correctly

import sys
import os
sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', 'backend')
)

from app.models.database import create_tables, DB_PATH, engine
from sqlalchemy import inspect

if __name__ == "__main__":
    print("Creating database tables...")
    print(f"Database location: {DB_PATH}")
    print("-" * 50)

    # Create all tables
    create_tables()

    # Verify tables were created
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    print(f"\n✅ Tables created: {len(tables)}")
    for table in tables:
        columns = inspector.get_columns(table)
        print(f"\n📋 {table} ({len(columns)} columns)")
        for col in columns:
            print(f"   - {col['name']:25} {str(col['type'])}")

    print("\n✅ Database test passed!")
    print(f"Your database file: {DB_PATH}")