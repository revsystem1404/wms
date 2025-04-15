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
    
    # Check if we need to create initial admin access
    from app import VehicleKeyUser, TimeTrackerUser, DepartmentUser, Employee
    
    # Add a default admin for the department login if none exists
    print("Creating default department admin user...")
    admin_user = DepartmentUser(
        department="admin",
        username="admin", 
        password=generate_password_hash("rev180325")
    )
    db.session.add(admin_user)
    
    # Add a default employee
    print("Creating default employee...")
    default_employee = Employee(
        name="Default Employee",
        hourly_rate=15.00
    )
    db.session.add(default_employee)
    
    # Commit changes
    db.session.commit()
    print("Database initialization complete!")