from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from fpdf import FPDF
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger  # ✅ Ensure correct cron trigger import
import atexit
from sqlalchemy import extract
import os
from werkzeug.utils import secure_filename
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Set up the database
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Keep the ALLOWED_EXTENSIONS here
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Function to check allowed file types
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Employee model
class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    monthly_overtime = db.Column(db.Integer, default=0)  # Ensure this line is in the model
    hourly_rate = db.Column(db.Float, default=15.00)

class DepartmentUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False)  # Like 'MOT', 'Prep'
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class TimeTrackerUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)  # Store hashed passwords

class VehicleKeyUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)  # Store hashed passwords

class MOTLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_reg = db.Column(db.String(20), nullable=False)
    task = db.Column(db.String(100), nullable=False)
    technician = db.Column(db.String(100), nullable=False)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='in_progress')  # NEW
    submitted_at = db.Column(db.DateTime, default=datetime.now)  # NEW

class AssignedTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    department = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    image_filename = db.Column(db.String(255), nullable=True)
    assigned_to = db.Column(db.String(50), nullable=True)  # Technician username
    status = db.Column(db.String(20), default='pending')   # pending, in_progress, completed
    start_time = db.Column(db.DateTime, nullable=True)     # To store when the task starts
    complete_time = db.Column(db.DateTime, nullable=True)  # To store when the task is completed
    vehicle_reg = db.Column(db.String(20), nullable=True)
    
    # New fields for delivery/collection
    contact_name = db.Column(db.String(100), nullable=True)
    contact_number = db.Column(db.String(20), nullable=True)
    contact_address = db.Column(db.Text, nullable=True)
    contact_notes = db.Column(db.Text, nullable=True)

class AssignedTaskImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('assigned_task.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)

    task = db.relationship('AssignedTask', backref=db.backref('images', lazy=True))

class WorkSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    clock_in = db.Column(db.DateTime, nullable=False, default=datetime.now)
    clock_out = db.Column(db.DateTime, nullable=True)

    employee = db.relationship('Employee', backref=db.backref('sessions', lazy=True))

    def total_hours(self):
        if self.clock_in and self.clock_out:
            total_seconds = (self.clock_out - self.clock_in).total_seconds()
            total_minutes = int(total_seconds // 60)

            # Subtract 1 hour if total minutes > 7 hours (420 mins)
            if total_minutes > 420:
                total_minutes -= 60

            return max(total_minutes, 0)
        return 0
    
class VehicleKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    key_checkout_time = db.Column(db.DateTime, nullable=False, default=datetime.now)
    key_number = db.Column(db.String(5), nullable=False)  # Stores the last 5 digits of the key
    key_return_time = db.Column(db.DateTime, nullable=True)

    employee = db.relationship('Employee', backref=db.backref('vehicle_keys', lazy=True))

@app.route('/')
def home():
    return render_template('home.html')

# Vehicle Key model
@app.route('/add_vehicle_key', methods=['POST'])
def add_vehicle_key():
    employee_id = request.form.get('employee_id')  # Get selected employee
    key_number = request.form.get('key_number')  # Get entered key number

    if employee_id and key_number:
        new_key = VehicleKey(
            employee_id=employee_id,
            key_number=key_number,
            key_checkout_time=datetime.now()
        )
        db.session.add(new_key)
        db.session.commit()

    return redirect(url_for('vehicle_key_monitor'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == "rev180325":  # ✅ Set a secure password
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Incorrect password, try again!", "danger")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))

from datetime import datetime
from calendar import monthrange

@app.route('/admin_dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if 'admin_logged_in' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form.get('name')
        hourly_rate = request.form.get('hourly_rate')

        if name and hourly_rate:
            new_employee = Employee(name=name, hourly_rate=float(hourly_rate))
            db.session.add(new_employee)
            db.session.commit()

            # ✅ Flash success message
            flash(f"Employee '{name}' added successfully!", 'success')

            # ✅ Redirect to avoid duplicate submissions
            return redirect(url_for('admin_dashboard'))

    employees = Employee.query.all()
    time_tracker_users = TimeTrackerUser.query.all()
    vehicle_key_users = VehicleKeyUser.query.all()
    department_users = DepartmentUser.query.all()

    # 🔧 Setup for full-month workdays (Mon–Sat)
    year = datetime.now().year
    month = datetime.now().month
    days_in_month = monthrange(year, month)[1]

    workdays = sum(
        1 for day in range(1, days_in_month + 1)
        if datetime(year, month, day).weekday() < 6  # 0–5 = Mon–Sat
    )

    expected_minutes = workdays * 8 * 60  # 8 hours/day * 60 minutes

    for emp in employees:
        # Total worked time (in minutes)
        total_minutes = sum(session.total_hours() for session in emp.sessions)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        emp.total_worked_hours = f"{hours}:{minutes:02d}"

        # Regular pay
        emp.pay = round((total_minutes / 60) * emp.hourly_rate, 2)

        # Overtime
        overtime_minutes = max(total_minutes - expected_minutes, 0)
        emp.monthly_overtime = overtime_minutes // 60
        emp.overtime_pay = round((overtime_minutes / 60) * emp.hourly_rate, 2)

    db.session.commit()

    return render_template(
        'admin_dashboard.html',
        employees=employees,
        time_tracker_users=time_tracker_users,
        vehicle_key_users=vehicle_key_users,
        department_users=department_users
    )

from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import extract  # ✅ Make sure this is at the top
from collections import defaultdict
from sqlalchemy import extract
from datetime import datetime
from flask import render_template, redirect, url_for, flash, session

@app.route('/worklogs/mot', methods=['GET'])
def worklog_mot():
    if 'department_logged_in' not in session or session.get('department_name') != 'mot':
        flash("Unauthorized access", "danger")
        return redirect(url_for('department_login'))

    # Get current technician from session
    technician_id = session['department_logged_in']
    technician_user = DepartmentUser.query.get(technician_id)
    technician_name = technician_user.username

    # Load all logs for this technician for the current month
    now = datetime.now()
    logs = MOTLog.query.filter(
        MOTLog.technician == technician_name,
        extract('month', MOTLog.start_time) == now.month,
        extract('year', MOTLog.start_time) == now.year
    ).order_by(MOTLog.start_time.desc()).all()

    # Logs still in progress (for that technician)
    in_progress_logs = [log for log in logs if log.status == 'in_progress']

    # ✅ Logs submitted today (completed)
    today = now.date()
    log_count = sum(
        1 for log in logs
        if log.status == 'completed' and log.end_time and log.end_time.date() == today
    )

    # ✅ Logs completed this month (new count)
    log_count_this_month = MOTLog.query.filter(
        MOTLog.technician == technician_name,
        MOTLog.status == 'completed',
        extract('month', MOTLog.end_time) == now.month,
        extract('year', MOTLog.end_time) == now.year
    ).count()

    # ✅ Build daily summary from completed logs
    daily_summary_raw = defaultdict(int)
    for log in logs:
        if log.status == 'completed' and log.end_time:
            log_date = log.end_time.date()
            daily_summary_raw[log_date] += 1

    daily_summary = {}
    for date in sorted(daily_summary_raw):
        formatted = date.strftime("%A %d/%m/%Y")
        daily_summary[formatted] = daily_summary_raw[date]

    # ✅ Assigned tasks for MOT
    assigned_tasks = AssignedTask.query.filter_by(department='mot').order_by(AssignedTask.created_at.desc()).all()

    # ✅ Completed tasks for this technician
    completed_tasks = [
        task for task in assigned_tasks
        if task.status == 'completed' and task.assigned_to == technician_name
    ]

    # ✅ Tasks completed this month
    completed_task_count = AssignedTask.query.filter(
        AssignedTask.department == 'mot',
        AssignedTask.assigned_to == technician_name,
        AssignedTask.status == 'completed',
        extract('month', AssignedTask.complete_time) == now.month,
        extract('year', AssignedTask.complete_time) == now.year
    ).count()

    # ✅ Tasks assigned today
    assigned_today_count = AssignedTask.query.filter(
        AssignedTask.department == 'mot',
        AssignedTask.assigned_to == technician_name,
        extract('year', AssignedTask.created_at) == now.year,
        extract('month', AssignedTask.created_at) == now.month,
        extract('day', AssignedTask.created_at) == now.day
    ).count()

    return render_template(
        'worklogs/mot.html',
        technician=technician_name,
        logs=logs,
        log_count=log_count,
        in_progress_logs=in_progress_logs,
        daily_summary=daily_summary,
        assigned_tasks=assigned_tasks,
        completed_tasks=completed_tasks,
        completed_task_count=completed_task_count,
        assigned_today_count=assigned_today_count,
        log_count_this_month=log_count_this_month  # 🆕 pass to template
    )
    
@app.route('/edit_employee/<int:id>', methods=['GET', 'POST'])
def edit_employee(id):
    if 'admin_logged_in' not in session:
        flash("You must be logged in as admin to edit employees.", "danger")
        return redirect(url_for('login'))
        
    employee = Employee.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        hourly_rate = request.form.get('hourly_rate')
        
        if name and hourly_rate:
            employee.name = name
            employee.hourly_rate = float(hourly_rate)
            db.session.commit()
            flash(f"Employee {name} updated successfully!", "success")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Name and hourly rate are required!", "danger")
    
    return render_template('edit_employee.html', employee=employee)    

@app.route('/mot/accept_task/<int:task_id>', methods=['POST'])
def accept_mot_task(task_id):
    if 'department_logged_in' not in session or session.get('department_name') != 'mot':
        flash("Unauthorized action", "danger")
        return redirect(url_for('department_login'))

    task = AssignedTask.query.get_or_404(task_id)

    # Block if already accepted by someone
    if task.status != 'pending':
        flash("This task is already in progress or completed.", "warning")
        return redirect(url_for('worklog_mot'))

    technician_id = session['department_logged_in']
    technician_user = DepartmentUser.query.get(technician_id)
    technician_name = technician_user.username

    task.assigned_to = technician_name
    task.status = 'in_progress'
    
    # Set the start time when the task begins
    task.start_time = datetime.now()  # Stamping the start time with the current time

    db.session.commit()

    flash("Task started!", "success")
    return redirect(url_for('worklog_mot'))

@app.route('/mot/complete_task/<int:task_id>', methods=['POST'])
def complete_mot_task(task_id):
    if 'department_logged_in' not in session or session.get('department_name') != 'mot':
        flash("Unauthorized action", "danger")
        return redirect(url_for('department_login'))

    task = AssignedTask.query.get_or_404(task_id)

    technician_id = session['department_logged_in']
    technician_user = DepartmentUser.query.get(technician_id)
    technician_name = technician_user.username

    # Only the assigned technician can complete the task
    if task.assigned_to != technician_name:
        flash("You are not assigned to this task.", "danger")
        return redirect(url_for('worklog_mot'))

    # Set the task's completion time when it's marked as completed
    task.status = 'completed'
    task.complete_time = datetime.now()

    # ✅ Log this completed task as a MOTLog entry
    mot_log = MOTLog(
        vehicle_reg=task.vehicle_reg or "-",
        task=task.title,
        technician=technician_name,
        start_time=task.start_time or datetime.now(),
        end_time=task.complete_time,
        notes=task.description,
        status='completed'
    )
    db.session.add(mot_log)

    db.session.commit()

    flash("Task marked as completed and logged.", "success")
    return redirect(url_for('worklog_mot'))

@app.route('/worklogs/prep')
def worklog_prep():
    if session.get('department_logged_in') is None or session.get('department_name') != 'prep':
        flash("You are not authorized to view this page.", "danger")
        return redirect(url_for('department_login'))

    assigned_tasks = AssignedTask.query.filter_by(department='prep').order_by(AssignedTask.created_at.desc()).all()
    return render_template('worklogs/prep.html', assigned_tasks=assigned_tasks)

@app.route('/worklogs/service')
def worklog_service():
    if session.get('department_logged_in') is None or session.get('department_name') != 'service':
        flash("You are not authorized to view this page.", "danger")
        return redirect(url_for('department_login'))

    assigned_tasks = AssignedTask.query.filter_by(department='service').order_by(AssignedTask.created_at.desc()).all()
    return render_template('worklogs/service.html', assigned_tasks=assigned_tasks)

@app.route('/worklogs/body-shop')
def worklog_body_shop():
    if session.get('department_logged_in') is None or session.get('department_name') != 'body-shop':
        flash("You are not authorized to view this page.", "danger")
        return redirect(url_for('department_login'))

    assigned_tasks = AssignedTask.query.filter_by(department='body-shop').order_by(AssignedTask.created_at.desc()).all()
    return render_template('worklogs/body_shop.html', assigned_tasks=assigned_tasks)

@app.route('/worklogs/reg-advert')
def worklog_reg_advert():
    if session.get('department_logged_in') is None or session.get('department_name') != 'reg-advert':
        flash("You are not authorized to view this page.", "danger")
        return redirect(url_for('department_login'))

    assigned_tasks = AssignedTask.query.filter_by(department='reg-advert').order_by(AssignedTask.created_at.desc()).all()
    return render_template('worklogs/reg_advert.html', assigned_tasks=assigned_tasks)

@app.route('/worklogs/sold')
def worklog_sold():
    if session.get('department_logged_in') is None or session.get('department_name') != 'sold':
        flash("You are not authorized to view this page.", "danger")
        return redirect(url_for('department_login'))

    assigned_tasks = AssignedTask.query.filter_by(department='sold').order_by(AssignedTask.created_at.desc()).all()
    return render_template('worklogs/sold.html', assigned_tasks=assigned_tasks)

@app.route('/register_time_tracker_user', methods=['POST'])
def register_time_tracker_user():
    if 'admin_logged_in' not in session:
        flash("You must be logged in as admin to register users.", "danger")
        return redirect(url_for('login'))

    username = request.form.get('username')
    password = request.form.get('password')

    existing_user = TimeTrackerUser.query.filter_by(username=username).first()
    if existing_user:
        flash("Username already exists! Choose another.", "danger")
        return redirect(url_for('admin_dashboard'))

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    new_user = TimeTrackerUser(username=username, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()

    flash(f"User {username} registered successfully for Employee Time Tracker!", "success")
    return redirect(url_for('admin_dashboard'))

from werkzeug.security import generate_password_hash, check_password_hash

@app.route('/register_department_user', methods=['POST'])
def register_department_user():
    if 'admin_logged_in' not in session:
        flash("Admin login required", "danger")
        return redirect(url_for('login'))

    department = request.form.get('department')
    username = request.form.get('username')
    password = request.form.get('password')

    if not (department and username and password):
        flash("All fields are required!", "danger")
        return redirect(url_for('admin_dashboard'))

    # Check if username already exists
    existing_user = DepartmentUser.query.filter_by(username=username).first()
    if existing_user:
        flash("Username already exists!", "danger")
        return redirect(url_for('admin_dashboard'))

    # Create user
    hashed_pw = generate_password_hash(password)
    new_user = DepartmentUser(department=department, username=username, password=hashed_pw)
    db.session.add(new_user)
    db.session.commit()

    flash(f"User '{username}' registered for {department.title()} department!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/department_login', methods=['GET', 'POST'])
def department_login():
    selected_department = request.args.get('department')  # Get department from URL

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = DepartmentUser.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            # Block login if user is not from the clicked department
            if selected_department and user.department != selected_department:
                flash("You are not authorized to log in under this department.", "danger")
                return redirect(url_for('department_login', department=selected_department))

            session.clear()
            session['department_logged_in'] = user.id
            session['department_name'] = user.department
            flash("Login successful!", "success")
            return redirect(url_for(f"worklog_{user.department.replace('-', '_')}"))

        flash("Incorrect username or password", "danger")

    return render_template('department_login.html', selected_department=selected_department)

@app.route('/department_logout')
def department_logout():
    session.pop('department_logged_in', None)
    session.pop('department_name', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('department_login'))

@app.route('/worklogs/mot/start', methods=['POST'])
def mot_start_work():
    if 'department_logged_in' not in session or session.get('department_name') != 'mot':
        flash("Unauthorized access", "danger")
        return redirect(url_for('department_login'))

    technician_id = session['department_logged_in']
    technician_user = DepartmentUser.query.get(technician_id)
    technician_name = technician_user.username

    vehicle_reg = request.form['vehicle_reg']
    task = request.form['task']

    new_log = MOTLog(
        vehicle_reg=vehicle_reg,
        task=task,
        technician=technician_name,
        start_time=datetime.now(),
        status='in_progress'
    )
    db.session.add(new_log)
    db.session.commit()

    flash("Work started successfully.", "success")
    return redirect(url_for('worklog_mot'))

@app.route('/worklogs/mot/complete', methods=['POST'])
def mot_complete_work():
    if 'department_logged_in' not in session or session.get('department_name') != 'mot':
        flash("Unauthorized access", "danger")
        return redirect(url_for('department_login'))

    technician_id = session['department_logged_in']
    technician_user = DepartmentUser.query.get(technician_id)
    technician_name = technician_user.username

    # Find latest in-progress log
    latest_log = MOTLog.query.filter_by(
        technician=technician_name,
        status='in_progress'
    ).order_by(MOTLog.start_time.desc()).first()

    if latest_log:
        latest_log.end_time = datetime.now()
        latest_log.status = 'completed'
        latest_log.notes = request.form.get('notes') or ""
        db.session.commit()
        flash("Work marked as completed.", "success")
    else:
        flash("No in-progress work found to complete.", "warning")

    return redirect(url_for('worklog_mot'))

@app.route('/worklogs/mot/complete/<int:log_id>', methods=['POST'])
def mot_complete_specific_log(log_id):
    if 'department_logged_in' not in session or session.get('department_name') != 'mot':
        flash("Unauthorized access", "danger")
        return redirect(url_for('department_login'))

    technician_id = session['department_logged_in']
    technician_user = DepartmentUser.query.get(technician_id)
    technician_name = technician_user.username

    log = MOTLog.query.get_or_404(log_id)

    # Extra safety check: make sure this is their own log and still in progress
    if log.technician != technician_name or log.status != 'in_progress':
        flash("Invalid or unauthorized log entry.", "danger")
        return redirect(url_for('worklog_mot'))

    log.end_time = datetime.now()
    log.status = 'completed'
    log.notes = request.form.get('notes') or log.notes
    db.session.commit()

    flash(f"Task for {log.vehicle_reg} marked as completed.", "success")
    return redirect(url_for('worklog_mot'))

@app.route('/assign_work', methods=['GET', 'POST'])
def assign_work():
    if 'admin_logged_in' not in session:
        flash("Admin login required", "danger")
        return redirect(url_for('login'))

    departments = ["mot", "prep", "service", "body-shop", "reg-advert", "sold"]
    technicians = DepartmentUser.query.all()

    department_job_titles = {
        "mot": ["MOT", "Garage Repair", "Workshop Runs", "Delivery", "Collection"],
        "prep": ["Prep Wash", "Interior Clean", "Machine Polish"],
        "service": ["Oil Change", "Tyre Replacement"],
        "body-shop": ["Dent Fix", "Paint Respray"],
        "reg-advert": [],
        "sold": [],
    }

    if request.method == 'POST':
        department = request.form.get('department')
        title = request.form.get('title')
        description = request.form.get('description')
        assigned_to = request.form.get('assigned_to') or None

        # Get delivery/collection fields if applicable
        contact_name = None
        contact_number = None
        contact_address = None
        contact_notes = None
        vehicle_reg = None

        if title in ["Delivery", "Collection"]:
            contact_name = request.form.get('contact_name')
            contact_number = request.form.get('contact_number')
            contact_address = request.form.get('contact_address')
            contact_notes = request.form.get('contact_notes')
            vehicle_reg = request.form.get('vehicle_reg')

        if not description:
            flash("Description is required.", "danger")
            return render_template(
                'assign_work.html',
                departments=departments,
                technicians=technicians,
                department_job_titles=department_job_titles
            )

        if title == 'custom':
            custom_title = request.form.get('custom_title')
            if not custom_title:
                flash("Please enter a custom job title.", "danger")
                return render_template(
                    'assign_work.html',
                    departments=departments,
                    technicians=technicians,
                    department_job_titles=department_job_titles
                )
            title = custom_title.strip()

        task = AssignedTask(
            department=department,
            title=title,
            description=description,
            assigned_to=assigned_to,
            contact_name=contact_name,
            contact_number=contact_number,
            contact_address=contact_address,
            contact_notes=contact_notes,
            vehicle_reg=vehicle_reg  # ✅ included here
        )
        db.session.add(task)
        db.session.flush()

        files = request.files.getlist('images')
        for image in files:
            if image and allowed_file(image.filename):
                filename = secure_filename(image.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image.save(filepath)
                db.session.add(AssignedTaskImage(task_id=task.id, filename=filename))

        db.session.commit()
        flash(f"Task assigned to {department.title()} department!", "success")

    return render_template(
        'assign_work.html',
        departments=departments,
        technicians=technicians,
        department_job_titles=department_job_titles
    )

@app.route('/manage_assigned_tasks')
def manage_assigned_tasks():
    if 'admin_logged_in' not in session:
        flash("Admin login required", "danger")
        return redirect(url_for('login'))

    tasks = AssignedTask.query.filter(AssignedTask.status != 'completed').order_by(AssignedTask.created_at.desc()).all()
    return render_template('manage_assigned_tasks.html', tasks=tasks)

@app.route('/edit_assigned_task/<int:task_id>', methods=['GET', 'POST'])
def edit_assigned_task(task_id):
    if 'admin_logged_in' not in session:
        flash("Admin access required.", "danger")
        return redirect(url_for('login'))

    task = AssignedTask.query.get_or_404(task_id)
    departments = ["mot", "prep", "service", "body-shop", "reg-advert", "sold"]
    technicians = DepartmentUser.query.all()

    if request.method == 'POST':
        task.department = request.form.get('department')
        task.title = request.form.get('title')
        task.description = request.form.get('description')
        task.assigned_to = request.form.get('assigned_to') or None
        
        # Handle delivery/collection fields
        if task.title in ["Delivery", "Collection"]:
            task.contact_name = request.form.get('contact_name')
            task.contact_number = request.form.get('contact_number')
            task.contact_address = request.form.get('contact_address')
            task.contact_notes = request.form.get('contact_notes')
        else:
            # Clear these fields if not delivery/collection
            task.contact_name = None
            task.contact_number = None
            task.contact_address = None
            task.contact_notes = None

        db.session.commit()
        flash("Task updated successfully.", "success")
        return redirect(url_for('manage_assigned_tasks'))

    return render_template(
        'edit_assigned_task.html',
        task=task,
        departments=departments,
        technicians=technicians
    )
    
@app.route('/delete_assigned_task/<int:task_id>', methods=['POST'])
def delete_assigned_task(task_id):
    if 'admin_logged_in' not in session:
        flash("Admin access required.", "danger")
        return redirect(url_for('login'))

    task = AssignedTask.query.get_or_404(task_id)

    # Delete associated images first
    for image in task.images:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], image.filename)
        if os.path.exists(image_path):
            os.remove(image_path)
        db.session.delete(image)

    db.session.delete(task)
    db.session.commit()
    flash("Assigned task deleted successfully.", "success")
    return redirect(url_for('manage_assigned_tasks'))

@app.route('/assign_work/completed/select', methods=['GET', 'POST'])
def select_completed_department():
    departments = ["mot", "prep", "service", "body-shop", "reg-advert", "sold"]

    if request.method == 'POST':
        selected = request.form.get('department')
        return redirect(url_for('view_completed_tasks_by_department', department=selected))

    return render_template('select_completed_department.html', departments=departments)

@app.route('/assign_work/completed/view', methods=['GET', 'POST'])
def view_completed_tasks_by_department():
    department = request.args.get('department')
    technician = request.args.get('technician')
    view_manual = request.args.get('view_manual') == 'true'

    if not department:
        flash("No department selected.", "warning")
        return redirect(url_for('select_completed_department'))

    department_technicians = DepartmentUser.query.filter_by(department=department).all()

    query = AssignedTask.query.filter_by(department=department, status='completed')
    if technician:
        query = query.filter_by(assigned_to=technician)
    completed_tasks = query.order_by(AssignedTask.created_at.desc()).all()

    manual_logs = []
    if department == 'mot' and view_manual:
        manual_query = MOTLog.query
        if technician:
            manual_query = manual_query.filter_by(technician=technician)
        manual_logs = manual_query.order_by(MOTLog.start_time.desc()).all()

    return render_template(
        'completed_tasks_by_department.html',
        department=department,
        completed_tasks=completed_tasks,
        department_technicians=department_technicians,
        technician=technician,
        manual_logs=manual_logs,
        view_manual=view_manual
    )

@app.route('/assign_work/completed/reset', methods=['POST'])
def reset_completed_tasks():
    department = request.form.get('department')

    if not department:
        flash("No department specified.", "danger")
        return redirect(url_for('select_completed_department'))

    # Delete completed tasks for this department
    deleted = AssignedTask.query.filter_by(department=department, status='completed').delete()
    db.session.commit()

    flash(f"{deleted} completed task{'s' if deleted != 1 else ''} cleared for {department.replace('-', ' ').title()}.", "info")
    return redirect(url_for('view_completed_tasks_by_department', department=department))

@app.route('/reset_vehicle_key_user_password', methods=['POST'])
def reset_vehicle_key_user_password():
    if 'admin_logged_in' not in session:
        return redirect(url_for('login'))

    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password')

    user = VehicleKeyUser.query.get(user_id)
    if user:
        hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256')
        user.password = hashed_password
        db.session.commit()
        flash(f"Password reset successfully for {user.username}", "success")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/remove_department_user/<int:id>')
def remove_department_user(id):
    if 'admin_logged_in' not in session:
        flash("Admin login required", "danger")
        return redirect(url_for('login'))

    user = DepartmentUser.query.get(id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash(f"Department user '{user.username}' has been removed.", "success")

    return redirect(url_for('admin_dashboard'))

@app.route('/reset_department_user_password', methods=['POST'])
def reset_department_user_password():
    if 'admin_logged_in' not in session:
        flash("Admin login required", "danger")
        return redirect(url_for('login'))

    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password')

    user = DepartmentUser.query.get(user_id)
    if user and new_password:
        user.password = generate_password_hash(new_password)
        db.session.commit()
        flash(f"Password reset for {user.username}.", "success")

    return redirect(url_for('admin_dashboard'))

@app.route('/reset_mot_logs/<int:user_id>', methods=['POST'])
def reset_mot_logs(user_id):
    if 'admin_logged_in' not in session:
        flash("Admin access required.", "danger")
        return redirect(url_for('login'))

    user = DepartmentUser.query.get(user_id)
    if not user or user.department != 'mot':
        flash("User not found or not in MOT department.", "danger")
        return redirect(url_for('admin_dashboard'))

    now = datetime.now()
    # Calculate last month
    if now.month == 1:
        last_month = 12
        year = now.year - 1
    else:
        last_month = now.month - 1
        year = now.year

    # Delete only that user's logs from last month
    logs_to_delete = MOTLog.query.filter(
        MOTLog.technician == user.username,
        extract('month', MOTLog.start_time) == last_month,
        extract('year', MOTLog.start_time) == year
    ).all()

    for log in logs_to_delete:
        db.session.delete(log)
    db.session.commit()

    flash(f"Deleted {len(logs_to_delete)} MOT logs from last month for {user.username}.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_mot_log/<int:log_id>', methods=['POST'])
def delete_mot_log(log_id):
    if 'department_logged_in' not in session or session.get('department_name') != 'mot':
        flash("Unauthorized access", "danger")
        return redirect(url_for('department_login'))

    log = MOTLog.query.get_or_404(log_id)

    # Optional: Confirm user owns the log
    technician_id = session['department_logged_in']
    technician_user = DepartmentUser.query.get(technician_id)
    if log.technician != technician_user.username:
        flash("You can only delete your own logs.", "danger")
        return redirect(url_for('worklog_mot'))

    db.session.delete(log)
    db.session.commit()
    flash("Log deleted successfully.", "success")
    return redirect(url_for('worklog_mot'))

@app.route('/remove_vehicle_key_user/<int:id>', methods=['GET'])
def remove_vehicle_key_user(id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('login'))

    user = VehicleKeyUser.query.get(id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash(f"User {user.username} has been removed.", "success")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/remove_time_tracker_user/<int:id>', methods=['GET'])
def remove_time_tracker_user(id):
    if 'admin_logged_in' not in session:
        flash("You must be logged in as admin to remove users.", "danger")
        return redirect(url_for('login'))

    user = TimeTrackerUser.query.get(id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash(f"User {user.username} has been removed.", "success")
    else:
        flash("User not found.", "danger")

    return redirect(url_for('admin_dashboard'))

# After employee removal, redirect back to Employee Time Tracker page
@app.route('/remove_employee/<int:id>', methods=['GET'])
def remove_employee(id):
    employee = Employee.query.get(id)
    
    if employee:
        # ✅ Delete all work sessions related to this employee first
        WorkSession.query.filter_by(employee_id=employee.id).delete()

        # ✅ Delete all vehicle key records related to this employee
        VehicleKey.query.filter_by(employee_id=employee.id).delete()

        # ✅ Now delete the employee
        db.session.delete(employee)
        db.session.commit()

    return redirect(url_for('admin_dashboard'))

# Route for Employee Time Tracker page
@app.route('/employee_time_tracker')
def employee_time_tracker():
    if 'time_tracker_logged_in' not in session:
        flash("You must be logged in to access this page.", "danger")
        return redirect(url_for('time_tracker_login'))

    employees = Employee.query.all()

    for emp in employees:
        total_minutes = sum(session.total_hours() for session in emp.sessions)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        emp.total_worked_hours = f"{hours}:{minutes:02d}"

    return render_template('index.html', employees=employees)

# AJAX Clock In
@app.route('/clock_in/<int:id>', methods=['POST'])
def clock_in(id):
    employee = Employee.query.get(id)
    if employee:
        new_session = WorkSession(employee_id=employee.id, clock_in=datetime.now())
        db.session.add(new_session)
        db.session.commit()

        return {
            'success': True,
            'action': 'clock_in',
            'clock_in': new_session.clock_in.strftime('%A, %d-%m-%Y %H:%M:%S'),
            'clock_out': None,
            'total_hours': "0:00"  # no clock out yet
        }
    return {'success': False}, 400

# AJAX Clock Out
@app.route('/clock_out/<int:id>', methods=['POST'])
def clock_out(id):
    employee = Employee.query.get(id)
    if employee:
        session = WorkSession.query.filter_by(employee_id=employee.id, clock_out=None).first()
        if session:
            session.clock_out = datetime.now()
            db.session.commit()

            # recalculate total minutes
            total_minutes = sum(s.total_hours() for s in employee.sessions)
            total_hours = total_minutes // 60
            total_remaining = total_minutes % 60

            return {
                'success': True,
                'action': 'clock_out',
                'clock_in': session.clock_in.strftime('%A, %d-%m-%Y %H:%M:%S'),
                'clock_out': session.clock_out.strftime('%A, %d-%m-%Y %H:%M:%S'),
                'total_hours': f"{total_hours}:{total_remaining:02d}"
            }
    return {'success': False}, 400

@app.route('/manual_clock_in', methods=['POST'])
def manual_clock_in():
    employee_id = request.form.get('employee_id')
    clock_in_time = request.form.get('clock_in_time')

    if employee_id and clock_in_time:
        employee = Employee.query.get(employee_id)
        if employee:
            new_session = WorkSession(
                employee_id=employee.id,
                clock_in=datetime.strptime(clock_in_time, '%Y-%m-%dT%H:%M')  # format matches <input type="datetime-local">
            )
            db.session.add(new_session)
            db.session.commit()
            flash(f"Manual clock-in recorded for {employee.name}.", "success")

    return redirect(url_for('admin_dashboard'))

@app.route('/manual_clock_out', methods=['POST'])
def manual_clock_out():
    employee_id = request.form.get('employee_id')
    clock_out_time = request.form.get('clock_out_time')

    if employee_id and clock_out_time:
        employee = Employee.query.get(employee_id)
        
        if employee:
            # Find the most recent clock-in session that has not been clocked out
            session = WorkSession.query.filter_by(employee_id=employee.id, clock_out=None).order_by(WorkSession.clock_in.desc()).first()
            
            if session:
                session.clock_out = datetime.strptime(clock_out_time, '%Y-%m-%dT%H:%M')  # Convert to datetime format
                db.session.commit()
                flash(f"Clock-out time manually set for {employee.name}", "success")

    return redirect(url_for('admin_dashboard'))

@app.route('/update_session/<int:session_id>', methods=['POST'])
def update_session(session_id):
    if 'admin_logged_in' not in session:
        flash("Admin access required.", "danger")
        return redirect(url_for('login'))

    session_record = WorkSession.query.get_or_404(session_id)

    try:
        clock_in_str = request.form.get('clock_in')
        clock_out_str = request.form.get('clock_out')

        session_record.clock_in = datetime.strptime(clock_in_str, '%Y-%m-%dT%H:%M')

        if clock_out_str:
            session_record.clock_out = datetime.strptime(clock_out_str, '%Y-%m-%dT%H:%M')
        else:
            session_record.clock_out = None

        db.session.commit()
        flash("Session updated successfully.", "success")
    except Exception as e:
        flash(f"Error updating session: {str(e)}", "danger")

    return redirect(url_for('admin_dashboard'))

# Route for returning vehicle key (update the key return time)
@app.route('/return_vehicle_key/<int:id>')
def return_vehicle_key(id):
    vehicle_key = VehicleKey.query.get(id)
    if vehicle_key:
        vehicle_key.key_return_time = datetime.now()
        db.session.commit()
    return redirect(url_for('vehicle_key_monitor'))

@app.route('/vehicle_key_monitor')
def vehicle_key_monitor():
    if 'vehicle_key_logged_in' not in session:  # 🔒 Check if user is logged in
        flash("You must be logged in to access this page.", "danger")
        return redirect(url_for('vehicle_key_login'))

    employees = Employee.query.all()
    vehicle_keys = VehicleKey.query.filter_by(key_return_time=None).all()

    return render_template('vehicle_key_monitor.html', employees=employees, vehicle_keys=vehicle_keys)

from werkzeug.security import generate_password_hash, check_password_hash

# Route to register new vehicle key users
@app.route('/register_vehicle_key_user', methods=['POST'])
def register_vehicle_key_user():
    if 'admin_logged_in' not in session:
        flash("You must be logged in as admin to register users.", "danger")
        return redirect(url_for('login'))

    username = request.form.get('username')
    password = request.form.get('password')

    if not username or not password:
        flash("Username and password are required.", "danger")
        return redirect(url_for('admin_dashboard'))

    existing_user = VehicleKeyUser.query.filter_by(username=username).first()
    if existing_user:
        flash("Username already exists! Choose another.", "danger")
        return redirect(url_for('admin_dashboard'))

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    new_user = VehicleKeyUser(username=username, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()

    flash(f"User {username} registered successfully for Vehicle Key Monitor!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/vehicle_key_login', methods=['GET', 'POST'])
def vehicle_key_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = VehicleKeyUser.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session.clear()  # 🚀 Ensure previous sessions are removed
            session['vehicle_key_logged_in'] = user.id  # Store specific user ID
            flash("Login successful!", "success")
            return redirect(url_for('vehicle_key_monitor'))
        else:
            flash("Incorrect username or password!", "danger")

    return render_template('vehicle_key_login.html')

@app.route('/time_tracker_login', methods=['GET', 'POST'])
def time_tracker_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = TimeTrackerUser.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session.clear()  # 🚀 Ensure previous sessions are removed
            session['time_tracker_logged_in'] = user.id  # Store specific user ID
            flash("Login successful!", "success")
            return redirect(url_for('employee_time_tracker'))
        else:
            flash("Incorrect username or password!", "danger")

    return render_template('time_tracker_login.html')

@app.route('/employee_table')
def employee_table():
    if 'time_tracker_logged_in' not in session:
        return '', 403
    employees = Employee.query.all()

    for emp in employees:
        total_minutes = sum(session.total_hours() for session in emp.sessions)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        emp.total_worked_hours = f"{hours}:{minutes:02d}"

    return render_template('partials/employee_table.html', employees=employees)

@app.route('/time_tracker_logout')
def time_tracker_logout():
    session.pop('time_tracker_logged_in', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('time_tracker_login'))

@app.route('/vehicle_key_logout')
def vehicle_key_logout():
    session.pop('vehicle_key_logged_in', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('vehicle_key_login'))

@app.route('/previous_key_logs')
def previous_key_logs():
    vehicle_keys = VehicleKey.query.filter(VehicleKey.key_return_time.isnot(None)).all()  # ✅ Show only returned keys

    return render_template('previous_key_logs.html', vehicle_keys=vehicle_keys)

@app.route('/test')
def test():
    return "Flask is working!"

@app.route('/delete_employee_logs/<int:employee_id>', methods=['GET'])
def delete_employee_logs(employee_id):
    employee = Employee.query.get(employee_id)
    
    if employee:
        # Delete all work sessions related to this employee
        WorkSession.query.filter_by(employee_id=employee.id).delete()

        # Commit the changes to the database
        db.session.commit()
        flash(f"Employee logs for {employee.name} have been successfully deleted.", "success")
    else:
        flash("Employee not found.", "danger")

    # Redirect back to the admin dashboard
    return redirect(url_for('admin_dashboard'))

@app.route('/download_employee_pdf/<int:employee_id>')
def download_employee_pdf(employee_id):
    employee = Employee.query.get(employee_id)
    if not employee:
        flash("Employee not found!", "danger")
        return redirect(url_for('admin_dashboard'))

    # Calculate total worked hours from work sessions
    total_minutes = sum(session.total_hours() for session in employee.sessions)
    total_hours = total_minutes // 60
    total_remaining_minutes = total_minutes % 60
    total_worked_hours = f"{total_hours}:{total_remaining_minutes:02d}"

    # Pay calculations
    hourly_rate = employee.hourly_rate
    total_pay = round((total_minutes / 60) * hourly_rate, 2)
    overtime_pay = round(employee.monthly_overtime * hourly_rate, 2)

    # Create PDF
    pdf = FPDF()
    pdf.add_page()

    # Header
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(200, 10, txt=f"Employee Report: {employee.name} (£{hourly_rate:.2f}/hr)", ln=True, align='C')
    pdf.ln(10)

    # Summary Section
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(200, 10, txt=f"Total Hours Worked: {total_worked_hours}", ln=True, align='L')
    pdf.cell(200, 10, txt=f"Overtime Hours: {employee.monthly_overtime} hrs", ln=True, align='L')
    pdf.cell(200, 10, txt=f"Total Pay: £{total_pay:.2f}", ln=True, align='L')
    pdf.cell(200, 10, txt=f"Overtime Pay: £{overtime_pay:.2f}", ln=True, align='L')
    pdf.ln(10)

    # Table Header
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(55, 10, txt="Clock In Time", border=1, align='C')
    pdf.cell(55, 10, txt="Clock Out Time", border=1, align='C')
    pdf.cell(40, 10, txt="Hours Worked", border=1, align='C')
    pdf.cell(40, 10, txt="Wage for Day", border=1, align='C')
    pdf.ln()

    # Work Sessions
    pdf.set_font('Arial', '', 10)
    if employee.sessions:
        for session in employee.sessions:
            clock_in = session.clock_in.strftime('%A, %d/%m/%Y %H:%M:%S')
            clock_out = session.clock_out.strftime('%A, %d/%m/%Y %H:%M:%S') if session.clock_out else "Still Working"
            total_mins = session.total_hours()
            hrs = total_mins // 60
            mins = total_mins % 60
            session_pay = round((total_mins / 60) * hourly_rate, 2)

            pdf.cell(55, 10, txt=clock_in, border=1, align='C')
            pdf.cell(55, 10, txt=clock_out, border=1, align='C')
            pdf.cell(40, 10, txt=f"{hrs}:{mins:02d}", border=1, align='C')
            pdf.cell(40, 10, txt=f"£{session_pay:.2f}", border=1, align='C')
            pdf.ln()
    else:
        pdf.cell(190, 10, txt="No work sessions available", border=1, align='C')
        pdf.ln()

    pdf_path = f"employee_report_{employee.id}.pdf"
    pdf.output(pdf_path)

    return send_file(pdf_path, as_attachment=True)

import pandas as pd

@app.route('/export_vehicle_keys')
def export_vehicle_keys():
    vehicle_keys = VehicleKey.query.all()

    # Convert Data to Pandas DataFrame
    data = []
    for vk in vehicle_keys:
        data.append({
            "Employee Name": vk.employee.name,
            "Key Number": vk.key_number,
            "Key Checkout Time": vk.key_checkout_time.strftime("%Y-%m-%d %H:%M:%S"),
            "Key Return Time": vk.key_return_time.strftime("%Y-%m-%d %H:%M:%S") if vk.key_return_time else "Not Returned"
        })
    
    df = pd.DataFrame(data)
    file_path = "vehicle_keys_report.xlsx"
    df.to_excel(file_path, index=False)

    return send_file(file_path, as_attachment=True)

# Function to reset Employee Time Tracker logs at 00:00 every night
from fpdf import FPDF
from datetime import datetime, timedelta

def generate_employee_pdf(employee):
    """Generate PDF for each employee and save it"""
    now = datetime.now()
    first_day_of_this_month = datetime(now.year, now.month, 1)
    first_day_of_last_month = first_day_of_this_month - timedelta(days=1)
    first_day_of_last_month = datetime(first_day_of_last_month.year, first_day_of_last_month.month, 1)

    # Get all work sessions for the previous month
    sessions = WorkSession.query.filter(
        WorkSession.employee_id == employee.id,
        WorkSession.clock_in >= first_day_of_last_month,
        WorkSession.clock_out < first_day_of_this_month
    ).all()

    # Calculate total worked hours in minutes
    total_minutes = sum(session.total_hours() for session in sessions)
    total_hours = total_minutes // 60
    total_remaining_minutes = total_minutes % 60
    total_worked_hours = f"{total_hours}:{total_remaining_minutes:02d}"

    # Workdays and expected work hours
    workdays = sum(1 for i in range((first_day_of_this_month - first_day_of_last_month).days)
                   if (first_day_of_last_month + timedelta(days=i)).weekday() < 6)
    expected_minutes = workdays * 8 * 60

    # Overtime
    overtime_minutes = max(total_minutes - expected_minutes, 0)
    overtime_hours = overtime_minutes // 60
    overtime_remaining_minutes = overtime_minutes % 60

    # Pay
    hourly_rate = employee.hourly_rate
    total_pay = round((total_minutes / 60) * hourly_rate, 2)
    overtime_pay = round((overtime_minutes / 60) * hourly_rate, 2)

    # Create PDF
    pdf = FPDF()
    pdf.add_page()

    # Header
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(200, 10, txt=f"Employee Report: {employee.name} (£{hourly_rate:.2f}/hr)", ln=True, align='C')
    pdf.ln(10)

    # Summary
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(200, 10, txt=f"Total Hours Worked: {total_worked_hours}", ln=True, align='L')
    pdf.cell(200, 10, txt=f"Overtime: {overtime_hours} hrs {overtime_remaining_minutes} mins", ln=True, align='L')
    pdf.cell(200, 10, txt=f"Total Pay: £{total_pay:.2f}", ln=True, align='L')
    pdf.cell(200, 10, txt=f"Overtime Pay: £{overtime_pay:.2f}", ln=True, align='L')
    pdf.ln(10)

    # Table Header
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(55, 10, txt="Clock In Time", border=1, align='C')
    pdf.cell(55, 10, txt="Clock Out Time", border=1, align='C')
    pdf.cell(40, 10, txt="Hours Worked", border=1, align='C')
    pdf.cell(40, 10, txt="Wage for Day", border=1, align='C')
    pdf.ln()

    # Work Sessions
    pdf.set_font('Arial', '', 10)
    if sessions:
        for session in sessions:
            clock_in = session.clock_in.strftime('%d/%m/%Y %H:%M:%S')
            clock_out = session.clock_out.strftime('%d/%m/%Y %H:%M:%S') if session.clock_out else "Still Working"
            total_mins = session.total_hours()
            hours_worked = total_mins // 60
            minutes_worked = total_mins % 60
            session_pay = round((total_mins / 60) * hourly_rate, 2)

            pdf.cell(55, 10, txt=clock_in, border=1, align='C')
            pdf.cell(55, 10, txt=clock_out, border=1, align='C')
            pdf.cell(40, 10, txt=f"{hours_worked}:{minutes_worked:02d}", border=1, align='C')
            pdf.cell(40, 10, txt=f"£{session_pay:.2f}", border=1, align='C')
            pdf.ln()
    else:
        pdf.cell(190, 10, txt="No work sessions available", border=1, align='C')
        pdf.ln()

    # Save the PDF
    pdf_output_path = f"employee_report_{employee.id}_month_{now.strftime('%Y_%m')}.pdf"
    pdf.output(pdf_output_path)
    print(f"Generated PDF for {employee.name}: {pdf_output_path}")

def reset_employee_time_tracker():
    with app.app_context():
        # Get current and previous month
        now = datetime.now()
        first_day_of_this_month = datetime(now.year, now.month, 1)
        first_day_of_last_month = first_day_of_this_month - timedelta(days=1)
        first_day_of_last_month = datetime(first_day_of_last_month.year, first_day_of_last_month.month, 1)

        # Generate PDF and calculate overtime for each employee
        employees = Employee.query.all()
        for emp in employees:
            # Generate and save the PDF for the employee
            generate_employee_pdf(emp)

            # Calculate and save overtime for the employee
            total_minutes = sum(session.total_hours() for session in emp.sessions)
            total_hours_worked = total_minutes // 60
            workdays = sum(1 for i in range((first_day_of_this_month - first_day_of_last_month).days)
                           if (first_day_of_last_month + timedelta(days=i)).weekday() < 6)
            expected_hours = workdays * 8
            overtime_hours = max(total_hours_worked - expected_hours, 0)  # Overtime can't be negative
            emp.monthly_overtime = overtime_hours

        # Commit the overtime changes
        db.session.commit()

        # Delete all work session logs after saving overtime
        db.session.query(WorkSession).delete()
        db.session.commit()

        print("✅ Employee Time Tracker reset at midnight with overtime saved and PDFs generated!")

# Set up the scheduler to run at 00:00 on the 1st of each month
scheduler = BackgroundScheduler()
scheduler.add_job(func=reset_employee_time_tracker, trigger=CronTrigger(day=1, hour=0, minute=0))  # Runs on the 1st of every month at midnight
scheduler.start()

# Ensure the scheduler shuts down when the app exits
atexit.register(lambda: scheduler.shutdown())

from sqlalchemy import extract
from io import BytesIO
from flask import send_file
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from collections import defaultdict
from datetime import datetime

@app.route('/download_mot_logs')
def download_mot_logs():
    if 'department_logged_in' not in session or session.get('department_name') != 'mot':
        flash("Unauthorized access", "danger")
        return redirect(url_for('department_login'))

    technician_id = session['department_logged_in']
    technician_user = DepartmentUser.query.get(technician_id)
    technician_name = technician_user.username

    now = datetime.now()
    current_month = now.strftime("%B")
    current_year = now.year

    logs = MOTLog.query.filter(
        MOTLog.technician == technician_name,
        extract('month', MOTLog.start_time) == now.month,
        extract('year', MOTLog.start_time) == now.year
    ).order_by(MOTLog.start_time.asc()).all()

    # Group logs by day
    daily_logs = defaultdict(list)
    for log in logs:
        day = log.start_time.strftime("%A %d %B %Y")  # e.g. "Monday 01 April 2025"
        daily_logs[day].append(log)

    # PDF setup
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    line_height = 16
    left_margin = 50
    y = height - 60

    def draw_header():
        nonlocal y
        p.setFont("Helvetica-Bold", 14)
        p.drawString(left_margin, y, f"MOT Worklogs - {technician_name} - {current_month} {current_year}")
        y -= 25
        p.setFont("Helvetica-Bold", 10)
        p.drawString(left_margin, y, "Date")
        p.drawString(left_margin + 60, y, "Vehicle")
        p.drawString(left_margin + 140, y, "Task")
        p.drawString(left_margin + 270, y, "Start")
        p.drawString(left_margin + 320, y, "End")
        p.drawString(left_margin + 370, y, "Notes")
        y -= 15
        p.setFont("Helvetica", 10)

    draw_header()

    for day in sorted(daily_logs.keys()):
        logs_for_day = daily_logs[day]
        completed_count = 0

        for log in logs_for_day:
            if y < 60:
                p.showPage()
                y = height - 60
                draw_header()

            p.drawString(left_margin, y, log.start_time.strftime("%A %d %B %Y"))  # Full UK-style
            p.drawString(left_margin + 60, y, log.vehicle_reg)
            p.drawString(left_margin + 140, y, log.task[:20])
            p.drawString(left_margin + 270, y, log.start_time.strftime("%H:%M"))
            p.drawString(left_margin + 320, y, log.end_time.strftime("%H:%M") if log.end_time else "-")

            # Wrap long notes
            notes = (log.notes or "-").strip()
            note_lines = []
            while notes:
                if len(notes) <= 40:
                    note_lines.append(notes)
                    break
                else:
                    space = notes[:40].rfind(' ')
                    if space == -1:
                        space = 40
                    note_lines.append(notes[:space])
                    notes = notes[space:].lstrip()

            p.drawString(left_margin + 370, y, note_lines[0])
            y -= line_height

            for line in note_lines[1:]:
                if y < 60:
                    p.showPage()
                    y = height - 60
                    draw_header()
                p.drawString(left_margin + 370, y, line)
                y -= line_height

            if log.status == 'completed' and log.end_time:
                completed_count += 1

        # After each day, print summary with full date again
        if y < 60:
            p.showPage()
            y = height - 60
            draw_header()

        p.setFont("Helvetica-Bold", 10)
        p.drawString(left_margin, y, f"✔ {completed_count} log(s) completed on {day}")
        y -= line_height
        p.setFont("Helvetica", 10)

    p.save()
    buffer.seek(0)

    filename = f"MOT_{technician_name}_{current_month}_{current_year}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run()