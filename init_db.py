from app import app, db
from werkzeug.security import generate_password_hash

print("Starting database initialization...")

with app.app_context():
    print("Creating all database tables...")
    db.create_all()
    
    # Check if we need to create initial admin access
    from app import VehicleKeyUser, TimeTrackerUser, DepartmentUser
    
    # Add a default admin for the department login if none exists
    if not DepartmentUser.query.filter_by(username="admin").first():
        print("Creating default department admin user...")
        admin_user = DepartmentUser(
            department="admin",
            username="admin", 
            password=generate_password_hash("rev180325")
        )
        db.session.add(admin_user)
    
    # Commit changes
    db.session.commit()
    print("Database initialization complete!")