import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, time
import time as time_sleep
import os
import hashlib

# --- App Configuration ---
st.set_page_config(page_title="Timesheet & Attendance Tool", layout="wide")

# --- Database Setup ---
DB_FILE = "company_data.db"
LAST_UPDATE_FILE = "last_update.txt"
ADMIN_PASSWORD = "admin" # Simple password for admin access

def hash_password(password):
    """Hashes the password for secure storage."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    """Creates the necessary tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Employee table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password TEXT NOT NULL
        )
    """)
    # Timesheet table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timesheet (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            task_description TEXT NOT NULL,
            hours_worked REAL NOT NULL,
            submission_date DATE NOT NULL,
            submission_time TIME NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
        )
    """)
    conn.commit()
    conn.close()

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
def add_timesheet_entry(employee_id, project_name, task_description, hours_worked):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("""
        INSERT INTO timesheet (employee_id, project_name, task_description, hours_worked, submission_date, submission_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (employee_id, project_name, task_description, hours_worked, now.date(), now.strftime("%H:%M:%S")))
    conn.commit()
    conn.close()
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(now.timestamp()))

def get_timesheet_entries_today():
    conn = get_db_connection()
    today = datetime.now().date()
    query = """
    SELECT t.employee_id, e.name, t.project_name, t.task_description, t.hours_worked, t.submission_time
    FROM timesheet t
    JOIN employees e ON t.employee_id = e.employee_id
    WHERE t.submission_date = ?
    ORDER BY t.submission_time DESC
    """
    df = pd.read_sql_query(query, conn, params=(str(today),))
    conn.close()
    return df

def get_attendance_status():
    """Determines the attendance status for all employees for the current day."""
    employees_df = get_all_employees()
    if employees_df.empty:
        return pd.DataFrame(columns=["Employee ID", "Name", "Status"])

    timesheet_today_df = get_timesheet_entries_today()

    status_list = []
    today = datetime.now().date()

    for index, employee in employees_df.iterrows():
        emp_id = employee["employee_id"]
        emp_name = employee["name"]
        emp_entries = timesheet_today_df[timesheet_today_df['employee_id'] == emp_id]

        status = "Absent"
        if not emp_entries.empty:
            first_entry_time_str = emp_entries['submission_time'].min()
            first_entry_time = datetime.strptime(first_entry_time_str, '%H:%M:%S').time()

            if time(8, 30) <= first_entry_time <= time(10, 0):
                status = "Present"
            elif first_entry_time >= time(13, 0):
                status = "Half-day"
            else:
                status = "Present (Late)" # Or any other logic

        status_list.append({"Employee ID": emp_id, "Name": emp_name, "Status": status})

    return pd.DataFrame(status_list)


# --- Real-time Update Mechanism ---
def get_last_update_time():
    if os.path.exists(LAST_UPDATE_FILE):
        with open(LAST_UPDATE_FILE, "r") as f:
            try:
                return float(f.read().strip())
            except (ValueError, TypeError):
                return 0.0
    return 0.0

# --- Authentication ---
def check_employee_credentials(employee_id, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM employees WHERE employee_id = ?", (employee_id,))
    result = cursor.fetchone()
    conn.close()
    if result and result['password'] == hash_password(password):
        return True
    return False

# --- Streamlit UI Views ---
def login_page():
    st.header("Employee Login")
    with st.form("login_form"):
        employee_id = st.text_input("Employee ID")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

        if submitted:
            if check_employee_credentials(employee_id, password):
                st.session_state["logged_in"] = True
                st.session_state["employee_id"] = employee_id
                st.rerun()
            else:
                st.error("Invalid Employee ID or Password. Please contact your manager if you are not added.")

def employee_view():
    st.header(f"Timesheet Entry for {st.session_state['employee_id']}")

    now_time = datetime.now().time()
    is_morning_window = time(8, 30) <= now_time <= time(10, 0)
    is_afternoon = now_time >= time(13, 0)

    if not is_morning_window and not is_afternoon:
        st.warning("You can only submit tasks between 8:30 AM - 10:00 AM or after 1:00 PM.")
        return

    with st.form("task_form", clear_on_submit=True):
        project_name = st.text_input("Project Name")
        task_description = st.text_area("Task Description")
        hours_worked = st.number_input("Hours Worked", min_value=0.5, step=0.5)
        submitted = st.form_submit_button("Submit Task")

        if submitted:
            if project_name and task_description and hours_worked > 0:
                add_timesheet_entry(st.session_state['employee_id'], project_name, task_description, hours_worked)
                st.success("Your task has been submitted successfully!")
            else:
                st.error("Please fill out all fields.")

def admin_view():
    st.header("Admin Panel")
    st.subheader("Add New Employee")
    with st.form("add_employee_form", clear_on_submit=True):
        employee_id = st.text_input("Employee ID")
        name = st.text_input("Employee Name")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Add Employee")

        if submitted:
            if employee_id and name and password:
                add_employee(employee_id, name, password)
            else:
                st.error("Please provide all details for the new employee.")

    st.subheader("All Employees")
    st.dataframe(get_all_employees(), use_container_width=True)


def manager_dashboard():
    st.header("Manager Dashboard")
    st.subheader("Today's Attendance Status")
    
    if 'last_update_attendance' not in st.session_state:
        st.session_state.last_update_attendance = get_last_update_time()
        st.session_state.attendance_data = get_attendance_status()

    attendance_placeholder = st.empty()
    attendance_placeholder.dataframe(st.session_state.attendance_data, use_container_width=True)

    st.subheader("Today's Timesheet Entries")
    if 'last_update_timesheet' not in st.session_state:
        st.session_state.last_update_timesheet = get_last_update_time()
        st.session_state.timesheet_data = get_timesheet_entries_today()

    timesheet_placeholder = st.empty()
    timesheet_placeholder.dataframe(st.session_state.timesheet_data, use_container_width=True)

    # Real-time update loop
    while True:
        time_sleep.sleep(2) # Check every 2 seconds
        last_update_time = get_last_update_time()
        if last_update_time > st.session_state.get('last_update_attendance', 0.0):
            st.session_state.last_update_attendance = last_update_time
            st.session_state.last_update_timesheet = last_update_time
            
            # Update data
            st.session_state.attendance_data = get_attendance_status()
            st.session_state.timesheet_data = get_timesheet_entries_today()

            # Rerender placeholders
            attendance_placeholder.dataframe(st.session_state.attendance_data, use_container_width=True)
            timesheet_placeholder.dataframe(st.session_state.timesheet_data, use_container_width=True)
            # A small break to let Streamlit process the update
            time_sleep.sleep(0.1)


# --- Main App Logic ---
def main():
    initialize_database()

    st.title("Company Timesheet and Attendance Portal")

    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
    if "admin_logged_in" not in st.session_state:
        st.session_state["admin_logged_in"] = False

    # Sidebar for navigation
    st.sidebar.title("Navigation")
    
    # Determine which main view to show
    if st.session_state.admin_logged_in:
        page = st.sidebar.selectbox("Admin Menu", ["Dashboard", "Manage Employees"])
        if st.sidebar.button("Logout Admin"):
            st.session_state.admin_logged_in = False
            st.rerun()
        
        if page == "Dashboard":
            manager_dashboard()
        elif page == "Manage Employees":
            admin_view()
    
    elif st.session_state.logged_in:
        employee_view()
        if st.sidebar.button("Logout"):
            st.session_state.logged_in = False
            st.rerun()

    else:
        # Show login options if no one is logged in
        role = st.sidebar.radio("Choose your portal", ["Employee Login", "Admin/Manager"])
        if role == "Employee Login":
            login_page()
        elif role == "Admin/Manager":
            password = st.sidebar.text_input("Enter Admin Password", type="password")
            if st.sidebar.button("Access Admin Panel"):
                if password == ADMIN_PASSWORD:
                    st.session_state.admin_logged_in = True
                    st.rerun()
                else:
                    st.sidebar.error("Incorrect password.")

if __name__ == "__main__":
    main()
