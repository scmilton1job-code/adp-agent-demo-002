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
            direct_deposit_split TEXT,
            location_id TEXT,
            status TEXT DEFAULT 'active'
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

    # --- Workforce/ERP join model (Northfield Outdoor Co. dataset) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            location_id TEXT PRIMARY KEY,
            location_code TEXT,
            location_name TEXT,
            city TEXT,
            state TEXT,
            country TEXT,
            location_type TEXT,
            cost_center_code TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS erp_gl_transactions (
            transaction_id TEXT PRIMARY KEY,
            cost_center_code TEXT,
            gl_account_code TEXT,
            period TEXT,
            transaction_type TEXT,
            amount REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS erp_labor_expense_codes (
            department TEXT,
            gl_account_code TEXT,
            allocation_pct REAL,
            PRIMARY KEY (department, gl_account_code)
        )
    ''')

    # Migrate existing employees tables that predate the location_id column.
    # CREATE TABLE IF NOT EXISTS is a no-op on a table that already exists,
    # so a column added to the schema above won't appear on disk without this.
    cursor.execute("PRAGMA table_info(employees)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if "location_id" not in existing_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN location_id TEXT")
        logger.info("Migrated 'employees' table: added location_id column.")
    if "status" not in existing_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN status TEXT DEFAULT 'active'")
        logger.info("Migrated 'employees' table: added status column.")
    
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
            ("789", "John", "Doe", "john.doe@example.com", "Sales", "Account Executive", "2025-01-10", "US-NY", json.dumps({"withholding_allowances": 2, "extra_withholding": 50}), json.dumps({"checking": "100%"}), None, "active"),
            ("101", "Sarah", "Chen", "sarah.chen@example.com", "Engineering", "Senior Cloud Engineer", "2026-07-01", "US-CA", json.dumps({"withholding_allowances": 1, "extra_withholding": 0}), json.dumps({"checking": "100%"}), None, "active"),
        ]
        cursor.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", employees)
        logger.info("Successfully seeded 'employees' table.")

    # Seed Northfield Outdoor Co. workforce — IDs prefixed N- to avoid colliding
    # with the existing demo employees (789, 101) above. withholding_elections
    # is real JSON (not a placeholder string) so the payroll dry-run agent in
    # agent.py can parse it without breaking.
    cursor.execute("SELECT COUNT(*) FROM employees WHERE id LIKE 'N-%'")
    if cursor.fetchone()[0] == 0:
        northfield_employees = [
            ("N-1", "Sarah", "Chen", "sarah.chen@northfield.com", "Sales", "Sales Associate", "2024-01-10",
             "US-NY", json.dumps({"withholding_allowances": 2, "extra_withholding": 0}), json.dumps({"checking": "100%"}), "LOC-100", "active"),
            ("N-2", "John", "Doe", "john.doe@northfield.com", "Operations", "Store Manager", "2023-05-20",
             "US-NY", json.dumps({"withholding_allowances": 1, "extra_withholding": 25}), json.dumps({"checking": "100%"}), "LOC-100", "active"),
            ("N-3", "Emily", "Davis", "emily.davis@northfield.com", "Sales", "Sales Associate", "2024-03-15",
             "US-NY", json.dumps({"withholding_allowances": 2, "extra_withholding": 0}), json.dumps({"checking": "100%"}), "LOC-101", "active"),
            ("N-4", "Michael", "Brown", "michael.brown@northfield.com", "Operations", "Inventory Lead", "2022-11-01",
             "US-NJ", json.dumps({"withholding_allowances": 3, "extra_withholding": 0}), json.dumps({"checking": "100%"}), "LOC-200", "active"),
            ("N-5", "Jessica", "Lee", "jessica.lee@northfield.com", "Sales", "Cashier", "2024-06-01",
             "US-PA", json.dumps({"withholding_allowances": 1, "extra_withholding": 0}), json.dumps({"checking": "100%"}), "LOC-300", "active"),
            ("N-6", "David", "Wilson", "david.wilson@northfield.com", "Operations", "Warehouse Manager", "2021-08-12",
             "US-TX", json.dumps({"withholding_allowances": 2, "extra_withholding": 0}), json.dumps({"checking": "100%"}), "LOC-400", "active"),
        ]
        cursor.executemany("INSERT INTO employees VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", northfield_employees)
        logger.info("Successfully seeded Northfield Outdoor Co. workforce rows in 'employees' table.")

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

    # Seed Locations (Northfield Outdoor Co. — the join backbone)
    cursor.execute("SELECT COUNT(*) FROM locations")
    if cursor.fetchone()[0] == 0:
        locations = [
            ("LOC-100", "NY01", "Downtown Flagship", "New York", "NY", "US", "HQ", "CC-4410"),
            ("LOC-101", "NY02", "Brooklyn Store", "New York", "NY", "US", "Physical", "CC-4411"),
            ("LOC-200", "NJ01", "Newark Outlet", "Newark", "NJ", "US", "Physical", "CC-4420"),
            ("LOC-300", "PA01", "Philadelphia Store", "Philadelphia", "PA", "US", "Physical", "CC-4430"),
            ("LOC-400", "TX01", "Dallas Warehouse", "Dallas", "TX", "US", "Physical", "CC-4440"),
        ]
        cursor.executemany("INSERT INTO locations VALUES (?,?,?,?,?,?,?,?)", locations)
        logger.info("Successfully seeded 'locations' table.")

    # Seed ERP GL transactions — two periods, actual + budget, with two
    # deliberately underperforming cost centers (Newark, Dallas) so the
    # insights query layer has a real finding to surface.
    cursor.execute("SELECT COUNT(*) FROM erp_gl_transactions")
    if cursor.fetchone()[0] == 0:
        erp_transactions = [
            ("T1",  "CC-4410", "4000-REVENUE", "2026-04", "actual", 150000),
            ("T2",  "CC-4410", "6010-LABOR",   "2026-04", "actual", 80000),
            ("T3",  "CC-4411", "4000-REVENUE", "2026-04", "actual", 90000),
            ("T4",  "CC-4411", "6010-LABOR",   "2026-04", "actual", 70000),
            ("T5",  "CC-4420", "4000-REVENUE", "2026-04", "actual", 60000),
            ("T6",  "CC-4420", "6010-LABOR",   "2026-04", "actual", 65000),
            ("T7",  "CC-4410", "4000-REVENUE", "2026-05", "actual", 160000),
            ("T8",  "CC-4410", "6010-LABOR",   "2026-05", "actual", 82000),
            ("T9",  "CC-4440", "4000-REVENUE", "2026-05", "actual", 50000),
            ("T10", "CC-4440", "6010-LABOR",   "2026-05", "actual", 60000),
            ("T11", "CC-4410", "4000-REVENUE", "2026-05", "budget", 155000),
            ("T12", "CC-4410", "6010-LABOR",   "2026-05", "budget", 78000),
            ("T13", "CC-4440", "4000-REVENUE", "2026-05", "budget", 70000),
            ("T14", "CC-4440", "6010-LABOR",   "2026-05", "budget", 55000),
        ]
        cursor.executemany("INSERT INTO erp_gl_transactions VALUES (?,?,?,?,?,?)", erp_transactions)
        logger.info("Successfully seeded 'erp_gl_transactions' table.")

    # Seed the department-to-GL bridge (resolves "labor cost by department")
    cursor.execute("SELECT COUNT(*) FROM erp_labor_expense_codes")
    if cursor.fetchone()[0] == 0:
        bridge_rows = [
            ("Sales", "6010-LABOR", 1.0),
            ("Operations", "6010-LABOR", 1.0),
        ]
        cursor.executemany("INSERT INTO erp_labor_expense_codes VALUES (?,?,?)", bridge_rows)
        logger.info("Successfully seeded 'erp_labor_expense_codes' table.")
        
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
                 "startDate", "tax_jurisdiction", "location_id"}
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


# --- Workforce/ERP Financial Insights Query Layer ---
# Reuses the existing mock_ats.db connection pattern (DB_PATH defined at top
# of file) rather than a separate database, so these queries see the same
# data the rest of the app uses.

def get_low_performing_locations(period: str = "2026-05") -> list[dict]:
    """
    Ranks locations by labor-to-revenue ratio (descending) for a given period.
    Highest ratio = worst labor efficiency.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT
            l.location_name,
            SUM(CASE WHEN e.gl_account_code = '4000-REVENUE' AND e.transaction_type = 'actual'
                     THEN e.amount ELSE 0 END) AS revenue,
            SUM(CASE WHEN e.gl_account_code = '6010-LABOR' AND e.transaction_type = 'actual'
                     THEN e.amount ELSE 0 END) AS labor
        FROM locations l
        JOIN erp_gl_transactions e ON l.cost_center_code = e.cost_center_code
        WHERE e.period = ?
        GROUP BY l.location_name
        ORDER BY (labor * 1.0 / NULLIF(revenue, 0)) DESC
    ''', (period,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "location": r[0],
            "revenue": r[1],
            "labor": r[2],
            "labor_ratio": round(r[2] / r[1], 2) if r[1] else None,
        }
        for r in rows
    ]


