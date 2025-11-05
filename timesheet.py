import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, time, date
import time as time_sleep
import os
import hashlib
import pytz

# --- AI Integration Imports ---
from transformers import pipeline

# --- App Configuration ---
st.set_page_config(page_title="AI-Powered Timesheet Tool", layout="wide")

# --- Timezone Configuration ---
IST = pytz.timezone('Asia/Kolkata')

# --- Database Setup ---
DB_FILE = "company_data.db"
LAST_UPDATE_FILE = "last_update.txt"
ADMIN_PASSWORD = "admin"

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timesheet (
            id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL,
            project_name TEXT NOT NULL, task_description TEXT NOT NULL,
            hours_worked REAL NOT NULL, submission_date DATE NOT NULL,
            submission_time TIME NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
        )
    """)
    conn.commit()
    conn.close()

# --- AI Model Loading ---
@st.cache_resource
def get_classification_pipeline():
    """Loads and caches the AI model pipeline."""
    return pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

def suggest_project_name(task_description, project_list):
    """Uses AI to suggest a project name based on the task description."""
    if not task_description or not project_list:
        return None
    classifier = get_classification_pipeline()
    result = classifier(task_description, candidate_labels=project_list)
    return result['labels'][0]

# --- Employee Management (Admin) ---
def add_employee(employee_id, name, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO employees (employee_id, name, password) VALUES (?, ?, ?)",
                       (employee_id, name, hash_password(password)))
        conn.commit()
        st.success(f"Employee {name} ({employee_id}) added successfully.")
    except sqlite3.IntegrityError:
        st.error(f"Employee ID {employee_id} already exists.")
    finally:
        conn.close()

def get_all_employees():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT employee_id, name FROM employees", conn)
    conn.close()
    return df

# --- Timesheet and Attendance Logic ---
def get_unique_project_names():
    """Gets a list of unique project names for AI suggestions."""
    conn = get_db_connection()
    try:
        df = pd.read_sql_query("SELECT DISTINCT project_name FROM timesheet", conn)
        return df['project_name'].tolist()
    finally:
        conn.close()

def add_timesheet_entry(employee_id, project_name, task_description, hours_worked, entry_date):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now(IST)
    cursor.execute("""
        INSERT INTO timesheet (employee_id, project_name, task_description, hours_worked, submission_date, submission_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (employee_id, project_name, task_description, hours_worked, entry_date, now.strftime("%H:%M:%S")))
    conn.commit()
    conn.close()
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(now.timestamp()))

def get_timesheet_entries_today():
    conn = get_db_connection()
    today = datetime.now(IST).date()
    query = "SELECT t.employee_id, e.name, t.project_name, t.task_description, t.hours_worked, t.submission_date, t.submission_time FROM timesheet t JOIN employees e ON t.employee_id = e.employee_id WHERE t.submission_date = ? ORDER BY t.submission_time DESC"
    df = pd.read_sql_query(query, conn, params=(str(today),))
    conn.close()
    return df

def get_attendance_status():
    employees_df = get_all_employees()
    if employees_df.empty:
        return pd.DataFrame(columns=["Employee ID", "Name", "Status"])
    timesheet_today_df = get_timesheet_entries_today()
    status_list = []
    for _, employee in employees_df.iterrows():
        emp_id = employee["employee_id"]
        emp_name = employee["name"]
        emp_entries = timesheet_today_df[timesheet_today_df['employee_id'] == emp_id]
        status = "Absent"
        if not emp_entries.empty:
            first_entry_time = datetime.strptime(emp_entries['submission_time'].min(), '%H:%M:%S').time()
            if time(8, 30) <= first_entry_time <= time(10, 0): status = "Present"
            elif first_entry_time >= time(13, 0): status = "Half-day"
            else: status = "Present (Late)"
        status_list.append({"Employee ID": emp_id, "Name": emp_name, "Status": status})
    return pd.DataFrame(status_list)

# --- Real-time Update Mechanism ---
def get_last_update_time():
    if os.path.exists(LAST_UPDATE_FILE):
        with open(LAST_UPDATE_FILE, "r") as f:
            try: return float(f.read().strip())
            except (ValueError, TypeError): return 0.0
    return 0.0

