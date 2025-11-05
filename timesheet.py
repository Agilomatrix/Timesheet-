import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import time
import os

# --- Database Setup ---
DB_FILE = "timesheet.db"
LAST_UPDATE_FILE = "last_update.txt"

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    """Creates the timesheet table if it doesn't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timesheet (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            task_description TEXT NOT NULL,
            hours_worked REAL NOT NULL,
            submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def add_timesheet_entry(employee_name, project_name, task_description, hours_worked):
    """Adds a new entry to the timesheet database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO timesheet (employee_name, project_name, task_description, hours_worked)
        VALUES (?, ?, ?, ?)
    """, (employee_name, project_name, task_description, hours_worked))
    conn.commit()
    conn.close()
    # Signal that an update has occurred
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(datetime.now().timestamp()))

def get_all_timesheet_entries():
    """Retrieves all timesheet entries from the database."""
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM timesheet ORDER BY submission_date DESC", conn)
    conn.close()
    return df

# --- Real-time Update Mechanism ---
def get_last_update_time():
    """Gets the timestamp of the last database update."""
    if os.path.exists(LAST_UPDATE_FILE):
        with open(LAST_UPDATE_FILE, "r") as f:
            try:
                return float(f.read().strip())
            except (ValueError, TypeError):
                return 0.0
    return 0.0

# --- Streamlit App ---
st.set_page_config(page_title="Timesheet Tool", layout="wide")

def employee_view():
    """UI for the employee to submit timesheet entries."""
    st.header("Employee Timesheet Entry")
    with st.form("timesheet_form", clear_on_submit=True):
        employee_name = st.text_input("Employee Name", key="employee_name")
        project_name = st.text_input("Project Name", key="project_name")
        task_description = st.text_area("Task Description", key="task_description")
        hours_worked = st.number_input("Hours Worked", min_value=0.0, step=0.5, key="hours_worked")
        submitted = st.form_submit_button("Submit")

        if submitted:
            if employee_name and project_name and task_description and hours_worked > 0:
                add_timesheet_entry(employee_name, project_name, task_description, hours_worked)
                st.success("Timesheet entry submitted successfully!")
            else:
                st.error("Please fill out all fields.")

def manager_view():
    """UI for the manager to view all timesheet entries with real-time updates."""
    st.header("Manager Dashboard")

    if 'last_update' not in st.session_state:
        st.session_state.last_update = get_last_update_time()
        st.session_state.data = get_all_timesheet_entries()

    # Placeholder for the data table
    data_placeholder = st.empty()
    data_placeholder.dataframe(st.session_state.data, use_container_width=True)

    while True:
        time.sleep(1)
        last_update_time = get_last_update_time()
        if last_update_time > st.session_state.last_update:
            st.session_state.last_update = last_update_time
            st.session_state.data = get_all_timesheet_entries()
            data_placeholder.dataframe(st.session_state.data, use_container_width=True)

def main():
    """Main function to run the Streamlit app."""
    initialize_database()

    st.title("Company Timesheet Tool")

    # Simple role selection
    role = st.sidebar.radio("Select Your Role", ["Employee", "Manager"])

    if role == "Employee":
        employee_view()
    elif role == "Manager":
        manager_view()

if __name__ == "__main__":
    main()