def get_labor_vs_budget_variance(period: str = "2026-05") -> list[dict]:
    """
    Compares actual vs budgeted labor cost per location for a given period.
    Only returns locations that have budget data for that period.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT
            l.location_name,
            SUM(CASE WHEN e.transaction_type = 'actual' AND e.gl_account_code = '6010-LABOR'
                     THEN e.amount ELSE 0 END) AS actual_labor,
            SUM(CASE WHEN e.transaction_type = 'budget' AND e.gl_account_code = '6010-LABOR'
                     THEN e.amount ELSE 0 END) AS budget_labor
        FROM locations l
        JOIN erp_gl_transactions e ON l.cost_center_code = e.cost_center_code
        WHERE e.period = ?
        GROUP BY l.location_name
        HAVING budget_labor > 0
    ''', (period,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "location": r[0],
            "actual_labor": r[1],
            "budget_labor": r[2],
            "variance": r[1] - r[2],
            "variance_pct": round((r[1] - r[2]) / r[2] * 100, 1) if r[2] else None,
        }
        for r in rows
    ]


def get_labor_cost_by_department(period: str = "2026-05") -> list[dict]:
    """
    Allocates labor GL spend to departments via the erp_labor_expense_codes
    bridge table, joined through employees -> locations -> ERP transactions.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT
            emp.department,
            SUM(e.amount * bridge.allocation_pct) AS labor_cost
        FROM employees emp
        JOIN locations l ON emp.location_id = l.location_id
        JOIN erp_gl_transactions e ON l.cost_center_code = e.cost_center_code
        JOIN erp_labor_expense_codes bridge
            ON emp.department = bridge.department
            AND e.gl_account_code = bridge.gl_account_code
        WHERE e.period = ? AND e.transaction_type = 'actual'
        GROUP BY emp.department
    ''', (period,))
    rows = cursor.fetchall()
    conn.close()
    return [{"department": r[0], "labor_cost": r[1]} for r in rows]


def generate_morning_report(period: str = "2026-05") -> dict:
    """
    Composes the location and budget-variance insights into a single
    proactive summary, suitable for the 'automated morning report' agent flow.
    """
    low_perf = get_low_performing_locations(period)
    variance = get_labor_vs_budget_variance(period)
    return {
        "headline": "Daily Workforce & Financial Insights",
        "period": period,
        "top_risk_locations": low_perf[:3],
        "budget_variance": variance,
    }