# --- Authentication ---
def check_employee_credentials(employee_id, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM employees WHERE employee_id = ?", (employee_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result['password'] == hash_password(password)

# --- Streamlit UI Views ---
def login_page():
    st.header("Employee Login")
    with st.form("login_form"):
        employee_id = st.text_input("Employee ID")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            if check_employee_credentials(employee_id, password):
                st.session_state["logged_in"] = True
                st.session_state["employee_id"] = employee_id
                st.rerun()
            else:
                st.error("Invalid credentials. Please contact your manager if you are not added.")

def employee_view():
    st.header(f"Timesheet Entry for {st.session_state['employee_id']}")
    now_time = datetime.now(IST).time()
    
    is_submission_allowed = (time(8, 30) <= now_time <= time(10, 0)) or (now_time >= time(13, 0))
    if not is_submission_allowed:
        st.warning("You can only submit tasks between 8:30 AM - 10:00 AM or after 1:00 PM.")
        return

    # Initialize session state for form fields
    if "project_name" not in st.session_state: st.session_state.project_name = ""
    if "task_description" not in st.session_state: st.session_state.task_description = ""

    with st.form("task_form"):
        entry_date = st.date_input("Date", value=datetime.now(IST).date())
        
        # We use session state to manage the input values
        st.session_state.task_description = st.text_area("Task Description", value=st.session_state.task_description)
        
        col1, col2 = st.columns([3, 1])
        with col1:
            st.session_state.project_name = st.text_input("Project Name", value=st.session_state.project_name)
        with col2:
            st.write("") # for vertical alignment
            st.write("") # for vertical alignment
            if st.form_submit_button("💡 Suggest Project"):
                project_list = get_unique_project_names()
                if project_list:
                    suggested_project = suggest_project_name(st.session_state.task_description, project_list)
                    st.session_state.project_name = suggested_project # Update session state
                    st.rerun() # Rerun to show the suggested name in the text box
                else:
                    st.warning("No existing projects to suggest from. Please enter one manually.")

        hours_worked = st.number_input("Hours Worked", min_value=0.5, step=0.5)
        
        if st.form_submit_button("Submit Task"):
            if st.session_state.project_name and st.session_state.task_description and hours_worked > 0:
                add_timesheet_entry(st.session_state['employee_id'], st.session_state.project_name, st.session_state.task_description, hours_worked, entry_date)
                st.success("Your task has been submitted successfully!")
                # Clear form fields after successful submission
                st.session_state.project_name = ""
                st.session_state.task_description = ""
            else:
                st.error("Please fill out all fields.")

def admin_view():
    st.header("Admin Panel")
    st.subheader("Add New Employee")
    with st.form("add_employee_form", clear_on_submit=True):
        employee_id = st.text_input("Employee ID")
        name = st.text_input("Employee Name")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Add Employee"):
            if employee_id and name and password: add_employee(employee_id, name, password)
            else: st.error("Please provide all details.")
    st.subheader("All Employees")
    st.dataframe(get_all_employees(), use_container_width=True)

def manager_dashboard():
    st.header("Admin Dashboard")
    st.subheader("Today's Attendance Status")
    
    attendance_placeholder = st.empty()
    attendance_placeholder.dataframe(get_attendance_status(), use_container_width=True)

    st.subheader("Today's Timesheet Entries")
    timesheet_placeholder = st.empty()
    timesheet_placeholder.dataframe(get_timesheet_entries_today(), use_container_width=True)

    # Real-time update loop
    while True:
        last_update_time = get_last_update_time()
        if 'last_update_check' not in st.session_state or last_update_time > st.session_state.last_update_check:
            st.session_state.last_update_check = last_update_time
            attendance_placeholder.dataframe(get_attendance_status(), use_container_width=True)
            timesheet_placeholder.dataframe(get_timesheet_entries_today(), use_container_width=True)
        time_sleep.sleep(2)

def main():
    initialize_database()
    st.title("AI-Powered Company Timesheet Portal")

    # Initialize session states
    if "logged_in" not in st.session_state: st.session_state.logged_in = False
    if "admin_logged_in" not in st.session_state: st.session_state.admin_logged_in = False

    # Main navigation logic
    if st.session_state.admin_logged_in:
        page = st.sidebar.selectbox("Admin Menu", ["Dashboard", "Manage Employees"])
        if st.sidebar.button("Logout Admin"):
            st.session_state.admin_logged_in = False
            st.rerun()
        if page == "Dashboard": manager_dashboard()
        else: admin_view()
    elif st.session_state.logged_in:
        employee_view()
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.rerun()
    else:
        role = st.sidebar.radio("Choose your portal", ["Employee Login", "Admin/Manager"])
        if role == "Employee Login": login_page()
        else:
            password = st.sidebar.text_input("Enter Admin Password", type="password")
            if st.sidebar.button("Access Admin Panel"):
                if password == ADMIN_PASSWORD:
                    st.session_state.admin_logged_in = True
                    st.rerun()
                else:
                    st.sidebar.error("Incorrect password.")

if __name__ == "__main__":
    main()
