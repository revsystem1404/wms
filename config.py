import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', '7654321jJ')
    
    # Database configuration
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Use DATABASE_URL environment variable (provided by Render) if available,
    # otherwise use SQLite for local development
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///employees.db')
    
    # If the URI starts with 'postgres://', change it to 'postgresql://' for SQLAlchemy 1.4+
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)
    
    # Upload folder configuration
    UPLOAD_FOLDER = os.path.join('static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    
    # Scheduler configuration
    SCHEDULER_API_ENABLED = True