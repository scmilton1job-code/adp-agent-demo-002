import sqlite3
import json
import os
import logging

logger = logging.getLogger("adp-agent.tools")
DB_PATH = "mock_ats.db"

def init_and_seed_db():
    """
    Ensures mock_ats.db exists, creates schemas, and seeds robust, highly specific 
    industry testing records if the database is empty.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            firstName TEXT,
            lastName TEXT,
            email TEXT,
            department TEXT,
            jobTitle TEXT,
            startDate TEXT,
            status TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY,
            firstName TEXT,
            lastName TEXT,
            email TEXT,
            department TEXT,
            jobTitle TEXT,
            startDate TEXT,
            tax_jurisdiction TEXT,
            withholding_elections TEXT,
            direct_deposit_split TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            shift_id TEXT PRIMARY KEY,
            team_name TEXT,
            assigned_worker_id TEXT,
            date TEXT,
            time_slot TEXT,
            coverage_status TEXT,
            pending_offers_count INTEGER
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profiles (
            employee_id TEXT PRIMARY KEY,
            skills TEXT,
            education TEXT,
            work_history TEXT
        )
    ''')
    
    # Seed Candidates
    cursor.execute("SELECT COUNT(*) FROM candidates")
    if cursor.fetchone()[0] == 0:
        candidates = [
            ("101", "Sarah", "Chen", "sarah.chen@example.com", "Engineering", "Senior Cloud Engineer", "2026-07-01", "hired"),
            ("102", "Marcus", "Vance", "marcus.vance@example.com", "Product", "Technical Product Manager", "2026-07-15", "hired"),
            ("201", "Elena", "Vasquez", "elena.vasquez@example.com", "Operations", "Compliance Specialist", None, "hired"),  # Missing startDate (Amber path trigger)
            ("202", "Alex", "Kowalski", "alex.k@example.com", "Engineering", "Security Analyst", "2026-08-01", "interviewing")
        ]
        cursor.executemany("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?)", candidates)
        logger.info("Successfully seeded 'candidates' table.")

    # Seed Employees
    cursor.execute("SELECT COUNT(*) FROM employees")
    if cursor.fetchone()[0] == 0:
        employees = [
            ("789", "John", "Doe", "john.doe@example.com", "Sales", "Account Executive", "2025-01-10", "US-NY", json.dumps({"withholding_allowances": 2, "extra_withholding": 50}), json.dumps({"checking": "100%"})),
            ("101", "Sarah", "Chen", "sarah.chen@example.com", "Engineering", "Senior Cloud Engineer", "2026-07-01", "US-CA", json.dumps({"withholding_allowances": 1, "extra_withholding": 0}), json.dumps({"checking": "100%"}))
        ]
        cursor.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?)", employees)
        logger.info("Successfully seeded 'employees' table.")

    # Seed Schedules (eTIME mock data)
    cursor.execute("SELECT COUNT(*) FROM schedules")
    if cursor.fetchone()[0] == 0:
        schedules = [
            ("S-901", "Cloud Ops Team", "101", "2026-06-12", "08:00 - 16:00", "assigned", 0),
            ("S-902", "Data Science Team", None, "2026-06-12", "16:00 - 00:00", "open_shift", 0),  # Open shift (UC3 target)
            ("S-903", "Platform Security Team", None, "2026-06-13", "08:00 - 16:00", "open_shift", 0)
        ]
        cursor.executemany("INSERT INTO schedules VALUES (?,?,?,?,?,?,?)", schedules)
        logger.info("Successfully seeded 'schedules' table.")
        
    conn.commit()
    conn.close()

# Ensure seeding is executed upon file load
init_and_seed_db()


# --- Read/Retrieval Helpers ---

def get_candidate_from_ats(candidate_id: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_employee_from_adp(employee_id: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        data = dict(row)
        # Deserialize JSON fields
        if data.get("withholding_elections"):
            data["withholding_elections"] = json.loads(data["withholding_elections"])
        if data.get("direct_deposit_split"):
            data["direct_deposit_split"] = json.loads(data["direct_deposit_split"])
        return data
    return None

def get_all_active_employees() -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees")
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        d = dict(row)
        if d.get("withholding_elections"):
            d["withholding_elections"] = json.loads(d["withholding_elections"])
        if d.get("direct_deposit_split"):
            d["direct_deposit_split"] = json.loads(d["direct_deposit_split"])
        results.append(d)
    return results

def get_schedule_details(shift_id: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schedules WHERE shift_id = ?", (shift_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


# --- Compliance & SCIM Standard Transformers ---

def transform_to_scim_format(candidate: dict) -> dict:
    """
    Maps localized candidate record blocks into strict RFC 7643 SCIM User Schema structures
    paired with custom corporate Enterprise Extensions.
    """
    email_val = candidate.get("email", "")
    given_name = candidate.get("firstName", "")
    family_name = candidate.get("lastName", "")
    dept = candidate.get("department", "")
    title = candidate.get("jobTitle", "")
    
    return {
        "schemas": [
            "urn:ietf:params:scim:schemas:core:2.0:User",
            "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
        ],
        "id": str(candidate.get("id")),
        "userName": email_val,
        "name": {
            "givenName": given_name,
            "familyName": family_name,
            "formatted": f"{given_name} {family_name}"
        },
        "emails": [
            {
                "value": email_val,
                "type": "work",
                "primary": True
            }
        ],
        "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User": {
            "department": dept,
            "jobTitle": title,
            "companyCode": "ADP-SIMPLIFIED-ENT"
        }
    }


# --- Dynamic Real-Time Write Handlers ---

def execute_tax_withholding_write(employee_id: str, jurisdiction: str, elections: dict) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check employee presence
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    if not cursor.fetchone():
        conn.close()
        raise ValueError(f"Employee with ID {employee_id} not found in System of Record.")
        
    serialized_elections = json.dumps(elections)
    cursor.execute('''
        UPDATE employees 
        SET tax_jurisdiction = ?, withholding_elections = ? 
        WHERE id = ?
    ''', (jurisdiction, serialized_elections, employee_id))
    
    conn.commit()
    conn.close()
    return {
        "employeeId": employee_id,
        "status": "committed",
        "updated_canonical": "taxWithholding",
        "applied_jurisdiction": jurisdiction,
        "elections": elections
    }

def execute_etime_coverage_write(shift_id: str, action: str, target_workers: list) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Find shift
    cursor.execute("SELECT * FROM schedules WHERE shift_id = ?", (shift_id,))
    if not cursor.fetchone():
        conn.close()
        raise ValueError(f"Shift with ID {shift_id} not found in scheduling ledger.")
        
    # Update shift parameters to show active resolution processing
    cursor.execute('''
        UPDATE schedules 
        SET coverage_status = 'processing', pending_offers_count = ? 
        WHERE shift_id = ?
    ''', (len(target_workers), shift_id))
    
    conn.commit()
    conn.close()
    return {
        "shiftId": shift_id,
        "action_executed": action,
        "notifications_dispatched": len(target_workers),
        "status": "active_orchestration",
        "eligible_recipients": target_workers
    }

def execute_ksao_profile_write(employee_id: str, new_skills: list) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT skills FROM profiles WHERE employee_id = ?", (employee_id,))
    row = cursor.fetchone()
    
    if row:
        existing_skills = json.loads(row[0]) if row[0] else []
        combined = list(set(existing_skills + new_skills))
        cursor.execute(
            "UPDATE profiles SET skills = ? WHERE employee_id = ?",
            (json.dumps(combined), employee_id)
        )
    else:
        cursor.execute(
            "INSERT INTO profiles (employee_id, skills, education, work_history) VALUES (?, ?, ?, ?)",
            (employee_id, json.dumps(new_skills), json.dumps([]), json.dumps([]))
        )
        
    conn.commit()
    conn.close()
    return {
        "employeeId": employee_id,
        "sync_count": len(new_skills),
        "profile_schema": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User",
        "current_skills": new_skills
    }


def terminate_employee(employee_id: str) -> dict:
    """
    Marks an employee record as terminated in the System of Record.
    Raises ValueError if the employee does not exist.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM employees WHERE id = ?", (employee_id,))
    if not cursor.fetchone():
        conn.close()
        raise ValueError(f"Employee '{employee_id}' not found.")
    cursor.execute(
        "UPDATE employees SET status = ? WHERE id = ?",
        ("terminated", employee_id),
    )
    conn.commit()
    conn.close()
    return {
        "employeeId": employee_id,
        "status": "terminated",
        "message": "Employee record marked terminated in System of Record.",
    }


def update_employee_fields(employee_id: str, fields: dict) -> dict:
    """
    Applies arbitrary field updates to an employee record.
    Only columns that exist on the employees table are updated.
    Raises ValueError if the employee does not exist or no valid fields supplied.
    """
    UPDATABLE = {"firstName", "lastName", "email", "department", "jobTitle",
                 "startDate", "tax_jurisdiction"}
    valid = {k: v for k, v in fields.items() if k in UPDATABLE}
    if not valid:
        raise ValueError(
            f"No updatable fields supplied. Allowed: {sorted(UPDATABLE)}"
        )

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM employees WHERE id = ?", (employee_id,))
    if not cursor.fetchone():
        conn.close()
        raise ValueError(f"Employee '{employee_id}' not found.")

    set_clause = ", ".join(f"{col} = ?" for col in valid)
    values = list(valid.values()) + [employee_id]
    cursor.execute(f"UPDATE employees SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return {
        "employeeId": employee_id,
        "updated_fields": list(valid.keys()),
        "message": "Employee record updated in System of Record.",
    }