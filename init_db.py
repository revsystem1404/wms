from app import app, db
from werkzeug.security import generate_password_hash
from sqlalchemy import inspect

print("Starting database initialization...")

with app.app_context():
    inspector = inspect(db.engine)
    existing_tables = inspector.get_table_names()
    print(f"Existing tables before reset: {existing_tables}")
    
    print("Dropping all tables...")
    db.drop_all()
    
    print("Creating all database tables...")
    db.create_all()
    
    # List all tables after creation
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print(f"Created tables: {tables}")
    
    # Commit changes
    db.session.commit()
    print("Database initialization complete!")