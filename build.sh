#!/bin/bash
# Build script for Render

# Exit on error
set -o errexit

# Install Python dependencies
pip install -r requirements.txt

# Create the static/uploads directory if it doesn't exist
mkdir -p static/uploads

# Run database migrations
python -c "from app import app, db; app.app_context().push(); db.create_all()"