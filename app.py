import os
import re
import sys
import time
import json
import uuid
import subprocess
import threading
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

import pandas as pd
import pyotp
import qrcode

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    flash,
    session,
    url_for,
    jsonify,
    send_from_directory,
    send_file,
    make_response
)

from werkzeug.utils import secure_filename
from flask_bcrypt import Bcrypt

from database.db import get_connection

from config import (
    SECRET_KEY,
    APP_NAME,
    QR_CODE_FOLDER,
    ADMIN_EMAIL,
    ADMIN_PASSWORD
)

from services.resume_parser import (
    extract_resume_text,
    parse_candidate_info
)

from services.email_service import (
    send_candidate_confirmation_email,
    send_smtp_email,
    process_excel_email_sending,
    process_multi_file_email_batch,
    detect_email_column,
    generate_candidate_temp_password
)

from services.pdf_exam_service import parse_exam_pdf_file



# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)
app.secret_key = SECRET_KEY

bcrypt = Bcrypt(app)


# ============================================================
# CORS & PRIVATE NETWORK ACCESS HEADERS (FOR LOCAL LAN & CHROME)
# ============================================================

@app.after_request
def add_cors_and_security_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, Origin"
    response.headers["Access-Control-Allow-Private-Network"] = "true"

    # Prevent browser caching of sensitive HR, Admin, and API data across account logins
    path = request.path
    if path.startswith("/hr") or path.startswith("/admin") or path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ============================================================
# BASE DIRECTORY & CANONICAL PATHS (SPACE-SAFE)
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent
BASE_DIR = str(PROJECT_ROOT)

QR_CODE_DIR = (PROJECT_ROOT / QR_CODE_FOLDER).resolve() if not os.path.isabs(QR_CODE_FOLDER) else Path(QR_CODE_FOLDER).resolve()
QR_CODE_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = (PROJECT_ROOT / "uploads").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER = str(UPLOAD_DIR)

CANDIDATE_UPLOAD_DIR = (UPLOAD_DIR / "candidates").resolve()
CANDIDATE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CANDIDATE_UPLOAD_FOLDER = str(CANDIDATE_UPLOAD_DIR)

RESUME_DIR = (UPLOAD_DIR / "resumes").resolve()
RESUME_DIR.mkdir(parents=True, exist_ok=True)
RESUME_FOLDER = str(RESUME_DIR)

AUTOMATION_DIR = (PROJECT_ROOT / "automation").resolve()
AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
AUTOMATION_FOLDER = str(AUTOMATION_DIR)

AUTOMATION_LOG_DIR = (AUTOMATION_DIR / "logs").resolve()
AUTOMATION_LOG_DIR.mkdir(parents=True, exist_ok=True)
AUTOMATION_LOG_FOLDER = str(AUTOMATION_LOG_DIR)

ROBOT_FILE = str((AUTOMATION_DIR / "candidate_automation.robot").resolve())
DEFAULT_BROWSER_MODE = "headless"


# ============================================================
# ALLOWED FILE TYPES
# ============================================================

ALLOWED_CANDIDATE_FILES = {
    "csv",
    "xlsx",
    "xls"
}

ALLOWED_RESUME_FILES = {
    "pdf",
    "doc",
    "docx"
}


# ============================================================
# AUTOMATION JOBS
# ============================================================

AUTOMATION_JOBS = {}


# ============================================================
# DATABASE SCHEMA MIGRATION / INITIALIZATION
# ============================================================

def ensure_database_schema():
    """
    Guarantees the candidates table exists with all required tracking columns:
    resume, resume_filename, resume_status, registration_status, automation_status,
    status, processed_at, job_id, email_status.
    """
    connection = None
    cursor = None
    try:
        connection = get_connection()
        if connection is None:
            print("⚠️ Database connection unavailable during schema verification.")
            return

        cursor = connection.cursor()

        # 1. Create candidates table if not present
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                phone VARCHAR(50) NOT NULL,
                position VARCHAR(255) NOT NULL,
                resume VARCHAR(255) NULL,
                resume_filename VARCHAR(255) NULL,
                resume_status VARCHAR(100) DEFAULT 'Not Uploaded',
                registration_status VARCHAR(100) DEFAULT 'Registered',
                automation_status VARCHAR(100) DEFAULT 'Pending',
                status VARCHAR(100) DEFAULT 'New',
                created_at DATETIME NULL,
                processed_at DATETIME NULL,
                job_id VARCHAR(100) NULL,
                email_status VARCHAR(50) DEFAULT 'Pending'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # 1.4 Create automation_jobs table if not present
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS automation_jobs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                job_code VARCHAR(100) NOT NULL UNIQUE,
                user_id INT NULL,
                job_name VARCHAR(255) NOT NULL,
                status VARCHAR(50) DEFAULT 'Uploaded',
                total_files INT DEFAULT 0,
                total_candidates INT DEFAULT 0,
                processed_candidates INT DEFAULT 0,
                failed_candidates INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                error_message TEXT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # 1.5 Create uploaded_files table if not present
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id INT AUTO_INCREMENT PRIMARY KEY,
                upload_id VARCHAR(100) NULL,
                filename VARCHAR(255) NOT NULL,
                filepath VARCHAR(512) NOT NULL,
                file_type VARCHAR(50) NOT NULL,
                status VARCHAR(50) DEFAULT 'Pending',
                processed_count INT DEFAULT 0,
                total_count INT DEFAULT 0,
                created_at DATETIME NULL,
                processed_at DATETIME NULL,
                job_id VARCHAR(100) NULL,
                user_id INT NULL,
                error_message TEXT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # Check and add upload_id to uploaded_files if missing
        try:
            cursor.execute("SHOW COLUMNS FROM uploaded_files")
            uf_cols = {row[0].lower() for row in cursor.fetchall()}
            if "upload_id" not in uf_cols:
                cursor.execute("ALTER TABLE uploaded_files ADD COLUMN upload_id VARCHAR(100) NULL")
                print("✅ Added column upload_id to uploaded_files table.")
        except Exception as uf_err:
            print("Notice verifying uploaded_files columns:", uf_err)

        # Check and add upload_id and input_file_path to automation_jobs if missing
        try:
            cursor.execute("SHOW COLUMNS FROM automation_jobs")
            aj_cols = {row[0].lower() for row in cursor.fetchall()}
            if "upload_id" not in aj_cols:
                cursor.execute("ALTER TABLE automation_jobs ADD COLUMN upload_id VARCHAR(100) NULL")
                print("✅ Added column upload_id to automation_jobs table.")
            if "input_file_path" not in aj_cols:
                cursor.execute("ALTER TABLE automation_jobs ADD COLUMN input_file_path VARCHAR(512) NULL")
                print("✅ Added column input_file_path to automation_jobs table.")
        except Exception as aj_err:
            print("Notice verifying automation_jobs columns:", aj_err)

        # 1.6 Create users table if not present
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                fullname VARCHAR(255) NOT NULL,
                username VARCHAR(255) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                phone VARCHAR(50) NULL,
                password VARCHAR(255) NOT NULL,
                totp_secret VARCHAR(255) NULL,
                role VARCHAR(50) DEFAULT 'hr',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # Check and add missing columns in users table if needed
        try:
            cursor.execute("SHOW COLUMNS FROM users")
            existing_user_cols = {row[0].lower() for row in cursor.fetchall()}
            if "role" not in existing_user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN role VARCHAR(50) DEFAULT 'hr'")
                print("✅ Added column role to users table.")
            if "must_change_password" not in existing_user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN must_change_password INT DEFAULT 0")
                print("✅ Added column must_change_password to users table.")
            if "google_authenticator_configured" not in existing_user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN google_authenticator_configured INT DEFAULT 0")
                print("✅ Added column google_authenticator_configured to users table.")
        except Exception as u_col_err:
            print("Notice verifying users columns:", u_col_err)

        # 2. Inspect existing columns and add missing ones
        cursor.execute("SHOW COLUMNS FROM candidates")
        existing_cols = {row[0].lower() for row in cursor.fetchall()}

        required_cols = {
            "resume_filename": "VARCHAR(255) NULL",
            "resume_status": "VARCHAR(100) DEFAULT 'Not Uploaded'",
            "registration_status": "VARCHAR(100) DEFAULT 'Pending'",
            "automation_status": "VARCHAR(100) DEFAULT 'Pending'",
            "processed_at": "DATETIME NULL",
            "job_id": "VARCHAR(100) NULL",
            "upload_id": "VARCHAR(100) NULL",
            "email_status": "VARCHAR(50) DEFAULT 'Pending'",
            "skills": "TEXT NULL",
            "education": "TEXT NULL",
            "experience": "VARCHAR(255) NULL",
            "user_id": "INT NULL",
            "source_file": "VARCHAR(255) NULL",
            "file_id": "INT NULL",
            "error_message": "TEXT NULL",
            "step_failed": "VARCHAR(100) NULL",
            "temp_password_sent": "INT DEFAULT 0",
            "hr_id": "INT NULL"
        }

        for col_name, col_type in required_cols.items():
            if col_name not in existing_cols:
                try:
                    cursor.execute(f"ALTER TABLE candidates ADD COLUMN {col_name} {col_type}")
                    print(f"✅ Added column {col_name} to candidates table.")
                except Exception as col_err:
                    print(f"Notice: adding column {col_name}: {col_err}")

        # Ensure index on candidates(hr_id)
        try:
            cursor.execute("SHOW INDEX FROM candidates WHERE Key_name = 'idx_candidates_hr_id'")
            if not cursor.fetchone():
                cursor.execute("CREATE INDEX idx_candidates_hr_id ON candidates(hr_id)")
                print("✅ Created index idx_candidates_hr_id on candidates table.")
        except Exception as idx_err:
            print("Notice verifying candidates hr_id index:", idx_err)

        # Backfill hr_id for existing candidate records from automation_jobs, uploaded_files, or users
        try:
            cursor.execute("""
                UPDATE candidates c
                JOIN automation_jobs aj ON c.job_id = aj.job_code
                SET c.hr_id = aj.user_id
                WHERE c.hr_id IS NULL AND aj.user_id IS NOT NULL
            """)
            cursor.execute("""
                UPDATE candidates c
                JOIN uploaded_files uf ON c.upload_id = uf.upload_id
                SET c.hr_id = uf.user_id
                WHERE c.hr_id IS NULL AND uf.user_id IS NOT NULL
            """)
            cursor.execute("""
                UPDATE candidates c
                JOIN users u ON c.user_id = u.id AND LOWER(u.role) = 'hr'
                SET c.hr_id = u.id
                WHERE c.hr_id IS NULL
            """)
            connection.commit()
            print("✅ Verified and backfilled candidates hr_id ownership mapping.")
        except Exception as bf_err:
            print("Notice backfilling candidates hr_id:", bf_err)

        # 2.5 Migration & Repair: Guarantee every candidate in DB has a valid Candidate User account in users table
        try:
            dict_cur = connection.cursor(dictionary=True)
            dict_cur.execute("SELECT id, name, email, phone, user_id FROM candidates WHERE email IS NOT NULL AND email != ''")
            cands_to_check = dict_cur.fetchall()
            for c_item in cands_to_check:
                c_id = c_item["id"]
                c_name = c_item["name"] or "Candidate"
                c_email = str(c_item["email"]).strip().lower()
                c_phone = c_item["phone"] or ""
                c_uid = c_item.get("user_id")

                # Check if linked user exists, has candidate role, and matches candidate email
                valid_user = None
                if c_uid:
                    dict_cur.execute("SELECT id, email, role FROM users WHERE id = %s LIMIT 1", (c_uid,))
                    u_rec = dict_cur.fetchone()
                    if u_rec and str(u_rec.get("role") or "").strip().lower() == "candidate" and str(u_rec.get("email") or "").strip().lower() == c_email:
                        valid_user = u_rec

                if not valid_user:
                    dict_cur.execute("SELECT id, username, email, role FROM users WHERE email = %s LIMIT 1", (c_email,))
                    u_by_email = dict_cur.fetchone()
                    if u_by_email:
                        target_u_id = u_by_email["id"]
                        dict_cur.execute("UPDATE candidates SET user_id = %s, registration_status = 'Registered' WHERE id = %s", (target_u_id, c_id))
                        if str(u_by_email.get("role") or "").strip().lower() != "candidate":
                            dict_cur.execute("UPDATE users SET role = 'candidate' WHERE id = %s", (target_u_id,))
                    else:
                        local_p = c_email.split("@")[0] if "@" in c_email else c_email
                        clean_u = re.sub(r"[^a-z0-9._-]", "", local_p.lower()) or "candidate"
                        base_u = clean_u
                        cnt = 1
                        while True:
                            dict_cur.execute("SELECT id FROM users WHERE username = %s LIMIT 1", (clean_u,))
                            if not dict_cur.fetchone():
                                break
                            clean_u = f"{base_u}{cnt}"
                            cnt += 1

                        temp_pw = f"{local_p}@"
                        hashed_pw = bcrypt.generate_password_hash(temp_pw).decode("utf-8")
                        totp_sec = pyotp.random_base32()
                        dict_cur.execute(
                            "INSERT INTO users (fullname, username, email, phone, password, role, must_change_password, google_authenticator_configured, totp_secret) VALUES (%s, %s, %s, %s, %s, 'candidate', 1, 0, %s)",
                            (c_name, clean_u, c_email, c_phone, hashed_pw, totp_sec)
                        )
                        new_u_id = dict_cur.lastrowid
                        dict_cur.execute("UPDATE candidates SET user_id = %s, registration_status = 'Registered' WHERE id = %s", (new_u_id, c_id))

            connection.commit()
            dict_cur.close()
            print("✅ Verified and synchronized all candidate accounts in users database table.")
        except Exception as mig_err:
            print("Notice migrating candidate user accounts:", mig_err)


        # Repair: Ensure HR/admin roles for HR accounts
        try:
            cursor.execute("UPDATE users SET role = 'admin' WHERE id = 1 OR username = 'admin' OR email = 'admin@company.com'")
            cursor.execute("UPDATE users SET role = 'hr' WHERE role IS NULL OR role = ''")
            connection.commit()
            print("✅ Verified database HR role assignments.")
        except Exception as r_err:
            print("Notice restoring HR roles:", r_err)

        # 3. Optional controlled repair: Link existing physical resumes in uploads/resumes to unlinked candidates
        try:
            cursor.execute("""
                SELECT id, name, email, resume, resume_status
                FROM candidates
                WHERE resume_status IN ('Not Uploaded', 'Upload Failed') OR resume IS NULL
            """)
            unlinked = cursor.fetchall()
            resume_files_on_disk = [
                f for f in RESUME_DIR.iterdir()
                if f.is_file() and f.suffix.lower() in {".pdf", ".doc", ".docx"} and f.stat().st_size > 0
            ]
            if unlinked and resume_files_on_disk:
                for cand_row in unlinked:
                    cand_id = cand_row[0]
                    cand_name = cand_row[1]
                    cand_email = cand_row[2]
                    matched_file = None
                    clean_name = re.sub(r"[^a-z0-9]", "", str(cand_name).lower())
                    tokens = [t for t in re.findall(r"[a-z0-9]+", str(cand_name).lower()) if len(t) >= 2 and t not in {"resume", "cv", "profile", "applicant"}]
                    first_n = tokens[0] if tokens else ""
                    last_n = tokens[-1] if len(tokens) >= 2 else ""

                    for rf in resume_files_on_disk:
                        rf_stem_clean = re.sub(r"[^a-z0-9]", "", rf.stem.lower())
                        if clean_name and (clean_name == rf_stem_clean or clean_name in rf_stem_clean):
                            matched_file = rf
                            break
                        if first_n and last_n and (first_n in rf_stem_clean and last_n in rf_stem_clean):
                            matched_file = rf
                            break

                    if matched_file and matched_file.is_file():
                        cursor.execute("""
                            UPDATE candidates
                            SET resume=%s,
                                resume_filename=%s,
                                resume_status='Uploaded',
                                automation_status='Processed',
                                status='Processed'
                            WHERE id=%s
                        """, (matched_file.name, matched_file.name, cand_id))
                        print(f"🔗 Linked existing physical resume {matched_file.name} to candidate #{cand_id} ({cand_name})")
        except Exception as _relink_err:
            print("Notice during resume re-link:", _relink_err)

        connection.commit()
        print("✅ Candidates database schema verified successfully.")
    except Exception as e:
        print(f"⚠️ ensure_database_schema error: {e}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def ensure_exam_database_schema():
    """
    Creates examination module tables if not present.
    """
    connection = None
    cursor = None
    try:
        connection = get_connection()
        if not connection:
            return
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exams (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT NULL,
                duration_minutes INT DEFAULT 30,
                total_marks DECIMAL(8,2) DEFAULT 30.00,
                passing_marks DECIMAL(8,2) DEFAULT 18.00,
                negative_marking TINYINT DEFAULT 0,
                negative_mark_value DECIMAL(8,2) DEFAULT 0.25,
                allowed_warnings INT DEFAULT 3,
                auto_submit_on_violation TINYINT DEFAULT 1,
                camera_required TINYINT DEFAULT 1,
                fullscreen_required TINYINT DEFAULT 1,
                result_visibility VARCHAR(50) DEFAULT 'IMMEDIATE',
                start_time DATETIME NULL,
                end_time DATETIME NULL,
                is_published TINYINT DEFAULT 0,
                randomize_questions TINYINT DEFAULT 0,
                randomize_options TINYINT DEFAULT 0,
                total_questions_to_show INT NULL,
                easy_count INT DEFAULT 0,
                medium_count INT DEFAULT 0,
                hard_count INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # Add new columns if table already existed
        exam_cols = {
            "randomize_questions": "TINYINT DEFAULT 0",
            "randomize_options": "TINYINT DEFAULT 0",
            "total_questions_to_show": "INT NULL",
            "easy_count": "INT DEFAULT 0",
            "medium_count": "INT DEFAULT 0",
            "hard_count": "INT DEFAULT 0"
        }
        for col_n, col_t in exam_cols.items():
            try:
                cursor.execute(f"ALTER TABLE exams ADD COLUMN {col_n} {col_t}")
            except Exception:
                pass

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                question_text TEXT NOT NULL,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_answer VARCHAR(10) NOT NULL,
                marks DECIMAL(8,2) DEFAULT 1.00,
                negative_marks DECIMAL(8,2) DEFAULT 0.00,
                category VARCHAR(100) DEFAULT 'Aptitude',
                difficulty VARCHAR(50) DEFAULT 'Medium',
                explanation TEXT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_questions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                exam_id INT NOT NULL,
                question_id INT NOT NULL,
                question_order INT DEFAULT 1,
                INDEX (exam_id),
                INDEX (question_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_assignments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                exam_id INT NOT NULL,
                candidate_id INT NOT NULL,
                job_id VARCHAR(100) NULL,
                upload_id VARCHAR(100) NULL,
                assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(50) DEFAULT 'ASSIGNED',
                INDEX (exam_id),
                INDEX (candidate_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_attempts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                exam_id INT NOT NULL,
                candidate_id INT NOT NULL,
                user_id INT NOT NULL,
                job_id VARCHAR(100) NULL,
                upload_id VARCHAR(100) NULL,
                started_at DATETIME NULL,
                expires_at DATETIME NULL,
                submitted_at DATETIME NULL,
                status VARCHAR(50) DEFAULT 'NOT_STARTED',
                score DECIMAL(8,2) DEFAULT 0.00,
                percentage DECIMAL(5,2) DEFAULT 0.00,
                passed TINYINT DEFAULT 0,
                warning_count INT DEFAULT 0,
                last_activity DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX (exam_id),
                INDEX (candidate_id),
                INDEX (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attempt_answers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                attempt_id INT NOT NULL,
                question_id INT NOT NULL,
                selected_option VARCHAR(10) NULL,
                is_correct TINYINT DEFAULT 0,
                marks_awarded DECIMAL(8,2) DEFAULT 0.00,
                is_marked_for_review TINYINT DEFAULT 0,
                saved_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX (attempt_id),
                INDEX (question_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attempt_questions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                attempt_id INT NOT NULL,
                question_id INT NOT NULL,
                question_order INT DEFAULT 1,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_option VARCHAR(10) NOT NULL,
                INDEX (attempt_id),
                INDEX (question_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                attempt_id INT NOT NULL,
                exam_id INT NOT NULL,
                candidate_id INT NOT NULL,
                violation_type VARCHAR(100) NOT NULL,
                warning_number INT DEFAULT 1,
                details TEXT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX (attempt_id),
                INDEX (exam_id),
                INDEX (candidate_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        connection.commit()
        print("✅ Exam database schema initialized successfully.")
    except Exception as e:
        print("Notice during exam schema verification:", e)
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def ensure_interview_database_schema():
    """
    Creates the interviews table if not present.
    """
    connection = None
    cursor = None
    try:
        connection = get_connection()
        if not connection:
            return
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interviews (
                id INT AUTO_INCREMENT PRIMARY KEY,
                candidate_id INT NOT NULL,
                candidate_name VARCHAR(255) NOT NULL,
                candidate_email VARCHAR(255) NOT NULL,
                interviewer_name VARCHAR(255) NOT NULL,
                interviewer_email VARCHAR(255) NULL,
                interview_date DATE NOT NULL,
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                interview_type VARCHAR(100) DEFAULT 'Technical',
                location_link VARCHAR(512) NULL,
                status VARCHAR(50) DEFAULT 'Scheduled',
                notes TEXT NULL,
                created_by INT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX (candidate_id),
                INDEX (interview_date),
                INDEX (interviewer_name),
                INDEX (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        # Add columns if pre-existed with different schema
        interview_cols = {
            "candidate_id": "INT NOT NULL DEFAULT 0",
            "candidate_name": "VARCHAR(255) NOT NULL DEFAULT ''",
            "candidate_email": "VARCHAR(255) NOT NULL DEFAULT ''",
            "interviewer_name": "VARCHAR(255) NOT NULL DEFAULT ''",
            "interviewer_email": "VARCHAR(255) NULL",
            "interview_date": "DATE NOT NULL DEFAULT '2026-01-01'",
            "start_time": "TIME NOT NULL DEFAULT '10:00:00'",
            "end_time": "TIME NOT NULL DEFAULT '11:00:00'",
            "interview_type": "VARCHAR(100) DEFAULT 'Technical'",
            "location_link": "VARCHAR(512) NULL",
            "status": "VARCHAR(50) DEFAULT 'Scheduled'",
            "notes": "TEXT NULL",
            "reschedule_reason": "VARCHAR(255) NULL",
            "previous_schedule": "TEXT NULL",
            "rescheduled_at": "DATETIME NULL",
            "candidate_reschedule_reason": "VARCHAR(255) NULL",
            "candidate_preferred_date": "DATE NULL",
            "candidate_preferred_time": "VARCHAR(100) NULL",
            "candidate_reschedule_message": "TEXT NULL",
            "reschedule_requested_at": "DATETIME NULL",
            "created_by": "INT NULL",
            "updated_at": "DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
        }
        for col_name, col_def in interview_cols.items():
            try:
                cursor.execute(f"ALTER TABLE interviews ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass

        # Notifications Table for HR & Candidates
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                candidate_id INT NULL,
                recipient_role VARCHAR(50) NOT NULL,
                title VARCHAR(255) NOT NULL,
                message TEXT NOT NULL,
                link VARCHAR(512) NULL,
                notification_type VARCHAR(50) DEFAULT 'interview_rescheduled',
                is_read TINYINT(1) DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX (user_id),
                INDEX (candidate_id),
                INDEX (recipient_role),
                INDEX (is_read)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        connection.commit()
        print("✅ Interview and Notification database schema initialized successfully.")
    except Exception as e:
        print("Notice during interview schema verification:", e)
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# Execute schema verification on startup
try:
    ensure_database_schema()
    ensure_exam_database_schema()
    ensure_interview_database_schema()
except Exception as _schema_err:
    print("Schema check on startup notice:", _schema_err)


# ============================================================
# RESOLVE USER ID HELPER
# ============================================================

def resolve_user_id(job_id=None):
    """
    Resolves the current user's database ID from the session or
    associated background job information/database records.
    """
    if "user_id" in session:
        return session["user_id"]
    if job_id and job_id in AUTOMATION_JOBS:
        uid = AUTOMATION_JOBS[job_id].get("user_id")
        if uid:
            return uid
    if job_id:
        connection = None
        cursor = None
        try:
            connection = get_connection()
            cursor = connection.cursor()
            # First check automation_jobs table
            cursor.execute(
                "SELECT user_id FROM automation_jobs WHERE (job_code=%s OR upload_id=%s) AND user_id IS NOT NULL LIMIT 1",
                (job_id, job_id)
            )
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
            # Then check candidates hr_id or user_id
            cursor.execute(
                "SELECT COALESCE(hr_id, user_id) FROM candidates WHERE job_id=%s AND (hr_id IS NOT NULL OR user_id IS NOT NULL) LIMIT 1",
                (job_id,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
        except Exception as e:
            print("Error in resolve_user_id database lookup:", e)
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
    return None


def get_authenticated_hr_id():
    """
    Returns the user_id of the currently authenticated HR user.
    Returns None if user is not logged in or role is candidate.
    For admin users, returns session user_id so admins can perform administrative tasks.
    """
    if not session.get("logged_in"):
        return None
    user_role = str(session.get("role") or "").strip().lower()
    if user_role in ["hr", "admin"]:
        return session.get("user_id")
    return None


def verify_candidate_ownership(cursor, candidate_id, hr_id, is_admin=False):
    """
    Verifies that the candidate record belongs to the specified HR user.
    Admins are granted access to all records.
    Returns candidate dict if owned/authorized, or None if not found or unauthorized.
    """
    if not hr_id and not is_admin:
        return None
    if is_admin:
        cursor.execute("SELECT * FROM candidates WHERE id = %s LIMIT 1", (candidate_id,))
        return cursor.fetchone()

    cursor.execute(
        """
        SELECT * FROM candidates
        WHERE id = %s
          AND (
            hr_id = %s
            OR (job_id IS NOT NULL AND job_id IN (SELECT job_code FROM automation_jobs WHERE user_id = %s))
            OR (upload_id IS NOT NULL AND upload_id IN (SELECT upload_id FROM uploaded_files WHERE user_id = %s))
          )
        LIMIT 1
        """,
        (candidate_id, hr_id, hr_id, hr_id)
    )
    return cursor.fetchone()


def verify_exam_ownership(cursor, exam_id, hr_id, is_admin=False):
    """
    Verifies that the exam belongs to the specified HR user.
    Admins are granted access to all records.
    Returns exam dict if owned/authorized, or None if not found or unauthorized.
    """
    if not hr_id and not is_admin:
        return None
    if is_admin:
        cursor.execute("SELECT * FROM exams WHERE id = %s LIMIT 1", (exam_id,))
        return cursor.fetchone()
    cursor.execute("SELECT * FROM exams WHERE id = %s AND user_id = %s LIMIT 1", (exam_id, hr_id))
    return cursor.fetchone()


def verify_interview_ownership(cursor, interview_id, hr_id, is_admin=False):
    """
    Verifies that the interview was created by the specified HR user or belongs to their candidate.
    Admins are granted access to all records.
    Returns interview dict if owned/authorized, or None if not found or unauthorized.
    """
    if not hr_id and not is_admin:
        return None
    if is_admin:
        cursor.execute("SELECT * FROM interviews WHERE id = %s LIMIT 1", (interview_id,))
        return cursor.fetchone()
    cursor.execute("""
        SELECT * FROM interviews
        WHERE id = %s
          AND (
            created_by = %s
            OR candidate_id IN (SELECT id FROM candidates WHERE hr_id = %s OR (hr_id IS NULL AND user_id = %s))
          )
        LIMIT 1
    """, (interview_id, hr_id, hr_id, hr_id))
    return cursor.fetchone()


def verify_candidate_interview_ownership(cursor, interview_id, user_id, user_email):
    """
    Verifies that the interview belongs to the candidate with the given user_id or email.
    Returns interview dict if owned/authorized, or None if not found or unauthorized.
    """
    if not interview_id:
        return None
    cursor.execute("""
        SELECT * FROM interviews
        WHERE id = %s
          AND (
            candidate_email = %s
            OR candidate_id IN (SELECT id FROM candidates WHERE user_id = %s OR email = %s)
          )
        LIMIT 1
    """, (interview_id, user_email, user_id, user_email))
    return cursor.fetchone()


def verify_question_ownership(cursor, question_id, hr_id, is_admin=False):
    """
    Verifies that the question belongs to the specified HR user.
    Admins are granted access to all records.
    Returns question dict if owned/authorized, or None if not found or unauthorized.
    """
    if not hr_id and not is_admin:
        return None
    if is_admin:
        cursor.execute("SELECT * FROM questions WHERE id = %s LIMIT 1", (question_id,))
        return cursor.fetchone()
    cursor.execute("SELECT * FROM questions WHERE id = %s AND user_id = %s LIMIT 1", (question_id, hr_id))
    return cursor.fetchone()


def verify_job_ownership(cursor, job_code_or_upload_id, hr_id, is_admin=False):
    """
    Verifies that an automation job or uploaded batch belongs to the specified HR user.
    Admins are granted access to all records.
    Returns True if owned/authorized, False otherwise.
    """
    if not hr_id and not is_admin:
        return False
    if is_admin:
        return True
    cursor.execute(
        "SELECT id FROM automation_jobs WHERE (job_code = %s OR upload_id = %s OR id = %s) AND user_id = %s LIMIT 1",
        (job_code_or_upload_id, job_code_or_upload_id, job_code_or_upload_id, hr_id)
    )
    if cursor.fetchone():
        return True
    cursor.execute(
        "SELECT id FROM uploaded_files WHERE (upload_id = %s OR job_id = %s OR id = %s) AND user_id = %s LIMIT 1",
        (job_code_or_upload_id, job_code_or_upload_id, job_code_or_upload_id, hr_id)
    )
    return bool(cursor.fetchone())



# ============================================================
# PASSWORD VALIDATION
# ============================================================

def validate_password_strength(password):

    if len(password) < 8:
        return False

    if not re.search(r"[A-Z]", password):
        return False

    if not re.search(r"[a-z]", password):
        return False

    if not re.search(r"[0-9]", password):
        return False

    if not re.search(
        r"""[~!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?]""",
        password
    ):
        return False

    return True


# ============================================================
# FILE HELPER
# ============================================================

def allowed_file(filename, allowed_extensions):

    if not filename:
        return False

    if "." not in filename:
        return False

    extension = (
        filename
        .rsplit(".", 1)[1]
        .lower()
    )

    return extension in allowed_extensions


# ============================================================
# NORMALIZE EXCEL COLUMN
# ============================================================

def normalize_column_name(column):

    return re.sub(
        r"[^a-z0-9]",
        "",
        str(column).lower()
    )


# ============================================================
# GET CANDIDATE COLUMN
# ============================================================

def get_candidate_column(
    row,
    possible_names
):

    normalized_row = {}

    for key in row.keys():

        normalized_key = (
            normalize_column_name(key)
        )

        normalized_row[
            normalized_key
        ] = row[key]

    for name in possible_names:

        normalized_name = (
            normalize_column_name(name)
        )

        if normalized_name in normalized_row:

            value = normalized_row[
                normalized_name
            ]

            if pd.isna(value):
                return ""

            return str(value).strip()

    return ""


# ============================================================
# READ CANDIDATE EXCEL
# ============================================================

def read_candidate_excel(file_path):

    extension = (
        file_path
        .rsplit(".", 1)[1]
        .lower()
    )

    if extension == "csv":

        dataframe = pd.read_csv(
            file_path
        )

    elif extension == "xlsx":

        dataframe = pd.read_excel(
            file_path,
            engine="openpyxl"
        )

    else:

        dataframe = pd.read_excel(
            file_path
        )

    return dataframe


# ============================================================
# FIND MATCHING RESUME
# ============================================================

def find_matching_resume(
    candidate_id,
    candidate_name,
    candidate_email
):

    if not os.path.isdir(
        RESUME_FOLDER
    ):
        return None

    files = os.listdir(
        RESUME_FOLDER
    )

    if not files:
        return None

    name_clean = re.sub(
        r"[^a-z0-9]",
        "",
        str(candidate_name).lower()
    )

    email_clean = re.sub(
        r"[^a-z0-9]",
        "",
        str(candidate_email).lower()
    )

    id_clean = str(
        candidate_id
    ).lower()

    # --------------------------------------------------------
    # ID MATCH
    # --------------------------------------------------------

    for filename in files:

        filename_clean = re.sub(
            r"[^a-z0-9]",
            "",
            filename.lower()
        )

        if (
            id_clean
            and id_clean in filename_clean
        ):

            return filename

    # --------------------------------------------------------
    # EMAIL MATCH
    # --------------------------------------------------------

    if email_clean:

        email_search = (
            email_clean.split("gmail")[0]
        )

        if email_search:

            for filename in files:

                filename_clean = re.sub(
                    r"[^a-z0-9]",
                    "",
                    filename.lower()
                )

                if email_search in filename_clean:

                    return filename

    # --------------------------------------------------------
    # FULL NAME MATCH
    # --------------------------------------------------------

    if name_clean:

        for filename in files:

            filename_clean = re.sub(
                r"[^a-z0-9]",
                "",
                filename.lower()
            )

            if name_clean in filename_clean:

                return filename

    # --------------------------------------------------------
    # NAME WORD MATCH
    # --------------------------------------------------------

    name_words = [
        word
        for word in re.findall(
            r"[a-z0-9]+",
            str(candidate_name).lower()
        )
        if len(word) >= 3
    ]

    for filename in files:

        filename_lower = filename.lower()

        matches = 0

        for word in name_words:

            if word in filename_lower:
                matches += 1

        if matches >= 1:
            return filename

    return None


# ============================================================
# SPLASH
# ============================================================

@app.route("/")
def splash():
    try:
        return render_template("splash.html")
    except Exception:
        return redirect(url_for("login"))



# ============================================================
# ROLE AUTHORIZATION & FIRST LOGIN SECURITY MIDDLEWARE
# ============================================================

@app.before_request
def enforce_role_and_password_security():
    endpoint = request.endpoint
    path = request.path or ""

    unprotected_endpoints = {
        "login", "login_user", "register", "register_user",
        "forgot_password", "reset_password", "update_password",
        "change_password", "logout", "static", "splash",
        "candidate_login", "candidate_login_api",
        "candidate_setup_2fa", "candidate_verify_otp"
    }

    if not endpoint or endpoint in unprotected_endpoints or path.startswith("/static"):
        return None

    # 1. Force logged-in candidates/users with temporary passwords (must_change_password=1) to change password first
    if session.get("logged_in") and session.get("must_change_password"):
        user_role = str(session.get("role") or "").strip().lower()
        if user_role == "candidate":
            if not session.get("cand_otp_verified"):
                if endpoint not in ["candidate_setup_2fa", "candidate_verify_otp", "logout"]:
                    if request.is_json or path.startswith("/api/"):
                        return jsonify({
                            "success": False,
                            "must_change_password": True,
                            "otp_required": True,
                            "redirect_url": "/candidate/setup-2fa",
                            "message": "Google Authenticator OTP verification required."
                        }), 403
                    flash("Please set up Google Authenticator before changing your password.", "warning")
                    return redirect(url_for("candidate_setup_2fa"))
            else:
                if endpoint not in ["change_password", "logout"]:
                    if request.is_json or path.startswith("/api/"):
                        return jsonify({
                            "success": False,
                            "must_change_password": True,
                            "redirect_url": "/change-password",
                            "message": "Temporary password must be changed before continuing."
                        }), 403
                    flash("Please change your temporary password before accessing the portal.", "warning")
                    return redirect(url_for("change_password"))
        else:
            if endpoint not in ["change_password", "logout"]:
                if request.is_json or path.startswith("/api/"):
                    return jsonify({
                        "success": False,
                        "must_change_password": True,
                        "message": "Temporary password must be changed before continuing."
                    }), 403
                flash("Please change your temporary password before accessing the portal.", "warning")
                return redirect(url_for("change_password"))

    # 2. Candidate Role Access Protection (Prevent Candidates from accessing HR administrative routes/APIs)
    if session.get("logged_in") and str(session.get("role") or "").strip().lower() == "candidate":
        hr_only_routes = [
            "/home", "/candidates", "/resume-scanner", "/resume", "/analytics", "/hr-analytics",
            "/admin", "/api/automation", "/api/excel", "/api/resume-scanner", "/api/candidate/send-email",
            "/api/candidate/delete", "/api/candidates/delete"
        ]
        
        candidate_allowed = [
            "/candidate", "/api/candidate", "/api/candidates", "/change-password", "/logout",
            "/candidate/setup-2fa", "/candidate/verify-otp"
        ]

        is_hr_route = any(path == p or path.startswith(p + "/") or path.startswith(p + "?") for p in hr_only_routes)
        is_allowed = any(path == p or path.startswith(p + "/") for p in candidate_allowed)

        if is_hr_route and not is_allowed:
            if request.is_json or path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "message": "Access Denied: HR authorization required."
                }), 403
            flash("Access Denied: Candidate accounts do not have access to HR administration tools.", "error")
            return redirect(url_for("candidate_dashboard"))

    return None


# ============================================================
# LOGIN
# ============================================================

@app.route("/login")
def login():

    return render_template(
        "login.html"
    )


# ============================================================
# REGISTER
# ============================================================

@app.route("/register")
def register():

    return render_template(
        "register.html"
    )


# ============================================================
# FORGOT PASSWORD
# ============================================================

@app.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
def forgot_password():

    if request.method == "POST":
        return verify_authenticator()

    return render_template(
        "forgot_password.html"
    )


# ============================================================
# REGISTER USER
# ============================================================

@app.route(
    "/register-user",
    methods=["POST"]
)
def register_user():

    try:

        fullname = request.form.get(
            "fullname",
            ""
        ).strip()

        username = request.form.get(
            "username",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if (
            not fullname
            or len(fullname) < 2
            or not re.match(
                r"^[A-Za-z\s]+$",
                fullname
            )
        ):

            flash(
                "Full Name must contain only letters and spaces and be at least 2 characters",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if (
            not username
            or len(username) < 3
            or " " in username
            or not re.match(
                r"^[A-Za-z0-9_]+$",
                username
            )
        ):

            flash(
                "Username must be at least 3 characters and contain no spaces",
                "error"
            )

            return redirect(
                url_for("register")
            )

        email_pattern = (
            r"^[a-zA-Z0-9_.+-]+@"
            r"[a-zA-Z0-9-]+\."
            r"[a-zA-Z0-9-.]+$"
        )

        if (
            not email
            or not re.match(
                email_pattern,
                email
            )
        ):

            flash(
                "Invalid email format",
                "error"
            )

            return redirect(
                url_for("register")
            )

        phone_pattern = (
            r"^\+?[0-9\s\-()]{7,15}$"
        )

        if (
            not phone
            or not re.match(
                phone_pattern,
                phone
            )
        ):

            flash(
                "Invalid phone number format",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if password != confirm_password:

            flash(
                "Passwords do not match",
                "error"
            )

            return redirect(
                url_for("register")
            )

        if not validate_password_strength(
            password
        ):

            flash(
                "Password must contain uppercase, lowercase, number and special character",
                "error"
            )

            return redirect(
                url_for("register")
            )

        connection = get_connection()

        if connection is None:

            flash(
                "Database connection failed",
                "error"
            )

            return redirect(
                url_for("register")
            )

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE username=%s
            """,
            (username,)
        )

        if cursor.fetchone():

            cursor.close()
            connection.close()

            flash(
                "Username already exists",
                "error"
            )

            return redirect(
                url_for("register")
            )

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE email=%s
            """,
            (email,)
        )

        if cursor.fetchone():

            cursor.close()
            connection.close()

            flash(
                "Email already exists",
                "error"
            )

            return redirect(
                url_for("register")
            )

        hashed_password = (
            bcrypt
            .generate_password_hash(
                password
            )
            .decode("utf-8")
        )

        secret = pyotp.random_base32()

        totp = pyotp.TOTP(
            secret
        )

        qr_uri = totp.provisioning_uri(
            name=email,
            issuer_name=APP_NAME
        )

        filename = (
            f"{secure_filename(username)}.png"
        )

        qr_path = os.path.join(
            QR_CODE_FOLDER,
            filename
        )

        qr = qrcode.make(
            qr_uri
        )

        qr.save(
            qr_path
        )

        cursor.execute(
            """
            INSERT INTO users
            (
                fullname,
                username,
                email,
                phone,
                password,
                totp_secret,
                role
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'hr'
            )
            """,
            (
                fullname,
                username,
                email,
                phone,
                hashed_password,
                secret
            )
        )

        connection.commit()

        cursor.close()
        connection.close()

        session["qr_code"] = filename

        flash(
            "Registration Successful. Please scan QR code.",
            "success"
        )

        return redirect(
            url_for("show_qr")
        )

    except Exception as e:

        print(
            "REGISTER ERROR:",
            e
        )

        flash(
            "Registration failed",
            "error"
        )

        return redirect(
            url_for("register")
        )


# ============================================================
# SHOW QR
# ============================================================

@app.route("/show-qr")
def show_qr():

    if "qr_code" not in session:

        return redirect(
            url_for("register")
        )

    return render_template(
        "show_qr.html",
        qr_image=session["qr_code"]
    )


# ============================================================
# LOGIN USER
# ============================================================

@app.route(
    "/login-user",
    methods=["POST"]
)
def login_user():

    try:
        is_json_req = request.is_json or (request.headers.get("X-Requested-With") == "XMLHttpRequest") or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)
        if request.is_json:
            json_data = request.get_json(silent=True) or {}
            user_input = str(json_data.get("username") or json_data.get("email") or "").strip()
            password = str(json_data.get("password") or "")
        else:
            user_input = (request.form.get("username") or request.form.get("email") or "").strip()
            password = request.form.get("password", "")

        if not user_input or not password:
            if is_json_req:
                return jsonify({"success": False, "message": "Invalid email or password"}), 400
            flash("Invalid email or password", "error")
            return redirect(url_for("login"))

        # ----------------------------------------------------
        # ADMIN AUTHENTICATION CHECK (Backend .env Credentials)
        # ----------------------------------------------------
        env_admin_email = (ADMIN_EMAIL or os.getenv("ADMIN_EMAIL", "admin@company.com")).strip().lower()
        env_admin_password = (ADMIN_PASSWORD or os.getenv("ADMIN_PASSWORD", "admin_secret_pass"))

        if env_admin_email and user_input.lower() == env_admin_email:
            if password == env_admin_password:
                session["logged_in"] = True
                session["is_admin"] = True
                session["role"] = "admin"
                session["username"] = "admin"
                session["fullname"] = "Administrator"

                logger.info(
                    "LOGIN ATTEMPT username=%s user_found=true account_active=true role=ADMIN password_match=true authentication=SUCCESS redirect=ADMIN_DASHBOARD",
                    user_input
                )
                if is_json_req:
                    return jsonify({"success": True, "role": "ADMIN", "redirect_url": "/admin/dashboard"})
                flash("Admin Login Successful", "success")
                return redirect(url_for("admin_dashboard"))
            else:
                logger.info(
                    "LOGIN ATTEMPT username=%s user_found=true account_active=true role=ADMIN password_match=false authentication=FAILED redirect=NONE",
                    user_input
                )
                if is_json_req:
                    return jsonify({"success": False, "message": "Invalid email or password"}), 401
                flash("Invalid email or password", "error")
                return redirect(url_for("login"))

        # ----------------------------------------------------
        # UNIFIED USER AUTHENTICATION & ROLE DETERMINATION (DATABASE)
        # ----------------------------------------------------
        connection = get_connection()
        if connection is None:
            if is_json_req:
                return jsonify({"success": False, "message": "Database connection failed"}), 500
            flash("Database connection failed", "error")
            return redirect(url_for("login"))

        cursor = connection.cursor(dictionary=True)
        user_input_clean = user_input.strip()

        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE username=%s
               OR email=%s
               OR LOWER(username)=LOWER(%s)
               OR LOWER(email)=LOWER(%s)
            LIMIT 1
            """,
            (user_input_clean, user_input_clean, user_input_clean, user_input_clean)
        )

        user = cursor.fetchone()
        if user:
            user_role = str(user.get("role") or "hr").strip().lower()
            pw_match = bcrypt.check_password_hash(user["password"], password)
            must_change_pw = bool(user.get("must_change_password"))

            redirect_target = "CHANGE_PASSWORD" if (pw_match and must_change_pw) else ("CANDIDATE_DASHBOARD" if (pw_match and user_role == "candidate") else ("ADMIN_DASHBOARD" if (pw_match and user_role == "admin") else "HR_DASHBOARD"))

            logger.info(
                "LOGIN ATTEMPT username=%s user_found=true account_active=true role=%s password_match=%s authentication=%s redirect=%s",
                user_input, user_role.upper(), pw_match, "SUCCESS" if pw_match else "FAILED", redirect_target
            )

            if pw_match:
                session["logged_in"] = True
                session["is_admin"] = (user_role == "admin")
                session["role"] = user_role
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["email"] = user.get("email") or user["username"]
                session["fullname"] = user["fullname"]
                session["must_change_password"] = must_change_pw

                if user_role == "candidate" and must_change_pw:
                    totp_secret = user.get("totp_secret")
                    if not totp_secret:
                        totp_secret = pyotp.random_base32()
                        up_cur = connection.cursor()
                        up_cur.execute("UPDATE users SET totp_secret = %s WHERE id = %s", (totp_secret, user["id"]))
                        connection.commit()
                        up_cur.close()
                    totp = pyotp.TOTP(totp_secret)
                    qr_uri = totp.provisioning_uri(name=user.get("email") or user["username"], issuer_name=APP_NAME)
                    filename = f"cand_qr_{user['id']}_{secure_filename(user['username'])}.png"
                    qr_path = os.path.join(QR_CODE_FOLDER, filename)
                    qr = qrcode.make(qr_uri)
                    qr.save(qr_path)
                    session["cand_qr_code"] = filename
                    session["cand_otp_verified"] = False

                cursor.close()
                connection.close()

                if user_role == "candidate" and must_change_pw:
                    dest_url = "/candidate/setup-2fa"
                elif must_change_pw:
                    dest_url = "/change-password"
                elif user_role == "candidate":
                    dest_url = "/candidate/dashboard"
                elif user_role == "admin":
                    dest_url = "/admin/dashboard"
                else:
                    dest_url = "/home"

                if is_json_req:
                    return jsonify({
                        "success": True,
                        "role": "CANDIDATE" if user_role == "candidate" else user_role.upper(),
                        "must_change_password": must_change_pw,
                        "redirect_url": dest_url
                    })

                if user_role == "candidate" and must_change_pw:
                    flash("Please set up Google Authenticator and enter OTP before changing your password.", "warning")
                    return redirect(url_for("candidate_setup_2fa"))

                if must_change_pw:
                    flash("Please change your temporary password after your first login.", "warning")
                    return redirect(url_for("change_password"))

                flash("Login Successful", "success")
                if user_role == "candidate":
                    return redirect(url_for("candidate_dashboard"))
                elif user_role == "admin":
                    return redirect(url_for("admin_dashboard"))
                else:
                    return redirect(url_for("home"))
            else:
                cursor.close()
                connection.close()
                if is_json_req:
                    return jsonify({"success": False, "message": "Invalid email or password"}), 401
                flash("Invalid email or password", "error")
                return redirect(url_for("login"))

        logger.info(
            "LOGIN ATTEMPT username=%s user_found=false account_active=false role=UNKNOWN password_match=false authentication=FAILED redirect=NONE",
            user_input
        )

        # Fallback check on candidates table
        cursor.execute(
            "SELECT id, name, email, phone, position FROM candidates WHERE email=%s LIMIT 1",
            (user_input_clean,)
        )
        candidate = cursor.fetchone()
        cursor.close()
        connection.close()

        if candidate:
            expected_password = str(candidate["id"])
            if password == expected_password or password == candidate["email"]:
                session["logged_in"] = True
                session["is_admin"] = False
                session["role"] = "candidate"
                session["user_id"] = candidate["id"]
                session["candidate_id"] = candidate["id"]
                session["username"] = candidate["email"]
                session["email"] = candidate["email"]
                session["fullname"] = candidate["name"]
                session["must_change_password"] = False

                if is_json_req:
                    return jsonify({"success": True, "role": "CANDIDATE", "must_change_password": False, "redirect_url": "/candidate/dashboard"})

                flash("Login Successful", "success")
                return redirect(url_for("candidate_dashboard"))

        if is_json_req:
            return jsonify({"success": False, "message": "Invalid email or password"}), 401

        flash("Invalid email or password", "error")
        return redirect(url_for("login"))

    except Exception as e:
        print("LOGIN ERROR:", e)
        if request.is_json:
            return jsonify({"success": False, "message": f"Login Failed: {str(e)}"}), 500
        flash("Login Failed", "error")
        return redirect(url_for("login"))


# ============================================================
# ADMIN AUTHENTICATION HELPER & ROUTES
# ============================================================

def is_admin_authenticated():
    return session.get("logged_in") is True and session.get("is_admin") is True


@app.route("/admin")
@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_admin_authenticated():
        flash(
            "Admin access required. Please login as Administrator.",
            "error"
        )
        return redirect(url_for("login"))

    connection = None
    cursor = None
    hr_users = []
    try:
        connection = get_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, fullname, username, email, phone, created_at
                FROM users
                WHERE LOWER(role) = 'hr'
                ORDER BY id DESC
                """
            )
            hr_users = cursor.fetchall() or []
    except Exception as e:
        print("Notice fetching HR users for admin:", e)
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return render_template(
        "admin.html",
        hr_users=hr_users
    )


@app.route("/admin/hr", methods=["GET"])
def admin_get_hr_users():
    if not is_admin_authenticated():
        return jsonify({
            "success": False,
            "status": "failed",
            "message": "Forbidden - Admin access required"
        }), 403

    connection = None
    cursor = None
    try:
        connection = get_connection()
        if connection is None:
            return jsonify({
                "success": False,
                "message": "Database connection failed"
            }), 500

        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, fullname, username, email, phone, created_at
            FROM users
            WHERE LOWER(role) = 'hr'
            ORDER BY id DESC
            """
        )
        hr_users = cursor.fetchall() or []

        return jsonify({
            "success": True,
            "status": "success",
            "hr_users": hr_users,
            "count": len(hr_users)
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/admin/hr/<int:user_id>", methods=["DELETE", "POST"])
@app.route("/admin/hr/delete/<int:user_id>", methods=["DELETE", "POST"])
def admin_delete_hr_user(user_id):
    if not is_admin_authenticated():
        return jsonify({
            "success": False,
            "status": "failed",
            "message": "Forbidden - Admin access required"
        }), 403

    connection = None
    cursor = None
    try:
        connection = get_connection()
        if connection is None:
            return jsonify({
                "success": False,
                "message": "Database connection failed"
            }), 500

        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT id, fullname, email FROM users WHERE id=%s AND LOWER(role) = 'hr' LIMIT 1",
            (user_id,)
        )
        user = cursor.fetchone()

        if not user:
            return jsonify({
                "success": False,
                "message": f"HR User #{user_id} not found"
            }), 404

        try:
            cursor.execute(
                "UPDATE candidates SET user_id=NULL, hr_id=NULL WHERE user_id=%s OR hr_id=%s",
                (user_id, user_id)
            )
        except Exception as e_cand:
            print("Notice updating candidate records before HR deletion:", e_cand)

        cursor.execute(
            "DELETE FROM users WHERE id=%s",
            (user_id,)
        )
        connection.commit()

        print(f"🔒 ADMIN ACTION: HR User #{user_id} ({user.get('email')}) deleted successfully.")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({
                "success": True,
                "status": "success",
                "message": f"HR user '{user.get('fullname')}' deleted successfully",
                "deleted_id": user_id
            })

        flash(
            f"HR user '{user.get('fullname')}' deleted successfully.",
            "success"
        )
        return redirect(url_for("admin_dashboard"))

    except Exception as e:
        if connection:
            connection.rollback()
        print("ADMIN DELETE HR ERROR:", e)
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ============================================================
# HOME
# ============================================================

@app.route("/home")
def home():

    if "logged_in" not in session:

        flash(
            "Please login first",
            "error"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "home.html",
        fullname=session.get("fullname"),
        username=session.get("username")
    )


# ============================================================
# CANDIDATES PAGE
# ============================================================

@app.route("/candidates")
def candidates():

    if "logged_in" not in session:

        flash(
            "Please login first",
            "error"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "candidates.html",
        fullname=session.get("fullname"),
        username=session.get("username")
    )


# ============================================================
# RESUME SCANNER PAGE
# ============================================================

@app.route("/resume-scanner")
@app.route("/resume")
def resume_scanner():

    if "logged_in" not in session:

        flash(
            "Please login first",
            "error"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "resume_scanner.html",
        fullname=session.get("fullname"),
        username=session.get("username")
    )


# ============================================================
# HR ANALYTICS PAGE
# ============================================================

@app.route("/analytics")
@app.route("/hr-analytics")
def analytics():

    if "logged_in" not in session:

        flash(
            "Please login first",
            "error"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "analytics.html",
        fullname=session.get("fullname"),
        username=session.get("username")
    )


# ============================================================
# CANDIDATE REGISTRATION PAGE
# ============================================================

# ============================================================
# CANDIDATE REGISTRATION PAGE
# ============================================================

@app.route("/candidate/register", methods=["GET", "POST"], strict_slashes=False)
@app.route("/candidates/register", methods=["GET", "POST"], strict_slashes=False)
def candidate_register():

    if request.method == "POST":

        connection = None
        cursor = None

        try:
            if request.is_json:
                json_data = request.get_json(silent=True) or {}
                name = str(json_data.get("name", "")).strip()
                email = str(json_data.get("email", "")).strip()
                phone = str(json_data.get("phone", "")).strip()
                position = str(json_data.get("position", "")).strip()
                job_id = str(json_data.get("job_id", "")).strip() or request.args.get("job_id", "").strip()
            else:
                name = request.form.get("name", "").strip()
                email = request.form.get("email", "").strip()
                phone = request.form.get("phone", "").strip()
                position = request.form.get("position", "").strip()
                job_id = request.form.get("job_id", "").strip() or request.args.get("job_id", "").strip()

            print("========================================")
            print("CANDIDATE REGISTRATION POST RECEIVED:")
            print(f"Name:     '{name}'")
            print(f"Email:    '{email}'")
            print(f"Phone:    '{phone}'")
            print(f"Position: '{position}'")
            print(f"Job ID:   '{job_id}'")
            print(f"Files:    {list(request.files.keys())}")
            print("========================================")

            if not name or not email or not phone or not position:
                print("❌ Missing required registration fields")
                flash("Name, email, phone and position are required", "error")
                return render_template(
                    "candidate_register.html",
                    job_id=job_id
                )

            email_pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
            if not re.match(email_pattern, email):
                print(f"❌ Invalid email format: {email}")
                flash("Invalid email address", "error")
                return render_template(
                    "candidate_register.html",
                    job_id=job_id
                )

            connection = get_connection()
            if connection is None:
                print("❌ Database connection failed during registration")
                flash("Database connection failed", "error")
                return render_template(
                    "candidate_register.html",
                    job_id=job_id
                )

            cursor = connection.cursor(dictionary=True)
            current_user_id = resolve_user_id(job_id)

            # Check if email exists for this HR
            cursor.execute(
                "SELECT id, resume, resume_filename FROM candidates WHERE email=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s)) LIMIT 1",
                (email, current_user_id, current_user_id)
            )

            existing = cursor.fetchone()
            candidate_id = None

            if existing:
                candidate_id = existing["id"]
                cursor.execute(
                    """
                    UPDATE candidates
                    SET name=%s, phone=%s, position=%s, registration_status=%s,
                        processed_at=%s, job_id=COALESCE(%s, job_id), hr_id=COALESCE(hr_id, %s)
                    WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                    """,
                    (name, phone, position, "Registered", datetime.now(), job_id or None, current_user_id, candidate_id, current_user_id, current_user_id)
                )
                print(f"🔄 Updated existing candidate #{candidate_id} ({name})")
            else:
                cursor.execute(
                    """
                    INSERT INTO candidates
                    (name, email, phone, position, resume, resume_filename, resume_status,
                     registration_status, automation_status, status, created_at, processed_at,
                     email_status, job_id, user_id, hr_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (name, email, phone, position, None, None, "Not Uploaded",
                     "Registered", "Pending", "New", datetime.now(), datetime.now(),
                     "Not Sent", job_id or None, current_user_id, current_user_id)
                )
                candidate_id = cursor.lastrowid
                print(f"✅ Created new candidate #{candidate_id} ({name})")

            # Save uploaded resume if provided
            resume_file = request.files.get("resume")
            resume_uploaded = False
            stored_resume_name = None

            if resume_file and resume_file.filename:
                if allowed_file(resume_file.filename, ALLOWED_RESUME_FILES):
                    original_filename = secure_filename(resume_file.filename)
                    extension = ""
                    if "." in original_filename:
                        extension = "." + original_filename.rsplit(".", 1)[1].lower()

                    unique_filename = f"candidate_{candidate_id}_{int(datetime.now().timestamp())}{extension}"
                    resume_path = (Path(RESUME_FOLDER) / unique_filename).resolve()

                    resume_file.save(str(resume_path))

                    # Also copy as original filename in uploads/resumes for direct access
                    if original_filename:
                        orig_path = (Path(RESUME_FOLDER) / original_filename).resolve()
                        if not orig_path.is_file():
                            try:
                                import shutil
                                shutil.copyfile(str(resume_path), str(orig_path))
                            except Exception:
                                pass

                    if resume_path.is_file() and resume_path.stat().st_size > 0:
                        file_size_bytes = resume_path.stat().st_size
                        stored_resume_name = original_filename
                        print(f"========================================")
                        print(f"RESUME SAVED FOR CANDIDATE #{candidate_id}")
                        print(f"Original Filename: {original_filename}")
                        print(f"Stored Filename:   {unique_filename}")
                        print(f"File Size:         {file_size_bytes} bytes")
                        print(f"========================================")
                        cursor.execute(
                            """
                            UPDATE candidates
                            SET resume=%s,
                                resume_filename=%s,
                                resume_status=%s,
                                registration_status=%s,
                                status=%s,
                                automation_status=%s,
                                processed_at=%s,
                                job_id=COALESCE(%s, job_id)
                            WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                            """,
                            (
                                unique_filename,
                                original_filename,
                                "Uploaded",
                                "Registered",
                                "Processed",
                                "Processed",
                                datetime.now(),
                                job_id or None,
                                candidate_id,
                                current_user_id,
                                current_user_id
                            )
                        )
                        resume_uploaded = True
                    else:
                        cursor.execute(
                            """
                            UPDATE candidates
                            SET resume_status=%s,
                                registration_status=%s,
                                status=%s,
                                automation_status=%s,
                                processed_at=%s,
                                job_id=COALESCE(%s, job_id)
                            WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                            """,
                            (
                                "Upload Failed",
                                "Registered",
                                "Resume Pending",
                                "Resume Pending",
                                datetime.now(),
                                job_id or None,
                                candidate_id,
                                current_user_id,
                                current_user_id
                            )
                        )
                else:
                    cursor.execute(
                        """
                        UPDATE candidates
                        SET resume_status=%s,
                            registration_status=%s,
                            status=%s,
                            automation_status=%s,
                            processed_at=%s,
                            job_id=COALESCE(%s, job_id)
                        WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                        """,
                        (
                            "Upload Failed",
                            "Registered",
                            "Resume Pending",
                            "Resume Pending",
                            datetime.now(),
                            job_id or None,
                            candidate_id,
                            current_user_id,
                            current_user_id
                        )
                    )
            else:
                # Check if matching resume exists on disk in uploads/resumes
                matched_resume = find_matching_resume(candidate_id, name, email)
                if matched_resume and (Path(RESUME_FOLDER) / matched_resume).is_file():
                    stored_resume_name = matched_resume
                    cursor.execute(
                        """
                        UPDATE candidates
                        SET resume=%s,
                            resume_filename=%s,
                            resume_status='Uploaded',
                            registration_status='Registered',
                            status='Processed',
                            automation_status='Processed',
                            processed_at=%s,
                            job_id=COALESCE(%s, job_id)
                        WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                        """,
                        (
                            matched_resume,
                            matched_resume,
                            datetime.now(),
                            job_id or None,
                            candidate_id,
                            current_user_id,
                            current_user_id
                        )
                    )
                    resume_uploaded = True
                    print(f"✅ Auto-linked existing resume '{matched_resume}' for candidate #{candidate_id}")
                elif existing and existing.get("resume") and (Path(RESUME_FOLDER) / str(existing["resume"])).is_file():
                    cursor.execute(
                        """
                        UPDATE candidates
                        SET resume_status=%s,
                            registration_status=%s,
                            status=%s,
                            automation_status=%s,
                            processed_at=%s,
                            job_id=COALESCE(%s, job_id)
                        WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                        """,
                        (
                            "Uploaded",
                            "Registered",
                            "Processed",
                            "Processed",
                            datetime.now(),
                            job_id or None,
                            candidate_id,
                            current_user_id,
                            current_user_id
                        )
                    )
                    resume_uploaded = True
                else:
                    cursor.execute(
                        """
                        UPDATE candidates
                        SET resume_status=%s,
                            registration_status=%s,
                            status=%s,
                            automation_status=%s,
                            processed_at=%s,
                            job_id=COALESCE(%s, job_id)
                        WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                        """,
                        (
                            "Not Uploaded",
                            "Registered",
                            "Resume Pending",
                            "Resume Pending",
                            datetime.now(),
                            job_id or None,
                            candidate_id,
                            current_user_id,
                            current_user_id
                        )
                    )

            # Ensure candidate account exists in users table with role = 'candidate'
            cand_username = None
            is_new_cand_user = False
            try:
                cursor.execute("SELECT id, username, role FROM users WHERE email=%s LIMIT 1", (email,))
                cand_user = cursor.fetchone()
                if not cand_user:
                    cand_username = generate_unique_username(email, cursor)
                    totp_sec = pyotp.random_base32()
                    cursor.execute(
                        "INSERT INTO users (fullname, username, email, phone, password, role, must_change_password, google_authenticator_configured, totp_secret) VALUES (%s, %s, %s, %s, %s, 'candidate', 1, 0, %s)",
                        (name, cand_username, email, phone, hashed_pw, totp_sec)
                    )
                    connection.commit()
                    cand_user_id = cursor.lastrowid
                    cursor.execute("UPDATE candidates SET user_id=%s WHERE id=%s", (cand_user_id, candidate_id))
                    connection.commit()
                    is_new_cand_user = True
                elif str(cand_user.get("role") or "").strip().lower() != "candidate":
                    cursor.execute("UPDATE users SET role='candidate' WHERE id=%s", (cand_user["id"],))
                    connection.commit()
                    cand_username = cand_user["username"]
                else:
                    cand_username = cand_user["username"]
            except Exception as e_c_usr:
                print("Notice managing candidate user account in candidate_register:", e_c_usr)

            logger.info(
                "AUTOMATION CANDIDATE REGISTRATION job_id=%s upload_id=N/A candidate_email=%s username=%s user_created=%s candidate_created=true role=CANDIDATE password_hash_created=true account_enabled=true",
                job_id or "N/A", email, cand_username or extract_username_from_email(email), is_new_cand_user
            )

            connection.commit()
            print(f"🎉 Candidate #{candidate_id} registration successfully committed.")

            # Automated SMTP Email Sending Step
            email_result = send_candidate_confirmation_email({
                "name": name,
                "email": email,
                "position": position
            })
            email_status_val = "Sent" if email_result.get("success") else "Failed"

            try:
                cursor.execute(
                    "UPDATE candidates SET email_status=%s WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))",
                    (email_status_val, candidate_id, current_user_id, current_user_id)
                )
                connection.commit()
            except Exception as e_email_db:
                print("Notice updating email_status in DB:", e_email_db)

            # If client requested JSON response
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
                return jsonify({
                    "success": True,
                    "candidate_id": candidate_id,
                    "name": name,
                    "email": email,
                    "registration": "success",
                    "registration_status": "Registered",
                    "resume_upload": "success" if resume_uploaded else "failed",
                    "resume_status": "Uploaded" if resume_uploaded else "Not Uploaded",
                    "resume_filename": stored_resume_name,
                    "email": "success" if email_result.get("success") else "failed",
                    "email_status": email_status_val,
                    "email_message": email_result.get("message", ""),
                    "status": "Processed" if resume_uploaded else "Resume Pending",
                    "message": "Candidate registered successfully"
                }), 200


            return render_template(
                "candidate_register.html",
                success=True,
                candidate_id=candidate_id,
                name=name,
                email=email,
                job_id=job_id,
                resume_uploaded=resume_uploaded
            )

        except Exception as e:
            if connection:
                connection.rollback()

            print("CANDIDATE REGISTER FORM ERROR:", e)
            import traceback
            traceback.print_exc()

            flash(f"Registration failed: {str(e)}", "error")

            return render_template(
                "candidate_register.html",
                job_id=job_id
            )

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    return render_template(
        "candidate_register.html",
        job_id=request.args.get("job_id", "").strip()
    )



# ============================================================
# CANDIDATE REGISTRATION API
# ============================================================

@app.route(
    "/api/candidate/register",
    methods=["POST"]
)
def candidate_register_api():

    connection = None
    cursor = None

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({
                "success": False,
                "message":
                    "No candidate data received"
            }), 400

        name = str(
            data.get("name", "")
        ).strip()

        email = str(
            data.get("email", "")
        ).strip()

        phone = str(
            data.get("phone", "")
        ).strip()

        position = str(
            data.get("position", "")
        ).strip()

        if (
            not name
            or not email
            or not phone
            or not position
        ):

            return jsonify({
                "success": False,
                "message":
                    "Name, email, phone and position are required"
            }), 400

        email_pattern = (
            r"^[a-zA-Z0-9_.+-]+@"
            r"[a-zA-Z0-9-]+\."
            r"[a-zA-Z0-9-.]+$"
        )

        if not re.match(
            email_pattern,
            email
        ):

            return jsonify({
                "success": False,
                "message":
                    "Invalid email address"
            }), 400

        connection = get_connection()

        if connection is None:

            return jsonify({
                "success": False,
                "message":
                    "Database connection failed"
            }), 500

        cursor = connection.cursor(
            dictionary=True
        )

        job_id = str(data.get("job_id", "")).strip() or None
        current_user_id = resolve_user_id(job_id)

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                phone,
                position,
                resume,
                status
            FROM candidates
            WHERE email=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
            LIMIT 1
            """,
            (email, current_user_id, current_user_id)
        )

        existing = cursor.fetchone()

        if existing:

            candidate_id = existing["id"]

            cursor.execute(
                """
                UPDATE candidates
                SET
                    name=%s,
                    phone=%s,
                    position=%s,
                    status=%s,
                    hr_id=COALESCE(hr_id, %s)
                WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                """,
                (
                    name,
                    phone,
                    position,
                    "Registered",
                    current_user_id,
                    candidate_id,
                    current_user_id,
                    current_user_id
                )
            )

            connection.commit()

            return jsonify({
                "success": True,
                "message":
                    "Candidate information updated",
                "candidate_id":
                    candidate_id,
                "username":
                    email,
                "password":
                    str(candidate_id)
            })

        cursor.execute(
            """
            INSERT INTO candidates
            (
                name,
                email,
                phone,
                position,
                resume,
                status,
                created_at,
                email_status,
                job_id,
                user_id,
                hr_id
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                name,
                email,
                phone,
                position,
                None,
                "Registered",
                datetime.now(),
                "Not Sent",
                job_id,
                current_user_id,
                current_user_id
            )
        )

        connection.commit()
        candidate_id = cursor.lastrowid

        # Automated SMTP Email Sending Step
        email_result = send_candidate_confirmation_email({
            "name": name,
            "email": email,
            "position": position
        })
        email_status_val = "Sent" if email_result.get("success") else "Failed"

        try:
            cursor.execute(
                "UPDATE candidates SET email_status=%s WHERE id=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))",
                (email_status_val, candidate_id, current_user_id, current_user_id)
            )
            connection.commit()
        except Exception as e_email_db:
            print("Notice updating email_status in DB:", e_email_db)

        return jsonify({
            "success": True,
            "message": "Candidate registered successfully",
            "candidate_id": candidate_id,
            "registration": "success",
            "resume_upload": "success" if (existing and existing.get("resume")) else "pending",
            "email": "success" if email_result.get("success") else "failed",
            "email_status": email_status_val,
            "email_message": email_result.get("message", ""),
            "username": email,
            "password": str(candidate_id)
        })


    except Exception as e:

        if connection:
            connection.rollback()

        print(
            "CANDIDATE REGISTER ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================================
# API CANDIDATE SEND EMAIL (TRIGGER SMTP CONFIRMATION)
# ============================================================

@app.route("/api/candidate/send-email/<int:candidate_id>", methods=["POST"])
def api_candidate_send_email(candidate_id):
    auth_hr_id = get_authenticated_hr_id()
    if not auth_hr_id:
        return jsonify({"success": False, "email": "failed", "message": "Unauthorized"}), 401

    is_admin = session.get("role") == "admin"
    connection = None
    cursor = None
    try:
        connection = get_connection()
        if connection is None:
            return jsonify({
                "success": False,
                "email": "failed",
                "message": "Database connection failed"
            }), 500

        cursor = connection.cursor(dictionary=True)
        candidate = verify_candidate_ownership(cursor, candidate_id, auth_hr_id, is_admin=is_admin)

        if not candidate:
            return jsonify({
                "success": False,
                "email": "failed",
                "message": f"Candidate #{candidate_id} not found or access denied"
            }), 403

        email_result = send_candidate_confirmation_email(candidate)
        email_status_val = "Sent" if email_result.get("success") else "Failed"

        cursor.execute(
            "UPDATE candidates SET email_status=%s WHERE id=%s",
            (email_status_val, candidate_id)
        )
        connection.commit()

        return jsonify({
            "status": "success" if email_result.get("success") else "failed",
            "success": email_result.get("success", False),
            "candidate_id": candidate_id,
            "registration": "success",
            "email": "success" if email_result.get("success") else "failed",
            "email_status": email_status_val,
            "message": email_result.get("message", "")
        })

    except Exception as e:
        if connection:
            connection.rollback()
        return jsonify({
            "status": "failed",
            "success": False,
            "email": "failed",
            "message": str(e)
        }), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ============================================================
# API SEND EMAIL (GENERIC SECURE SMTP SENDER)
# Accepts candidate_id, to_email, subject, message
# Password remains backend-only in .env
# ============================================================

@app.route("/api/send-email", methods=["POST"])
@app.route("/api/email/send", methods=["POST"])
def api_send_email():
    auth_hr_id = get_authenticated_hr_id()
    is_admin = session.get("role") == "admin"
    connection = None
    cursor = None
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = request.form.to_dict()

        candidate_id = data.get("candidate_id") or data.get("id")
        to_email = str(data.get("to_email") or data.get("email") or data.get("to") or "").strip()
        subject = str(data.get("subject") or "Application Confirmation").strip()
        message = str(data.get("message") or data.get("body") or data.get("text") or "Your application has been successfully registered.").strip()

        candidate = None
        if candidate_id:
            try:
                candidate_id = int(candidate_id)
                connection = get_connection()
                if connection:
                    cursor = connection.cursor(dictionary=True)
                    candidate = verify_candidate_ownership(cursor, candidate_id, auth_hr_id, is_admin=is_admin)
                    if not candidate and auth_hr_id:
                        return jsonify({"status": "failed", "success": False, "message": f"Candidate #{candidate_id} not found or access denied"}), 403
            except Exception as e_db:
                print("Notice fetching candidate in api_send_email:", e_db)

        if candidate and not to_email:
            to_email = str(candidate.get("email") or "").strip()

        if not to_email:
            return jsonify({
                "status": "failed",
                "success": False,
                "message": "Recipient email address ('to_email') is required."
            }), 400

        # Send email via SMTP service (loads backend .env credentials safely)
        if candidate:
            email_result = send_candidate_confirmation_email(
                candidate_data=candidate,
                subject=subject,
                message=message
            )
        else:
            email_result = send_smtp_email(
                to_email=to_email,
                subject=subject,
                body_text=message
            )

        email_success = email_result.get("success", False)
        email_status_val = "Sent" if email_success else "Failed"

        if candidate_id:
            try:
                if not connection:
                    connection = get_connection()
                if connection:
                    if not cursor:
                        cursor = connection.cursor(dictionary=True)
                    cursor.execute(
                        "UPDATE candidates SET email_status=%s WHERE id=%s",
                        (email_status_val, candidate_id)
                    )
                    connection.commit()
            except Exception as e_up:
                print("Notice updating candidate email_status in DB:", e_up)

        status_str = "success" if email_success else "failed"
        return jsonify({
            "status": status_str,
            "success": email_success,
            "email_status": email_status_val,
            "message": email_result.get("message", "Email processed successfully")
        }), (200 if email_success else 400)

    except Exception as e:
        print("API SEND EMAIL ERROR:", e)
        return jsonify({
            "status": "failed",
            "success": False,
            "message": str(e)
        }), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/api/send-email-excel", methods=["POST"])
@app.route("/api/excel/send-emails", methods=["POST"])
def api_send_email_excel():
    """
    API endpoint to read uploaded Excel (.xlsx, .xls) and CSV (.csv) files,
    extract recipient email addresses, validate them, remove cross-file duplicates, and send SMTP emails to each recipient.
    """
    try:
        files = request.files.getlist("files") or request.files.getlist("file") or request.files.getlist("excel_file") or request.files.getlist("candidate_files")
        if not files or not any(f and f.filename for f in files):
            single_f = request.files.get("file") or request.files.get("excel_file") or request.files.get("candidate_file")
            files = [single_f] if single_f and single_f.filename else []

        subject = request.form.get("subject") or "Application Notification"
        body_text = request.form.get("message") or request.form.get("body") or "Thank you for your interest."
        body_html = request.form.get("html")

        if not files and request.is_json:
            json_data = request.get_json(silent=True) or {}
            excel_path = json_data.get("excel_path") or json_data.get("file_path") or json_data.get("files")
            subject = json_data.get("subject") or subject
            body_text = json_data.get("message") or json_data.get("body") or body_text
            body_html = json_data.get("html")
            if excel_path:
                files = excel_path if isinstance(excel_path, list) else [excel_path]

        if not files:
            return jsonify({
                "status": "failed",
                "success": False,
                "message": "No Excel or CSV files provided in request."
            }), 400

        res = process_multi_file_email_batch(
            file_sources=files,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            user_id=session.get("user_id"),
            base_url=request.host_url
        )
        status_code = 200 if res.get("success") else 400
        return jsonify(res), status_code
    except Exception as e:
        print("API SEND EMAIL EXCEL ERROR:", e)
        return jsonify({
            "status": "failed",
            "success": False,
            "message": str(e)
        }), 500



# ============================================================
# CANDIDATE LOGIN (REDIRECT TO UNIFIED LOGIN PAGE)
# ============================================================

@app.route("/candidate/login")
def candidate_login():

    return redirect(url_for("login"))


# ============================================================
# CANDIDATE DASHBOARD ROUTE & API
# ============================================================

@app.route("/candidate/dashboard")
@app.route("/candidate")
def candidate_dashboard():
    if "logged_in" not in session:
        flash("Please login first", "error")
        return redirect(url_for("login"))

    if session.get("must_change_password"):
        flash("Please change your temporary password before accessing your dashboard.", "warning")
        return redirect(url_for("change_password"))

    user_id = session.get("user_id")
    user_email = session.get("email") or session.get("username")

    connection = get_connection()
    cand_data = None
    user_data = None
    assigned_exams = []

    if connection:
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE id = %s OR email = %s OR username = %s LIMIT 1", (user_id, user_email, user_email))
            user_data = cursor.fetchone()

            cursor.execute("SELECT * FROM candidates WHERE user_id = %s OR email = %s LIMIT 1", (user_id, user_email))
            cand_data = cursor.fetchone()

            cand_id = cand_data["id"] if cand_data else None
            job_id = cand_data.get("job_id") if cand_data else None
            upload_id = cand_data.get("upload_id") if cand_data else None

            # Query assigned published exams
            query = """
                SELECT DISTINCT ex.*
                FROM exams ex
                JOIN exam_assignments ea ON ex.id = ea.exam_id
                WHERE ex.is_published = 1 AND (
                    ea.candidate_id = %s OR
                    (ea.job_id IS NOT NULL AND ea.job_id = %s) OR
                    (ea.upload_id IS NOT NULL AND ea.upload_id = %s)
                )
            """
            cursor.execute(query, (cand_id or -1, job_id or '-1', upload_id or '-1'))
            exams_raw = cursor.fetchall()

            for ex in exams_raw:
                # Check current attempt status for candidate
                cursor.execute("""
                    SELECT * FROM exam_attempts
                    WHERE exam_id = %s AND (candidate_id = %s OR user_id = %s)
                    ORDER BY id DESC LIMIT 1
                """, (ex["id"], cand_id or -1, user_id or -1))
                att = cursor.fetchone()

                ex["attempt_status"] = att["status"] if att else "NOT_STARTED"
                ex["attempt_id"] = att["id"] if att else None
                assigned_exams.append(ex)

            # Query candidate scheduled interviews
            scheduled_interviews = []
            try:
                cand_email = cand_data.get("email") if cand_data else user_email
                cursor.execute("""
                    SELECT id, candidate_id, candidate_name, candidate_email, interviewer_name, interviewer_email,
                           DATE_FORMAT(interview_date, '%Y-%m-%d') as interview_date,
                           TIME_FORMAT(start_time, '%H:%i') as start_time,
                           TIME_FORMAT(end_time, '%H:%i') as end_time,
                           interview_type, location_link, status, notes,
                           reschedule_reason, previous_schedule,
                           candidate_reschedule_reason,
                           DATE_FORMAT(candidate_preferred_date, '%Y-%m-%d') as candidate_preferred_date,
                           candidate_preferred_time, candidate_reschedule_message,
                           DATE_FORMAT(reschedule_requested_at, '%b %d, %Y %h:%i %p') as reschedule_requested_at_formatted,
                           DATE_FORMAT(rescheduled_at, '%b %d, %Y %h:%i %p') as rescheduled_at_formatted,
                           DATE_FORMAT(updated_at, '%b %d, %Y %h:%i %p') as updated_at_formatted,
                           DATE_FORMAT(created_at, '%b %d, %Y %h:%i %p') as created_at_formatted
                    FROM interviews
                    WHERE (candidate_id IS NOT NULL AND candidate_id = %s) OR candidate_email = %s
                    ORDER BY interview_date ASC, start_time ASC
                """, (cand_id or -1, cand_email or ''))
                scheduled_interviews = cursor.fetchall()
            except Exception as e_int:
                print("Notice fetching candidate interviews:", e_int)

            cursor.close()
            connection.close()
        except Exception as e_dash:
            print("Notice fetching candidate dashboard data:", e_dash)

    return render_template(
        "candidate_dashboard.html",
        user=user_data or {
            "fullname": session.get("fullname"),
            "username": session.get("username"),
            "email": session.get("email")
        },
        candidate=cand_data or {},
        assigned_exams=assigned_exams,
        scheduled_interviews=scheduled_interviews or []
    )


@app.route("/api/candidate/dashboard", methods=["GET"])
def api_candidate_dashboard():
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user_id = session.get("user_id")
    user_email = session.get("email") or session.get("username")

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, fullname, username, email, phone, role FROM users WHERE id = %s OR email = %s LIMIT 1", (user_id, user_email))
        user_rec = cursor.fetchone()

        cursor.execute("SELECT * FROM candidates WHERE user_id = %s OR email = %s LIMIT 1", (user_id, user_email))
        cand_rec = cursor.fetchone()
        cursor.close()
        connection.close()

        return jsonify({
            "success": True,
            "user": user_rec,
            "candidate": cand_rec
        })
    except Exception as err:
        return jsonify({"success": False, "message": str(err)}), 500


# ============================================================
# CANDIDATE LOGIN API
# ============================================================

@app.route(
    "/api/candidate/login",
    methods=["POST"]
)
def candidate_login_api():

    connection = None
    cursor = None

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({
                "success": False,
                "message":
                    "No login data received"
            }), 400

        username = str(
            data.get("username", "")
        ).strip()

        password = str(
            data.get("password", "")
        ).strip()

        if not username or not password:

            return jsonify({
                "success": False,
                "message":
                    "Username and password are required"
            }), 400

        connection = get_connection()

        if connection is None:

            return jsonify({
                "success": False,
                "message":
                    "Database connection failed"
            }), 500

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            "SELECT * FROM users WHERE username = %s OR email = %s LIMIT 1",
            (username, username)
        )
        user = cursor.fetchone()

        if user and bcrypt.check_password_hash(user["password"], password):
            user_role = str(user.get("role") or "candidate").strip().lower()
            must_change_pw = bool(user.get("must_change_password"))

            session["logged_in"] = True
            session["is_admin"] = (user_role == "admin")
            session["role"] = user_role
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["email"] = user.get("email") or user["username"]
            session["fullname"] = user["fullname"]
            session["must_change_password"] = must_change_pw

            if user_role == "candidate" and must_change_pw:
                totp_secret = user.get("totp_secret")
                if not totp_secret:
                    totp_secret = pyotp.random_base32()
                    up_cur = connection.cursor()
                    up_cur.execute("UPDATE users SET totp_secret = %s WHERE id = %s", (totp_secret, user["id"]))
                    connection.commit()
                    up_cur.close()
                totp = pyotp.TOTP(totp_secret)
                qr_uri = totp.provisioning_uri(name=user.get("email") or user["username"], issuer_name=APP_NAME)
                filename = f"cand_qr_{user['id']}_{secure_filename(user['username'])}.png"
                qr_path = os.path.join(QR_CODE_FOLDER, filename)
                qr = qrcode.make(qr_uri)
                qr.save(qr_path)
                session["cand_qr_code"] = filename
                session["cand_otp_verified"] = False
                dest_url = "/candidate/setup-2fa"
            elif must_change_pw:
                dest_url = "/change-password"
            elif user_role == "candidate":
                dest_url = "/candidate/dashboard"
            else:
                dest_url = "/home"

            cursor.close()
            connection.close()

            return jsonify({
                "success": True,
                "authenticated": True,
                "user_id": user["id"],
                "username": user["username"],
                "role": "CANDIDATE" if user_role == "candidate" else user_role.upper(),
                "must_change_password": must_change_pw,
                "redirect_url": dest_url
            })

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                phone,
                position,
                resume,
                status
            FROM candidates
            WHERE email=%s
            LIMIT 1
            """,
            (username,)
        )

        candidate = cursor.fetchone()

        if not candidate:

            return jsonify({
                "success": False,
                "message":
                    "Invalid username or password"
            }), 401

        expected_password = str(
            candidate["id"]
        )

        if password != expected_password and password != candidate["email"]:

            return jsonify({
                "success": False,
                "message":
                    "Invalid username or password"
            }), 401

        session["logged_in"] = True
        session["role"] = "candidate"
        session["user_id"] = candidate["id"]
        session["username"] = candidate["email"]
        session["email"] = candidate["email"]
        session["fullname"] = candidate["name"]
        session["must_change_password"] = False

        return jsonify({
            "success": True,
            "authenticated": True,
            "user_id": candidate["id"],
            "candidate_id": candidate["id"],
            "role": "CANDIDATE",
            "must_change_password": False,
            "redirect_url": "/candidate/dashboard",
            "candidate": candidate
        })

    except Exception as e:

        print(
            "CANDIDATE LOGIN ERROR:",
            e
        )

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()



# ============================================================
# CANDIDATE 2FA SETUP & OTP VERIFICATION ROUTES
# ============================================================

@app.route("/candidate/setup-2fa", methods=["GET"])
def candidate_setup_2fa():
    if not session.get("logged_in"):
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    user_role = str(session.get("role") or "").strip().lower()
    if user_role != "candidate":
        return redirect(url_for("home"))

    if not session.get("must_change_password"):
        return redirect(url_for("candidate_dashboard"))

    if session.get("cand_otp_verified"):
        return redirect(url_for("change_password"))

    user_id = session.get("user_id")
    qr_filename = session.get("cand_qr_code")

    if not qr_filename or not os.path.exists(os.path.join(QR_CODE_FOLDER, qr_filename)):
        connection = get_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT id, username, email, totp_secret FROM users WHERE id = %s LIMIT 1", (user_id,))
            u_rec = cursor.fetchone()
            if u_rec:
                secret = u_rec.get("totp_secret")
                if not secret:
                    secret = pyotp.random_base32()
                    u_cur = connection.cursor()
                    u_cur.execute("UPDATE users SET totp_secret = %s WHERE id = %s", (secret, user_id))
                    connection.commit()
                    u_cur.close()
                totp = pyotp.TOTP(secret)
                qr_uri = totp.provisioning_uri(name=u_rec.get("email") or u_rec["username"], issuer_name=APP_NAME)
                qr_filename = f"cand_qr_{user_id}_{secure_filename(u_rec['username'])}.png"
                qr_path = os.path.join(QR_CODE_FOLDER, qr_filename)
                qr = qrcode.make(qr_uri)
                qr.save(qr_path)
                session["cand_qr_code"] = qr_filename
            cursor.close()
            connection.close()

    return render_template("candidate_setup_2fa.html", qr_image=qr_filename)


@app.route("/candidate/verify-otp", methods=["POST"])
def candidate_verify_otp():
    if not session.get("logged_in"):
        if request.is_json:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    user_role = str(session.get("role") or "").strip().lower()
    if user_role != "candidate":
        if request.is_json:
            return jsonify({"success": False, "message": "Access Denied"}), 403
        return redirect(url_for("home"))

    is_json_req = request.is_json or (request.headers.get("X-Requested-With") == "XMLHttpRequest") or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)

    if request.is_json:
        data = request.get_json(silent=True) or {}
        otp_code = str(data.get("otp_code") or "").strip()
    else:
        otp_code = str(request.form.get("otp_code") or "").strip()

    if len(otp_code) != 6 or not otp_code.isdigit():
        if is_json_req:
            return jsonify({"success": False, "message": "Invalid OTP Code. Must be 6 digits."}), 400
        flash("Invalid OTP Code. Please enter the 6-digit code from Google Authenticator.", "error")
        return redirect(url_for("candidate_setup_2fa"))

    user_id = session.get("user_id")
    connection = get_connection()
    if not connection:
        if is_json_req:
            return jsonify({"success": False, "message": "Database connection failed"}), 500
        flash("Database connection failed", "error")
        return redirect(url_for("candidate_setup_2fa"))

    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT totp_secret FROM users WHERE id = %s LIMIT 1", (user_id,))
    user_rec = cursor.fetchone()
    cursor.close()
    connection.close()

    if not user_rec or not user_rec.get("totp_secret"):
        if is_json_req:
            return jsonify({"success": False, "message": "Authenticator secret not found."}), 400
        flash("Authenticator secret not found. Please try again.", "error")
        return redirect(url_for("candidate_setup_2fa"))

    totp = pyotp.TOTP(user_rec["totp_secret"])
    if totp.verify(otp_code, valid_window=1):
        session["cand_otp_verified"] = True
        logger.info("CANDIDATE 2FA OTP VERIFIED user_id=%s authentication=SUCCESS", user_id)
        if is_json_req:
            return jsonify({
                "success": True,
                "message": "OTP Verified Successfully",
                "redirect_url": "/change-password"
            })
        flash("Google Authenticator Verified Successfully! Please change your password.", "success")
        return redirect(url_for("change_password"))
    else:
        logger.info("CANDIDATE 2FA OTP VERIFIED user_id=%s authentication=FAILED", user_id)
        if is_json_req:
            return jsonify({"success": False, "message": "Invalid OTP Code. Please try again."}), 400
        flash("Invalid OTP Code. Please enter the correct code from Google Authenticator.", "error")
        return redirect(url_for("candidate_setup_2fa"))


# ============================================================
# GET CANDIDATES & EXAM RESULTS HELPER
# ============================================================

def attach_candidate_exam_data(cursor, candidate):
    cand_id = candidate["id"]
    cand_email = (candidate.get("email") or "").strip().lower()

    user_id = candidate.get("user_id")
    if not user_id and cand_email:
        cursor.execute("SELECT id FROM users WHERE LOWER(email) = %s LIMIT 1", (cand_email,))
        u_row = cursor.fetchone()
        if u_row:
            user_id = u_row["id"]
    
    candidate["user_id"] = user_id

    # 1. Query exam_attempts for this candidate
    cursor.execute("""
        SELECT 
            ea.id AS attempt_id,
            ea.exam_id,
            COALESCE(ex.title, 'Aptitude Exam') AS exam_title,
            COALESCE(ex.total_questions_to_show, 30) AS exam_total_questions,
            COALESCE(ex.total_marks, 30.00) AS exam_total_marks,
            COALESCE(ex.passing_marks, 18.00) AS exam_passing_marks,
            ea.started_at,
            ea.expires_at,
            ea.submitted_at,
            ea.status AS attempt_status,
            ea.score,
            ea.percentage,
            ea.passed,
            ea.warning_count,
            ea.job_id,
            ea.upload_id
        FROM exam_attempts ea
        LEFT JOIN exams ex ON ea.exam_id = ex.id
        WHERE ea.candidate_id = %s OR (ea.user_id = %s AND %s IS NOT NULL)
        ORDER BY ea.id DESC
    """, (cand_id, user_id, user_id))
    attempts = cursor.fetchall() or []

    # 2. Query exam_assignments for this candidate
    cursor.execute("""
        SELECT 
            asn.id AS assignment_id,
            asn.exam_id,
            COALESCE(ex.title, 'Aptitude Exam') AS exam_title,
            COALESCE(ex.total_questions_to_show, 30) AS exam_total_questions,
            COALESCE(ex.total_marks, 30.00) AS exam_total_marks,
            COALESCE(ex.passing_marks, 18.00) AS exam_passing_marks,
            asn.assigned_at,
            asn.status AS assignment_status,
            asn.job_id,
            asn.upload_id
        FROM exam_assignments asn
        LEFT JOIN exams ex ON asn.exam_id = ex.id
        WHERE asn.candidate_id = %s
        ORDER BY asn.id DESC
    """, (cand_id,))
    assignments = cursor.fetchall() or []

    exam_name = "No Exam Assigned"
    exam_status = "—"
    score_formatted = "—"
    result_status = "—"
    exam_id = None
    attempt_id = None

    exam_details = {
        "has_exam": False,
        "exam_id": None,
        "attempt_id": None,
        "exam_name": "No Exam Assigned",
        "attempt_status": "—",
        "started_at": "—",
        "submitted_at": "—",
        "total_questions": 0,
        "questions_answered": 0,
        "correct_answers": 0,
        "wrong_answers": 0,
        "unanswered": 0,
        "total_marks": 0.0,
        "obtained_marks": 0.0,
        "percentage": 0.0,
        "passing_percentage": 50.0,
        "result": "—",
        "warning_count": 0,
        "tab_switch_count": 0,
        "fullscreen_exit_count": 0,
        "attempts_count": len(attempts)
    }

    if attempts:
        att = attempts[0]
        exam_id = att["exam_id"]
        attempt_id = att["attempt_id"]
        exam_name = att["exam_title"] or "Aptitude Exam"

        raw_status = (att["attempt_status"] or "NOT_STARTED").upper()
        if raw_status in ("COMPLETED", "SUBMITTED"):
            exam_status = "Completed"
        elif raw_status == "AUTO_SUBMITTED":
            exam_status = "Auto Submitted"
        elif raw_status == "IN_PROGRESS":
            exam_status = "In Progress"
        elif raw_status in ("DISQUALIFIED", "FAILED"):
            exam_status = "Auto Submitted" if att.get("warning_count", 0) >= 3 else "Completed"
        else:
            exam_status = "Not Started"

        tot_q = int(att.get("exam_total_questions") or 30)
        tot_marks = float(att.get("exam_total_marks") or tot_q)
        pass_marks = float(att.get("exam_passing_marks") or 18.0)
        pass_pct = (pass_marks / tot_marks * 100.0) if tot_marks > 0 else 50.0

        obt_score = float(att.get("score") or 0.0)
        pct = float(att.get("percentage") or 0.0)

        q_answered = 0
        q_correct = 0
        q_wrong = 0
        q_unanswered = tot_q
        tab_switches = 0
        fs_exits = 0

        if attempt_id:
            cursor.execute("SELECT COUNT(*) as q_count FROM attempt_questions WHERE attempt_id = %s", (attempt_id,))
            q_snap = cursor.fetchone()
            if q_snap and q_snap["q_count"] > 0:
                tot_q = int(q_snap["q_count"])

            cursor.execute("""
                SELECT 
                    COUNT(*) as total_ans,
                    SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_cnt,
                    SUM(CASE WHEN selected_option IS NOT NULL AND selected_option != '' AND is_correct = 0 THEN 1 ELSE 0 END) as wrong_cnt
                FROM attempt_answers
                WHERE attempt_id = %s
            """, (attempt_id,))
            ans_row = cursor.fetchone()
            if ans_row:
                q_answered = int(ans_row.get("total_ans") or 0)
                q_correct = int(ans_row.get("correct_cnt") or 0)
                q_wrong = int(ans_row.get("wrong_cnt") or 0)
                q_unanswered = max(0, tot_q - q_answered)

            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN violation_type = 'TAB_SWITCH' THEN 1 ELSE 0 END) as tab_switches,
                    SUM(CASE WHEN violation_type = 'FULLSCREEN_EXIT' THEN 1 ELSE 0 END) as fs_exits
                FROM security_events
                WHERE attempt_id = %s
            """, (attempt_id,))
            sec_row = cursor.fetchone()
            if sec_row:
                tab_switches = int(sec_row.get("tab_switches") or 0)
                fs_exits = int(sec_row.get("fs_exits") or 0)

        is_passed = att.get("passed")
        if is_passed is None:
            is_passed = 1 if (pct >= pass_pct or obt_score >= pass_marks) else 0

        if exam_status in ("Completed", "Auto Submitted"):
            score_str = f"{int(obt_score)}" if obt_score.is_integer() else f"{obt_score:.1f}"
            score_formatted = f"{score_str}/{tot_q} ({int(pct)}%)"
            result_status = "Passed" if is_passed else "Failed"
        elif exam_status == "In Progress":
            score_formatted = "—"
            result_status = "In Progress"
        else: # Not Started
            score_formatted = "—"
            result_status = "Pending"

        exam_details.update({
            "has_exam": True,
            "exam_id": exam_id,
            "attempt_id": attempt_id,
            "exam_name": exam_name,
            "attempt_status": exam_status,
            "started_at": att["started_at"].strftime("%d %b %Y %H:%M") if att.get("started_at") else "—",
            "submitted_at": att["submitted_at"].strftime("%d %b %Y %H:%M") if att.get("submitted_at") else "—",
            "total_questions": tot_q,
            "questions_answered": q_answered,
            "correct_answers": q_correct,
            "wrong_answers": q_wrong,
            "unanswered": q_unanswered,
            "total_marks": tot_marks,
            "obtained_marks": obt_score,
            "percentage": pct,
            "passing_percentage": pass_pct,
            "result": result_status,
            "warning_count": att.get("warning_count", 0),
            "tab_switch_count": tab_switches,
            "fullscreen_exit_count": fs_exits
        })

    elif assignments:
        asn = assignments[0]
        exam_id = asn["exam_id"]
        exam_name = asn["exam_title"] or "Aptitude Exam"
        exam_status = "Not Started"
        score_formatted = "—"
        result_status = "Pending"

        tot_q = int(asn.get("exam_total_questions") or 30)
        tot_marks = float(asn.get("exam_total_marks") or tot_q)
        pass_marks = float(asn.get("exam_passing_marks") or 18.0)
        pass_pct = (pass_marks / tot_marks * 100.0) if tot_marks > 0 else 50.0

        exam_details.update({
            "has_exam": True,
            "exam_id": exam_id,
            "attempt_id": None,
            "exam_name": exam_name,
            "attempt_status": "Not Started",
            "total_questions": tot_q,
            "total_marks": tot_marks,
            "passing_percentage": pass_pct,
            "result": "Pending"
        })

    candidate["exam_name"] = exam_name
    candidate["exam_status"] = exam_status
    candidate["score_formatted"] = score_formatted
    candidate["result_status"] = result_status
    candidate["exam_id"] = exam_id
    candidate["attempt_id"] = attempt_id
    candidate["exam_details"] = exam_details
    return candidate


@app.route("/api/candidates", methods=["GET"])
def api_candidates():

    if "logged_in" not in session:

        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    connection = None
    cursor = None

    try:

        connection = get_connection()

        if connection is None:

            return jsonify({
                "success": False,
                "message": "Database connection failed"
            }), 500

        cursor = connection.cursor(dictionary=True)

        current_user_id = resolve_user_id()
        auth_hr_id = get_authenticated_hr_id()
        user_role = str(session.get("role") or "").strip().lower()
        is_admin = (user_role == "admin")

        job_id_param = (request.args.get("job_id") or request.args.get("jobId") or "").strip()
        upload_id_param = (request.args.get("upload_id") or request.args.get("uploadId") or "").strip()

        # If job_id or upload_id is omitted, check for the user's latest active job
        if not job_id_param and not upload_id_param and request.args.get("all") != "true" and user_role == "hr":
            try:
                conn_active = get_connection()
                if conn_active:
                    cur_active = conn_active.cursor(dictionary=True)
                    cur_active.execute(
                        "SELECT job_code, upload_id FROM automation_jobs WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                        (current_user_id,)
                    )
                    act_rec = cur_active.fetchone()
                    if act_rec:
                        job_id_param = act_rec.get("job_code") or ""
                        upload_id_param = act_rec.get("upload_id") or ""
                    cur_active.close()
                    conn_active.close()
            except Exception as e_act:
                print("Notice resolving active job for candidates list:", e_act)

        search_query = (request.args.get("search") or request.args.get("q") or "").strip().lower()
        is_all = request.args.get("all") == "true"

        where_clauses = []
        params = []

        if user_role == "candidate":
            user_email = session.get("email") or ""
            where_clauses.append("(user_id = %s OR email = %s)")
            params.extend([current_user_id, user_email])
        elif user_role == "hr":
            # HR data isolation: only candidates uploaded by or belonging to this HR
            where_clauses.append("""(
                hr_id = %s 
                OR (job_id IS NOT NULL AND job_id IN (SELECT job_code FROM automation_jobs WHERE user_id = %s))
                OR (upload_id IS NOT NULL AND upload_id IN (SELECT upload_id FROM uploaded_files WHERE user_id = %s))
            )""")
            params.extend([current_user_id, current_user_id, current_user_id])

            if job_id_param and not is_all:
                cursor.execute(
                    "SELECT id FROM automation_jobs WHERE (job_code = %s OR upload_id = %s) AND user_id = %s LIMIT 1",
                    (job_id_param, job_id_param, current_user_id)
                )
                job_check = cursor.fetchone()
                if not job_check:
                    # Also check uploaded_files
                    cursor.execute(
                        "SELECT id FROM uploaded_files WHERE (job_id = %s OR upload_id = %s) AND user_id = %s LIMIT 1",
                        (job_id_param, job_id_param, current_user_id)
                    )
                    job_check = cursor.fetchone()

                if job_check:
                    where_clauses.append("(job_id = %s OR upload_id = %s)")
                    params.extend([job_id_param, job_id_param])
                else:
                    # Foreign job_id requested by HR — do not leak foreign candidates!
                    cursor.close()
                    connection.close()
                    return jsonify({"success": True, "candidates": [], "count": 0})
            elif upload_id_param and not is_all:
                cursor.execute(
                    "SELECT id FROM uploaded_files WHERE (upload_id = %s OR job_id = %s) AND user_id = %s LIMIT 1",
                    (upload_id_param, upload_id_param, current_user_id)
                )
                if cursor.fetchone():
                    where_clauses.append("(upload_id = %s OR job_id = %s)")
                    params.extend([upload_id_param, upload_id_param])
                else:
                    cursor.close()
                    connection.close()
                    return jsonify({"success": True, "candidates": [], "count": 0})
        elif is_admin:
            if job_id_param and not is_all:
                where_clauses.append("(job_id = %s OR upload_id = %s)")
                params.extend([job_id_param, job_id_param])
            elif upload_id_param and not is_all:
                where_clauses.append("(upload_id = %s OR job_id = %s)")
                params.extend([upload_id_param, upload_id_param])

        if search_query:
            search_param = f"%{search_query}%"
            where_clauses.append("(LOWER(name) LIKE %s OR LOWER(email) LIKE %s OR LOWER(phone) LIKE %s OR LOWER(position) LIKE %s OR LOWER(COALESCE(status, '')) LIKE %s OR LOWER(COALESCE(registration_status, '')) LIKE %s OR LOWER(COALESCE(resume_status, '')) LIKE %s OR CAST(id AS CHAR) LIKE %s)")
            params.extend([search_param] * 8)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else "WHERE 1=1"

        cursor.execute(
            f"""
            SELECT
                id,
                name,
                email,
                phone,
                position,
                resume,
                resume_filename,
                COALESCE(resume_status, 'Not Uploaded') AS resume_status,
                COALESCE(registration_status, 'Registered') AS registration_status,
                COALESCE(automation_status, 'Pending') AS automation_status,
                status,
                created_at,
                processed_at,
                job_id,
                upload_id,
                user_id,
                hr_id,
                email_status,
                error_message
            FROM candidates
            {where_sql}
            ORDER BY id DESC
            """,
            tuple(params)
        )

        candidates_data = cursor.fetchall()

        for candidate in candidates_data:

            if isinstance(candidate.get("created_at"), datetime):
                candidate["created_at"] = candidate["created_at"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            elif candidate.get("created_at"):
                candidate["created_at"] = str(candidate["created_at"])

            if isinstance(candidate.get("processed_at"), datetime):
                candidate["processed_at_formatted"] = candidate["processed_at"].strftime(
                    "%d %b %Y %H:%M"
                )
                candidate["processed_at"] = candidate["processed_at"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            elif candidate.get("processed_at"):
                candidate["processed_at_formatted"] = str(candidate["processed_at"])
                candidate["processed_at"] = str(candidate["processed_at"])
            else:
                candidate["processed_at_formatted"] = "N/A"
                candidate["processed_at"] = None

            cand_res_file = candidate.get("resume") or candidate.get("resume_filename")
            if cand_res_file:
                phys_file = (Path(RESUME_FOLDER) / str(cand_res_file)).resolve()
                if phys_file.is_file() and phys_file.stat().st_size > 0:
                    candidate["resume_url"] = url_for(
                        "candidate_resume",
                        filename=cand_res_file
                    )
                    candidate["resume_status"] = "Uploaded"
                else:
                    candidate["resume_url"] = None
            else:
                candidate["resume_url"] = None

            # Attach exam status, score, result, and detailed metrics
            attach_candidate_exam_data(cursor, candidate)

        response = make_response(jsonify({
            "success": True,
            "count": len(candidates_data),
            "candidates": candidates_data
        }))
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    except Exception as e:
        print("GET CANDIDATES API ERROR:", e)
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@app.route("/api/candidates/<int:candidate_id>/details", methods=["GET"])
def api_candidate_details(candidate_id):
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database error"}), 500

    cursor = connection.cursor(dictionary=True)
    user_role = str(session.get("role") or "").strip().lower()
    is_admin = (user_role == "admin")

    if user_role == "candidate":
        cursor.execute("SELECT * FROM candidates WHERE id = %s LIMIT 1", (candidate_id,))
        cand = cursor.fetchone()
        if not cand:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Candidate not found"}), 404

        current_user_id = resolve_user_id()
        user_email = session.get("email") or ""

        cand_uid = str(cand.get("user_id") or "")
        cand_email = str(cand.get("email") or "").strip().lower()
        curr_uid = str(current_user_id or "")
        curr_email = str(user_email or "").strip().lower()

        is_owner = (curr_uid and cand_uid == curr_uid) or (curr_email and cand_email == curr_email)
        if not is_owner:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Access Denied: You cannot view another candidate's details."}), 403
    else:
        auth_hr_id = get_authenticated_hr_id()
        cand = verify_candidate_ownership(cursor, candidate_id, auth_hr_id, is_admin=is_admin)
        if not cand:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Access Denied: You cannot view another HR account's candidate details."}), 403

    attach_candidate_exam_data(cursor, cand)

    cursor.close()
    connection.close()
    response = make_response(jsonify({"success": True, "candidate": cand}))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response



# ============================================================
# INTERNAL EXCEL PROCESSOR
# ============================================================

def process_excel_into_database(
    excel_path,
    user_id=None
):

    dataframe = read_candidate_excel(
        excel_path
    )

    if dataframe.empty:

        return {
            "inserted": 0,
            "skipped": 0
        }

    connection = get_connection()

    if connection is None:
        raise Exception(
            "Database connection failed"
        )

    cursor = connection.cursor()

    inserted = 0
    skipped = 0

    try:

        for _, row in dataframe.iterrows():

            name = get_candidate_column(
                row,
                [
                    "name",
                    "candidate name",
                    "full name"
                ]
            )

            email = get_candidate_column(
                row,
                [
                    "email",
                    "email address",
                    "candidate email"
                ]
            )

            phone = get_candidate_column(
                row,
                [
                    "phone",
                    "phone number",
                    "mobile",
                    "mobile number"
                ]
            )

            position = get_candidate_column(
                row,
                [
                    "position",
                    "job position",
                    "role",
                    "job role",
                    "applied position"
                ]
            )

            if (
                not name
                or not email
                or not phone
                or not position
            ):

                skipped += 1
                continue

            cursor.execute(
                """
                SELECT id
                FROM candidates
                WHERE email=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s))
                LIMIT 1
                """,
                (email, user_id, user_id)
            )

            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE candidates
                    SET name=%s, phone=%s, position=%s, hr_id=COALESCE(hr_id, %s)
                    WHERE id=%s
                    """,
                    (name, phone, position, user_id, existing[0])
                )
                skipped += 1
                continue

            cursor.execute(
                """
                INSERT INTO candidates
                (
                    name,
                    email,
                    phone,
                    position,
                    resume,
                    resume_filename,
                    resume_status,
                    registration_status,
                    automation_status,
                    status,
                    created_at,
                    email_status,
                    user_id,
                    hr_id
                )
                VALUES
                (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    name,
                    email,
                    phone,
                    position,
                    None,
                    None,
                    "Not Uploaded",
                    "Pending",
                    "Pending",
                    "New",
                    datetime.now(),
                    "Not Sent",
                    user_id,
                    user_id
                )
            )

            inserted += 1

        connection.commit()

        return {
            "inserted": inserted,
            "skipped": skipped
        }

    except Exception:

        connection.rollback()

        raise

    finally:

        cursor.close()
        connection.close()


# ============================================================
# AUTOMATION UPLOAD
#
# ONE EXCEL + MULTIPLE RESUMES
# ============================================================

# ============================================================
# AUTOMATION UPLOAD
#
# ONE EXCEL + MULTIPLE RESUMES
# ============================================================

@app.route(
    "/api/automation/upload",
    methods=["POST"]
)
def automation_upload():

    if "logged_in" not in session:

        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    try:

        # ====================================================
        # MULTI-FILE EXCEL / CSV PROCESSING
        # ====================================================
        candidate_files = (
            request.files.getlist("candidate_files") or
            request.files.getlist("candidate_file") or
            request.files.getlist("files")
        )
        if not candidate_files or not any(f and f.filename for f in candidate_files):
            single_f = request.files.get("candidate_file")
            candidate_files = [single_f] if single_f and single_f.filename else []

        if not candidate_files:
            return jsonify({
                "success": False,
                "message": "Candidate Excel/CSV file was not provided."
            }), 400

        saved_candidate_files = []
        saved_unique_paths = []
        user_id = session.get("user_id")
        timestamp_prefix = int(time.time())
        rand_suffix = uuid.uuid4().hex[:6].upper()
        job_code = f"JOB-{timestamp_prefix}-{rand_suffix}"
        upload_id = f"UPLOAD-{timestamp_prefix}-{rand_suffix}"
        job_id = job_code

        connection = get_connection()
        cursor = connection.cursor(dictionary=True) if connection else None
        total_candidates_in_batch = 0

        for idx, candidate_file in enumerate(candidate_files, start=1):
            if not candidate_file or not candidate_file.filename:
                continue

            if not allowed_file(candidate_file.filename, ALLOWED_CANDIDATE_FILES):
                return jsonify({
                    "success": False,
                    "message": f"File '{candidate_file.filename}' is not allowed. Only CSV, XLS and XLSX files are allowed."
                }), 400

            original_filename = secure_filename(candidate_file.filename)
            extension = original_filename.rsplit(".", 1)[1].lower() if "." in original_filename else "xlsx"

            # Generate UNIQUE stored filename in job subfolder to NEVER overwrite older uploads!
            job_cand_dir = (Path(CANDIDATE_UPLOAD_FOLDER) / f"job_{job_id}").resolve()
            job_cand_dir.mkdir(parents=True, exist_ok=True)
            unique_stored_name = f"{timestamp_prefix}_{idx}_{original_filename}"
            unique_excel_path = str((job_cand_dir / unique_stored_name).resolve())

            # Save uploaded file
            candidate_file.save(unique_excel_path)
            saved_unique_paths.append(unique_excel_path)

            print("\nUPLOAD CREATED:")
            print(f"upload_id={upload_id}")
            print(f"filename={original_filename}")
            print(f"stored_path={unique_excel_path}")
            print(f"file_exists={Path(unique_excel_path).is_file()}\n")

            # Read DataFrame & detect email column
            try:
                if extension == "csv":
                    df = pd.read_csv(unique_excel_path)
                else:
                    try:
                        df = pd.read_excel(unique_excel_path, engine="openpyxl")
                    except Exception:
                        df = pd.read_excel(unique_excel_path)

                total_rows = len(df) if df is not None else 0
                total_candidates_in_batch += total_rows

                email_col, col_err = detect_email_column(df, filename=original_filename)
                if col_err or not email_col:
                    if cursor:
                        cursor.execute(
                            "INSERT INTO uploaded_files (upload_id, filename, filepath, file_type, status, total_count, created_at, job_id, user_id, error_message) VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)",
                            (upload_id, original_filename, unique_excel_path, extension, "Failed", total_rows, job_id, user_id, col_err)
                        )
                        connection.commit()
                    return jsonify({
                        "success": False,
                        "message": col_err
                    }), 400

            except Exception as read_err:
                return jsonify({
                    "success": False,
                    "message": f"Could not read uploaded file '{original_filename}': {str(read_err)}"
                }), 400

            # Register file in uploaded_files table
            if cursor:
                try:
                    cursor.execute(
                        "INSERT INTO uploaded_files (upload_id, filename, filepath, file_type, status, total_count, created_at, job_id, user_id) VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s)",
                        (upload_id, original_filename, unique_excel_path, extension, "Processing", total_rows, job_id, user_id)
                    )
                    connection.commit()
                except Exception as e_file_db:
                    print("Notice inserting into uploaded_files DB:", e_file_db)

            saved_candidate_files.append(original_filename)

        primary_input_file = saved_unique_paths[0] if saved_unique_paths else ""

        # Create record in automation_jobs table
        if cursor:
            try:
                cursor.execute(
                    "INSERT INTO automation_jobs (job_code, upload_id, user_id, job_name, status, total_files, total_candidates, input_file_path, created_at) VALUES (%s, %s, %s, %s, 'Uploaded', %s, %s, %s, NOW())",
                    (job_code, upload_id, user_id, f"Job {job_code}", len(saved_unique_paths), total_candidates_in_batch, primary_input_file)
                )
                connection.commit()
                print("\nJOB CREATED:")
                print(f"job_id={job_id}")
                print(f"upload_id={upload_id}")
                print(f"input_file={primary_input_file}\n")
            except Exception as e_job:
                print("Notice creating automation_jobs record:", e_job)

        if cursor:
            cursor.close()
        if connection:
            connection.close()

        # ====================================================
        # SAVE UPLOADED RESUMES INTO JOB-ISOLATED SUBFOLDER BEFORE PROCESSING
        # ====================================================
        job_resume_dir = (Path(RESUME_FOLDER) / f"job_{job_id}").resolve()
        job_resume_dir.mkdir(parents=True, exist_ok=True)

        resume_files = (
            request.files.getlist("resumes") or
            request.files.getlist("resume") or
            request.files.getlist("resume_files") or
            request.files.getlist("cv_files")
        )
        if not resume_files:
            single_r = request.files.get("resume") or request.files.get("resume_file")
            resume_files = [single_r] if single_r and single_r.filename else []

        saved_resumes = []
        for resume in resume_files:
            if not resume or not resume.filename:
                continue
            if not allowed_file(resume.filename, ALLOWED_RESUME_FILES):
                continue
            safe_name = secure_filename(resume.filename)
            if not safe_name:
                continue

            # Save to job-isolated subfolder
            resume_path = (job_resume_dir / safe_name).resolve()
            resume.save(str(resume_path))

            # Also save to root RESUME_FOLDER as fallback copy
            global_copy_path = (Path(RESUME_FOLDER) / safe_name).resolve()
            try:
                import shutil
                shutil.copyfile(str(resume_path), str(global_copy_path))
            except Exception:
                pass

            if resume_path.is_file() and resume_path.stat().st_size > 0:
                saved_resumes.append(safe_name)

        # Execute Multi-File Candidate Auto-Registration, Resume Detection & SMTP Email Dispatch for THIS JOB ONLY
        batch_summary = process_multi_file_email_batch(
            file_sources=saved_unique_paths,
            job_id=job_id,
            user_id=user_id,
            base_url=request.host_url,
            upload_id=upload_id
        )

        # Update uploaded_files statuses to Completed for this job
        try:
            conn_u = get_connection()
            if conn_u:
                cur_u = conn_u.cursor()
                for path_str in saved_unique_paths:
                    cur_u.execute("UPDATE uploaded_files SET status='Completed', processed_at=NOW() WHERE filepath=%s AND job_id=%s", (path_str, job_id))
                conn_u.commit()
                cur_u.close()
                conn_u.close()
        except Exception as u_up_err:
            print("Notice updating uploaded_files completed status:", u_up_err)

        return jsonify({
            "success": True,
            "message": "Candidate files and resumes processed successfully.",
            "upload_id": upload_id,
            "job_id": job_id,
            "job_code": job_code,
            "uploaded_files": saved_candidate_files,
            "uploaded_file": primary_input_file,
            "resume_count": len(saved_resumes),
            "resumes": saved_resumes,
            "batch_summary": batch_summary,
            "total_candidates": total_candidates_in_batch,
            "total_rows": batch_summary.get("total_rows", 0),
            "valid_emails": batch_summary.get("valid_emails", 0),
            "duplicate_emails": batch_summary.get("duplicate_emails", 0),
            "successfully_registered": batch_summary.get("successfully_registered", 0),
            "emails_sent": batch_summary.get("emails_sent", 0),
            "registration_failures": batch_summary.get("registration_failures", 0),
            "email_failures": batch_summary.get("email_failures", 0)
        })

    except Exception as e:

        print(
            "AUTOMATION UPLOAD ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "message":
                f"Automation upload failed: {str(e)}"

        }), 500


# ============================================================
# RETRY / RESUME AUTOMATION BATCH
# ============================================================

@app.route("/api/automation/retry", methods=["POST"])
def api_automation_retry():
    """
    Resumes or retries candidate processing for a given job_id or upload_id.
    Strictly uses the specified job's file.
    """
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    user_id = session.get("user_id")

    if not job_id:
        return jsonify({"success": False, "message": "job_id parameter is required for retry"}), 400

    conn = get_connection()
    if not conn:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cur = conn.cursor(dictionary=True)
        is_admin = session.get("role") == "admin"
        if not verify_job_ownership(cur, job_id, user_id, is_admin=is_admin):
            cur.close()
            conn.close()
            return jsonify({"success": False, "message": f"Access Denied: You do not have permission to retry job '{job_id}'"}), 403

        cur.execute("SELECT filepath FROM uploaded_files WHERE job_id = %s OR upload_id = %s", (job_id, job_id))
        records = cur.fetchall()
        cur.close()
        conn.close()

        file_paths = [r["filepath"] for r in records if r.get("filepath") and Path(r["filepath"]).is_file()]
        if not file_paths:
            return jsonify({"success": False, "message": f"No valid uploaded files found for job_id '{job_id}'"}), 404

        summary = process_multi_file_email_batch(
            file_sources=file_paths,
            job_id=job_id,
            user_id=user_id,
            base_url=request.host_url
        )

        return jsonify({
            "success": True,
            "message": f"Retry executed for job {job_id}",
            "summary": summary
        })

    except Exception as e:
        return jsonify({"success": False, "message": f"Retry failed: {str(e)}"}), 500


# ============================================================
# RPA AUTOMATION ENGINE (ROBOT FRAMEWORK & SELENIUM)
# ============================================================

@app.route("/api/automation/start", methods=["POST"])
def api_automation_start():
    if "logged_in" not in session:
        return jsonify({
            "success": False,
            "status": "FAILED",
            "message": "Unauthorized"
        }), 401

    data = request.get_json(silent=True) or {}
    user_id_for_job = session.get("user_id")

    client_job_id = (data.get("job_id") or data.get("jobId") or "").strip()
    client_upload_id = (data.get("upload_id") or data.get("uploadId") or "").strip()
    client_excel = (data.get("excel_file") or data.get("candidate_file") or "").strip()

    excel_path = None
    target_job_id = client_job_id
    upload_id = client_upload_id
    total_candidates = 0

    # 1. Direct explicit file path if passed and valid
    if client_excel and Path(client_excel).is_file():
        excel_path = str(Path(client_excel).resolve())
    elif client_excel:
        p_direct = Path(client_excel).resolve()
        p_in_upload = (Path(CANDIDATE_UPLOAD_FOLDER) / client_excel).resolve()
        if p_direct.is_file():
            excel_path = str(p_direct)
        elif p_in_upload.is_file():
            excel_path = str(p_in_upload)

    # 2. If target_job_id is provided, load job record from automation_jobs / uploaded_files
    if target_job_id:
        try:
            conn = get_connection()
            if conn:
                cur = conn.cursor(dictionary=True)
                is_admin = session.get("role") == "admin"
                if not verify_job_ownership(cur, target_job_id, user_id_for_job, is_admin=is_admin):
                    cur.close()
                    conn.close()
                    return jsonify({
                        "success": False,
                        "status": "FAILED",
                        "message": f"Access Denied: You do not have permission to run automation for job '{target_job_id}'"
                    }), 403

                cur.execute(
                    "SELECT input_file_path, upload_id, total_candidates FROM automation_jobs WHERE job_code = %s OR id = %s LIMIT 1",
                    (target_job_id, target_job_id)
                )
                j_rec = cur.fetchone()
                if j_rec:
                    if not excel_path and j_rec.get("input_file_path") and Path(j_rec["input_file_path"]).is_file():
                        excel_path = j_rec["input_file_path"]
                    if not upload_id and j_rec.get("upload_id"):
                        upload_id = j_rec["upload_id"]
                    if j_rec.get("total_candidates"):
                        total_candidates = j_rec["total_candidates"]

                if not excel_path:
                    cur.execute(
                        "SELECT filepath, upload_id FROM uploaded_files WHERE job_id = %s OR upload_id = %s ORDER BY id DESC LIMIT 1",
                        (target_job_id, target_job_id)
                    )
                    u_rec = cur.fetchone()
                    if u_rec and u_rec.get("filepath") and Path(u_rec["filepath"]).is_file():
                        excel_path = u_rec["filepath"]
                        if not upload_id:
                            upload_id = u_rec.get("upload_id")

                cur.close()
                conn.close()
        except Exception as e_q:
            print("Notice querying database for job_id:", e_q)

    # 3. If target_job_id was not provided, look up the latest job for the logged in user
    if not excel_path and not target_job_id and user_id_for_job:
        try:
            conn = get_connection()
            if conn:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT job_code, upload_id, input_file_path, total_candidates FROM automation_jobs WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                    (user_id_for_job,)
                )
                j_latest = cur.fetchone()
                if j_latest:
                    if j_latest.get("input_file_path") and Path(j_latest["input_file_path"]).is_file():
                        excel_path = j_latest["input_file_path"]
                    target_job_id = j_latest.get("job_code") or target_job_id
                    upload_id = j_latest.get("upload_id") or upload_id
                    if j_latest.get("total_candidates"):
                        total_candidates = j_latest["total_candidates"]

                if not excel_path:
                    cur.execute(
                        "SELECT filepath, job_id, upload_id FROM uploaded_files WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                        (user_id_for_job,)
                    )
                    rec = cur.fetchone()
                    if rec and rec.get("filepath") and Path(rec["filepath"]).is_file():
                        excel_path = rec["filepath"]
                        if not target_job_id and rec.get("job_id"):
                            target_job_id = rec["job_id"]
                        if not upload_id and rec.get("upload_id"):
                            upload_id = rec.get("upload_id")

                cur.close()
                conn.close()
        except Exception as e_u:
            print("Notice querying latest job for user:", e_u)

    job_id = target_job_id if target_job_id else "-"

    # Pre-flight strict validation: job_id, upload_id, input file existence, file extension
    valid_ext = excel_path and any(excel_path.lower().endswith(ext) for ext in [".csv", ".xlsx", ".xls"])
    if not excel_path or not Path(excel_path).is_file() or not valid_ext:
        return jsonify({
            "success": False,
            "status": "FAILED",
            "job_id": job_id,
            "jobId": job_id,
            "upload_id": upload_id or "-",
            "stage": "Validation Failed",
            "last_successful_step": "Pre-flight input validation",
            "failure_reason": "Candidate upload file not found for this job. Please upload a CSV or Excel file first.",
            "message": "Candidate upload file not found for this job. Please upload a CSV or Excel file first."
        }), 400

    # Read and verify file records count
    try:
        if str(excel_path).lower().endswith(".csv"):
            dataframe = pd.read_csv(excel_path)
        else:
            try:
                dataframe = pd.read_excel(excel_path, engine="openpyxl")
            except Exception:
                dataframe = pd.read_excel(excel_path)

        if dataframe is None or dataframe.empty:
            return jsonify({
                "success": False,
                "status": "FAILED",
                "job_id": job_id,
                "jobId": job_id,
                "upload_id": upload_id or "-",
                "stage": "Validation Failed",
                "last_successful_step": "Parsing candidate file records",
                "failure_reason": "Candidate file contains no records.",
                "message": "Candidate file contains no records."
            }), 400

        total_candidates = len(dataframe)
    except Exception as e:
        return jsonify({
            "success": False,
            "status": "FAILED",
            "job_id": job_id,
            "jobId": job_id,
            "upload_id": upload_id or "-",
            "stage": "Validation Failed",
            "last_successful_step": "Reading candidate file",
            "failure_reason": f"Could not read candidate file: {str(e)}",
            "message": f"Could not read candidate file: {str(e)}"
        }), 400

    registration_url = data.get(
        "registration_url",
        "/candidate/register"
    )

    browser_mode = data.get("browser_mode", "").strip().lower()
    if browser_mode not in ["headless", "visible"]:
        browser_mode = DEFAULT_BROWSER_MODE
        if browser_mode not in ["headless", "visible"]:
            browser_mode = "headless"

    job_resume_dir = str((Path(RESUME_FOLDER) / f"job_{job_id}").resolve())

    # Required Debug Log Output
    print("\nSTARTING AUTOMATION")
    print(f"job_id={job_id}")
    print(f"upload_id={upload_id or 'N/A'}")
    print(f"input_file={excel_path}")
    print(f"input_file_exists=true")
    print(f"total_candidates={total_candidates}")
    print(f"resume_root={job_resume_dir}\n")

    # Bind candidates to current job_id
    if user_id_for_job:
        db_conn = None
        db_cur = None
        try:
            db_conn = get_connection()
            if db_conn:
                db_cur = db_conn.cursor()
                db_cur.execute(
                    "UPDATE candidates SET job_id = %s, upload_id = COALESCE(upload_id, %s) WHERE (job_id IS NULL OR job_id = '')",
                    (job_id, upload_id or None)
                )
                db_conn.commit()
                print(f"✅ Bound candidates for user {user_id_for_job} to job_id {job_id}.")
        except Exception as e_bind:
            print("Notice binding job_id to candidates:", e_bind)
        finally:
            if db_cur:
                db_cur.close()
            if db_conn:
                db_conn.close()

    job_folder = str((Path(AUTOMATION_LOG_FOLDER) / job_id).resolve())
    os.makedirs(job_folder, exist_ok=True)

    screenshots_folder = str((Path(job_folder) / "screenshots").resolve())
    os.makedirs(screenshots_folder, exist_ok=True)

    output_file = str((Path(job_folder) / "output.xml").resolve())
    log_file = str((Path(job_folder) / "log.html").resolve())
    report_file = str((Path(job_folder) / "report.html").resolve())

    # Environment Setup
    base_url = request.host_url.rstrip("/")
    environment = os.environ.copy()

    environment["SMART_RECRUITMENT_BASE_URL"] = base_url
    environment["SMART_RECRUITMENT_EXCEL_FILE"] = excel_path
    environment["CANDIDATE_EXCEL_FILE"] = excel_path
    environment["EXCEL_FILE"] = excel_path
    environment["SMART_RECRUITMENT_CANDIDATE_FILE"] = excel_path
    environment["SMART_RECRUITMENT_RESUME_FOLDER"] = job_resume_dir
    environment["RESUME_FOLDER"] = job_resume_dir
    environment["SMART_RECRUITMENT_REGISTRATION_URL"] = registration_url
    environment["REGISTRATION_URL"] = (
        base_url + registration_url
        if registration_url.startswith("/")
        else registration_url
    )
    environment["SMART_RECRUITMENT_JOB_ID"] = job_id
    environment["SMART_RECRUITMENT_UPLOAD_ID"] = upload_id or ""
    environment["SMART_RECRUITMENT_BROWSER_MODE"] = browser_mode
    environment["BROWSER_MODE"] = browser_mode
    environment["SMART_RECRUITMENT_ATTACH_EXISTING_CHROME"] = "false"

    command = [
        sys.executable,
        "-m",
        "robot",
        "--variable", f"INPUT_FILE:{excel_path}",
        "--variable", f"JOB_ID:{job_id}",
        "--variable", f"UPLOAD_ID:{upload_id or ''}",
        "--variable", f"RESUME_FOLDER:{job_resume_dir}",
        "--outputdir",
        job_folder,
        "--output",
        "output.xml",
        "--log",
        "log.html",
        "--report",
        "report.html",
        ROBOT_FILE
    ]

    def _stream_process_output(proc, job_dict):
        try:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                clean_line = line.strip()
                if clean_line:
                    job_dict["output"].append(clean_line)
                    if len(job_dict["output"]) > 300:
                        job_dict["output"] = job_dict["output"][-300:]
        except Exception as err:
            print("Process stream reader notice:", err)
        finally:
            if proc.stdout:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

    try:
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        job_info = {
            "process": process,
            "pid": process.pid,
            "job_id": job_id,
            "upload_id": upload_id or "",
            "user_id": session.get("user_id"),
            "status": "STARTING",
            "browser": "selenium",
            "browser_mode": browser_mode,
            "browser_status": "initializing",
            "robot": "active",
            "robot_status": "starting",
            "stage": "Initializing Selenium WebDriver",
            "last_successful_step": "Automation job initialized",
            "failure_reason": "",
            "progress": 5,
            "message": f"Robot Framework initialized (Browser: {browser_mode.capitalize()} mode)...",
            "output": [],
            "job_folder": job_folder,
            "started": datetime.now().isoformat(),
            "output_file": output_file,
            "log_file": log_file,
            "report_file": report_file,
            "current_candidate": 0,
            "total_candidates": total_candidates
        }

        AUTOMATION_JOBS[job_id] = job_info

        reader_thread = threading.Thread(
            target=_stream_process_output,
            args=(process, job_info),
            daemon=True
        )
        reader_thread.start()

        return jsonify({
            "success": True,
            "jobId": job_id,
            "job_id": job_id,
            "upload_id": upload_id or "",
            "status": "STARTING",
            "browser": "selenium",
            "browser_mode": browser_mode,
            "robot": "active",
            "message": "Robot Framework & Selenium started successfully.",
            "total_candidates": total_candidates,
            "pid": process.pid
        })

    except Exception as e:
        print("ROBOT START ERROR:", e)
        return jsonify({
            "success": False,
            "status": "FAILED",
            "job_id": job_id,
            "jobId": job_id,
            "upload_id": upload_id or "",
            "message": f"Could not start Robot Framework: {str(e)}"
        }), 500


# ============================================================
# ROBOT STATUS & STATE MANAGEMENT
# ============================================================

@app.route(
    "/api/automation/status/<job_id>",
    methods=["GET"]
)
def automation_status(job_id):

    if "logged_in" not in session:
        return jsonify({
            "success": False,
            "status": "FAILED",
            "message": "Unauthorized"
        }), 401

    job = AUTOMATION_JOBS.get(job_id)

    if not job or job.get("user_id") != session.get("user_id"):
        return jsonify({
            "success": False,
            "jobId": job_id,
            "status": "FAILED",
            "message": "Automation job not found"
        }), 404

    process = job["process"]
    return_code = process.poll()
    outputs = job.get("output", [])
    current_candidate = job.get("current_candidate", 0)
    total_candidates = job.get("total_candidates", 0)
    stage = job.get("stage", "Processing")
    last_successful_step = job.get("last_successful_step", "Job started")
    failure_reason = job.get("failure_reason", "")

    # Parse stdout in real-time
    for line in outputs:
        # Total candidates in Excel: X
        m_tot = re.search(r"Total candidates in Excel:\s*(\d+)", line)
        if m_tot and not total_candidates:
            total_candidates = int(m_tot.group(1))
            job["total_candidates"] = total_candidates

        # Candidate X/Y: Name
        m_cand = re.search(r"Candidate\s+(\d+)/(\d+)(?::\s*(.+))?", line)
        if m_cand:
            current_candidate = int(m_cand.group(1))
            total_candidates = int(m_cand.group(2))
            job["current_candidate"] = current_candidate
            job["total_candidates"] = total_candidates

        # STAGE: <stage_name>
        if "STAGE:" in line:
            stage = line.split("STAGE:", 1)[1].strip()
            job["stage"] = stage

        # LAST_STEP: <step_name>
        if "LAST_STEP:" in line:
            last_successful_step = line.split("LAST_STEP:", 1)[1].strip()
            job["last_successful_step"] = last_successful_step

        # CANDIDATE_STATE: <state>
        if "CANDIDATE_STATE:" in line:
            cand_state = line.split("CANDIDATE_STATE:", 1)[1].strip()
            job["candidate_state"] = cand_state

        # Registration: SUCCESS or Registration: FAILED
        if "Registration: SUCCESS" in line:
            job["last_registration_status"] = "SUCCESS"
        elif "Registration FAILED" in line:
            job["last_registration_status"] = "FAILED"

        # Resume: <status>
        if line.strip().startswith("Resume:"):
            resume_st = line.split("Resume:", 1)[1].strip()
            job["last_resume_status"] = resume_st

        # Detect candidate or selenium failure details
        if "FAILED:" in line or "FAIL " in line or "Error:" in line or "Exception:" in line or "TypeError:" in line:
            cleaned_err = re.sub(r"^[A-Z_]+:\s*", "", line).strip()
            if cleaned_err and len(cleaned_err) > 3:
                failure_reason = cleaned_err
                job["failure_reason"] = failure_reason

    # Browser status lifecycle
    browser_connected = any("Selenium Connected" in l or "WebDriver session active" in l for l in outputs)
    job["browser_status"] = "connected" if browser_connected else "initializing"

    # Smart progress calculation
    if total_candidates > 0 and current_candidate > 0:
        calc_progress = int(20 + (current_candidate / total_candidates) * 75)
        job["progress"] = max(job.get("progress", 10), min(95, calc_progress))
    elif outputs and job.get("progress", 0) < 20:
        job["progress"] = 20

    # Build status message
    status_message = "Robot Framework is running..."
    if outputs:
        for line in reversed(outputs[-20:]):
            if any(k in line for k in ["STAGE:", "LAST_STEP:", "Candidate", "Resume", "Registration", "AUTOMATION"]):
                status_message = line.replace("STAGE:", "").replace("LAST_STEP:", "").strip()
                break

    # ========================================================
    # STILL RUNNING (process active)
    # ========================================================
    if return_code is None:
        job["status"] = "RUNNING"
        job["robot_status"] = "active"
        job["message"] = status_message

        return jsonify({
            "success": True,
            "jobId": job_id,
            "job_id": job_id,
            "status": "RUNNING",
            "browser": "selenium",
            "browser_mode": job.get("browser_mode", DEFAULT_BROWSER_MODE),
            "browser_status": job["browser_status"],
            "robot": "active",
            "robot_status": "active",
            "stage": stage,
            "last_successful_step": last_successful_step,
            "progress": job["progress"],
            "current_candidate": current_candidate,
            "total_candidates": total_candidates,
            "message": status_message,
            "output": outputs[-30:]
        })

    # ========================================================
    # COMPLETED (Return code 0)
    # ========================================================
    if return_code == 0:
        job["status"] = "SUCCESS"
        job["robot_status"] = "completed"
        job["browser_status"] = "closed"
        job["progress"] = 100
        job["stage"] = "Completed"
        job["last_successful_step"] = "All candidates processed successfully"
        job["message"] = "Candidate automation completed successfully."

        return jsonify({
            "success": True,
            "jobId": job_id,
            "job_id": job_id,
            "status": "SUCCESS",
            "browser": "selenium",
            "browser_mode": job.get("browser_mode", DEFAULT_BROWSER_MODE),
            "browser_status": "closed",
            "robot": "completed",
            "robot_status": "completed",
            "stage": "Completed",
            "last_successful_step": "All candidates processed successfully",
            "progress": 100,
            "current_candidate": total_candidates or current_candidate,
            "total_candidates": total_candidates,
            "message": "Automation completed successfully",
            "output": outputs[-50:]
        })

    # ========================================================
    # FAILED (Non-zero exit code)
    # ========================================================
    job["status"] = "FAILED"
    job["robot_status"] = "failed"
    job["browser_status"] = "cleaned_up"
    job["progress"] = 100

    exact_reason = failure_reason or f"Robot Framework automation failed (exit code: {return_code})"
    job["message"] = exact_reason

    return jsonify({
        "success": False,
        "jobId": job_id,
        "job_id": job_id,
        "status": "FAILED",
        "browser": "selenium",
        "browser_mode": job.get("browser_mode", DEFAULT_BROWSER_MODE),
        "browser_status": "cleaned_up",
        "robot": "failed",
        "robot_status": "failed",
        "stage": stage,
        "last_successful_step": last_successful_step,
        "reason": exact_reason,
        "progress": 100,
        "current_candidate": current_candidate,
        "total_candidates": total_candidates,
        "message": exact_reason,
        "output": outputs[-50:]
    })


# ============================================================
# CANCEL AUTOMATION JOB
# ============================================================

@app.route(
    "/api/automation/cancel/<job_id>",
    methods=["POST"]
)
def automation_cancel(job_id):

    if "logged_in" not in session:
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    job = AUTOMATION_JOBS.get(job_id)
    if not job or job.get("user_id") != session.get("user_id"):
        return jsonify({
            "success": False,
            "message": "Automation job not found"
        }), 404

    process = job.get("process")
    if process and process.poll() is None:
        try:
            process.terminate()
            job["status"] = "CANCELLED"
            job["robot_status"] = "cancelled"
            job["browser_status"] = "terminated"
            job["message"] = "Automation job was cancelled by user."
            return jsonify({
                "success": True,
                "jobId": job_id,
                "status": "CANCELLED",
                "message": "Automation job cancelled successfully."
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "message": f"Could not cancel job: {str(e)}"
            }), 500

    return jsonify({
        "success": True,
        "jobId": job_id,
        "status": job.get("status", "IDLE"),
        "message": "Job is not currently running."
    })


# ============================================================
# AUTOMATION LOGS
# ============================================================

@app.route(
    "/api/automation/logs",
    methods=["GET"]
)
def automation_logs():

    if "logged_in" not in session:
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    result = []

    try:
        current_user_id = session.get("user_id")
        for job_id, job in AUTOMATION_JOBS.items():
            if job.get("user_id") == current_user_id:
                result.append({
                    "job_id": job_id,
                    "jobId": job_id,
                    "status": job.get("status", "UNKNOWN"),
                    "stage": job.get("stage", ""),
                    "started": job.get("started", ""),
                    "message": job.get("message", "")
                })

        result.reverse()

        return jsonify({
            "success": True,
            "jobs": result
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


# ============================================================
# AUTOMATION SUCCESS PAGE
# ============================================================

@app.route("/automation/success")
def automation_success():

    if "logged_in" not in session:

        flash(
            "Please login first",
            "error"
        )

        return redirect(
            url_for("login")
        )

    job_id = request.args.get("job_id", "").strip()

    return render_template(
        "automation_success.html",
        fullname=session.get("fullname"),
        username=session.get("username"),
        job_id=job_id
    )


# ============================================================
# AUTOMATION REGISTER CANDIDATE API (BACKEND DRIVEN)
# Accepts multipart/form-data or JSON with optional resume file
# ============================================================

@app.route("/api/automation/register-candidate", methods=["POST"])
def api_automation_register_candidate():
    connection = None
    cursor = None
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = request.form.to_dict()

        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip()
        phone = str(data.get("phone", "")).strip()
        position = str(data.get("position", "")).strip()
        job_id = str(data.get("job_id", "")).strip() or None
        upload_id = str(data.get("upload_id", "")).strip() or None

        if not name or not email or not phone or not position:
            return jsonify({
                "success": False,
                "message": "Name, email, phone and position are required"
            }), 400

        email_pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(email_pattern, email):
            return jsonify({
                "success": False,
                "message": "Invalid email address"
            }), 400

        logger.info("AUTOMATION REGISTRATION START email=%s", email)

        connection = get_connection()
        if connection is None:
            return jsonify({
                "success": False,
                "message": "Database connection failed"
            }), 500

        cursor = connection.cursor(dictionary=True)

        # 1. User Record Creation & Verification FIRST
        cursor.execute("SELECT id, username, email, role, password FROM users WHERE email=%s LIMIT 1", (email,))
        usr_rec = cursor.fetchone()
        is_new_user = False
        cand_user_id = None
        cand_username = None
        temp_pw = None

        if usr_rec:
            cand_username = usr_rec["username"]
            cand_user_id = usr_rec["id"]
            if str(usr_rec.get("role") or "").strip().lower() != "candidate":
                cursor.execute("UPDATE users SET role='candidate' WHERE id=%s", (cand_user_id,))
                connection.commit()
            logger.info("USER CREATED user_id=%s username=%s role=CANDIDATE active=true", cand_user_id, cand_username)
        else:
            cand_username = generate_unique_username(email, cursor)
            temp_pw = generate_candidate_temp_password(email)
            hashed_pw = bcrypt.generate_password_hash(temp_pw).decode("utf-8")
            totp_sec = pyotp.random_base32()

            cursor.execute(
                "INSERT INTO users (fullname, username, email, phone, password, role, must_change_password, google_authenticator_configured, totp_secret) VALUES (%s, %s, %s, %s, %s, 'candidate', 1, 0, %s)",
                (name, cand_username, email, phone, hashed_pw, totp_sec)
            )
            connection.commit()
            cand_user_id = cursor.lastrowid
            is_new_user = True
            logger.info("USER CREATED user_id=%s username=%s role=CANDIDATE active=true", cand_user_id, cand_username)

        # 1b. User Persistence & Auth Verification
        cursor.execute("SELECT id, username, email, role, password FROM users WHERE id=%s LIMIT 1", (cand_user_id,))
        verify_usr = cursor.fetchone()
        if not verify_usr:
            raise Exception(f"User account creation failed or transaction not committed for user_id #{cand_user_id}")

        logger.info("USER COMMIT VERIFIED user_exists=true")

        # Test auth lookup simulating login
        cursor.execute(
            "SELECT id, username, email, role, password FROM users WHERE username=%s OR email=%s OR LOWER(username)=LOWER(%s) OR LOWER(email)=LOWER(%s) LIMIT 1",
            (cand_username, email, cand_username, email)
        )
        auth_test_user = cursor.fetchone()
        if not auth_test_user:
            raise Exception(f"Auth lookup test failed for candidate user {cand_username} / {email}")

        logger.info("AUTH LOOKUP TEST user_found=true username_match=true role=CANDIDATE")

        if is_new_user and temp_pw:
            pw_match_test = bcrypt.check_password_hash(auth_test_user["password"], temp_pw)
            if not pw_match_test:
                raise Exception("Password verification failed for newly created candidate account!")
            logger.info("PASSWORD VERIFICATION password_match=true")

        # 2. Candidate Record Creation / Linkage
        effective_hr_id = None
        if session.get("logged_in") and str(session.get("role") or "").strip().lower() in ["hr", "admin"]:
            effective_hr_id = session.get("user_id")
        if not effective_hr_id and job_id:
            try:
                cursor.execute("SELECT user_id FROM automation_jobs WHERE (job_code = %s OR upload_id = %s) AND user_id IS NOT NULL LIMIT 1", (job_id, job_id))
                j_row = cursor.fetchone()
                if j_row and j_row.get("user_id"):
                    effective_hr_id = j_row["user_id"]
            except Exception:
                pass
        if not effective_hr_id and upload_id:
            try:
                cursor.execute("SELECT user_id FROM uploaded_files WHERE (upload_id = %s OR job_id = %s) AND user_id IS NOT NULL LIMIT 1", (upload_id, upload_id))
                u_row = cursor.fetchone()
                if u_row and u_row.get("user_id"):
                    effective_hr_id = u_row["user_id"]
            except Exception:
                pass

        if effective_hr_id:
            cursor.execute("SELECT id, resume, resume_filename FROM candidates WHERE email=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s)) LIMIT 1", (email, effective_hr_id, effective_hr_id))
        else:
            cursor.execute("SELECT id, resume, resume_filename FROM candidates WHERE email=%s LIMIT 1", (email,))
        existing = cursor.fetchone()

        candidate_id = None
        if existing:
            candidate_id = existing["id"]
            cursor.execute(
                """
                UPDATE candidates
                SET name=%s, phone=%s, position=%s, registration_status='Registered',
                    user_id=%s, processed_at=%s, job_id=COALESCE(%s, job_id), upload_id=COALESCE(%s, upload_id),
                    hr_id=COALESCE(hr_id, %s)
                WHERE id=%s
                """,
                (name, phone, position, cand_user_id, datetime.now(), job_id, upload_id, effective_hr_id, candidate_id)
            )
            connection.commit()
        else:
            cursor.execute(
                """
                INSERT INTO candidates
                (name, email, phone, position, resume, resume_filename, resume_status,
                 registration_status, automation_status, status, created_at, processed_at,
                 email_status, job_id, upload_id, user_id, hr_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (name, email, phone, position, None, None, "Not Uploaded",
                 "Registered", "Pending", "New", datetime.now(), datetime.now(),
                 "Not Sent", job_id, upload_id, cand_user_id, effective_hr_id)
            )
            connection.commit()
            candidate_id = cursor.lastrowid

        logger.info("CANDIDATE CREATED candidate_id=%s user_id=%s", candidate_id, cand_user_id)

        # 3. Process attached resume file if present
        resume_file = request.files.get("resume")
        resume_uploaded = False
        resume_filename_val = None
        resume_status_val = "Not Uploaded"

        if resume_file and resume_file.filename:
            if allowed_file(resume_file.filename, ALLOWED_RESUME_FILES):
                original_filename = secure_filename(resume_file.filename)
                extension = ""
                if "." in original_filename:
                    extension = "." + original_filename.rsplit(".", 1)[1].lower()

                unique_filename = f"candidate_{candidate_id}_{int(datetime.now().timestamp())}{extension}"
                resume_path = (Path(RESUME_FOLDER) / unique_filename).resolve()

                resume_file.save(str(resume_path))

                if resume_path.is_file() and resume_path.stat().st_size > 0:
                    file_size_bytes = resume_path.stat().st_size
                    print(f"========================================")
                    print(f"AUTOMATION RESUME SAVED FOR CANDIDATE #{candidate_id}")
                    print(f"Original Filename: {original_filename}")
                    print(f"Stored Filename:   {unique_filename}")
                    print(f"Absolute Path:     {resume_path}")
                    print(f"File Size:         {file_size_bytes} bytes")
                    print(f"========================================")

                    cursor.execute(
                        """
                        UPDATE candidates
                        SET resume=%s,
                            resume_filename=%s,
                            resume_status=%s,
                            registration_status=%s,
                            status=%s,
                            automation_status=%s,
                            processed_at=%s,
                            job_id=COALESCE(%s, job_id)
                        WHERE id=%s
                        """,
                        (
                            unique_filename,
                            original_filename,
                            "Uploaded",
                            "Registered",
                            "Processed",
                            "Processed",
                            datetime.now(),
                            job_id,
                            candidate_id
                        )
                    )
                    resume_uploaded = True
                    resume_filename_val = original_filename
                    resume_status_val = "Uploaded"
                else:
                    print(f"❌ Resume file save failed or size 0 for candidate #{candidate_id}")
                    cursor.execute(
                        """
                        UPDATE candidates
                        SET resume_status=%s,
                            registration_status=%s,
                            status=%s,
                            automation_status=%s,
                            processed_at=%s,
                            job_id=COALESCE(%s, job_id)
                        WHERE id=%s
                        """,
                        ("Upload Failed", "Registered", "Resume Pending", "Resume Pending", datetime.now(), job_id, candidate_id)
                    )
                    resume_status_val = "Upload Failed"
            else:
                print(f"❌ Invalid resume file extension: {resume_file.filename}")
                cursor.execute(
                    """
                    UPDATE candidates
                    SET resume_status=%s,
                        registration_status=%s,
                        status=%s,
                        automation_status=%s,
                        processed_at=%s,
                        job_id=COALESCE(%s, job_id)
                    WHERE id=%s
                    """,
                    ("Upload Failed", "Registered", "Resume Pending", "Resume Pending", datetime.now(), job_id, candidate_id)
                )
                resume_status_val = "Upload Failed"
        else:
            if existing and existing.get("resume") and (Path(RESUME_FOLDER) / str(existing["resume"])).is_file():
                cursor.execute(
                    """
                    UPDATE candidates
                    SET resume_status=%s,
                        registration_status=%s,
                        status=%s,
                        automation_status=%s,
                        processed_at=%s,
                        job_id=COALESCE(%s, job_id)
                    WHERE id=%s
                    """,
                    ("Uploaded", "Registered", "Processed", "Processed", datetime.now(), job_id, candidate_id)
                )
                resume_uploaded = True
                resume_status_val = "Uploaded"
            else:
                cursor.execute(
                    """
                    UPDATE candidates
                    SET resume_status=%s,
                        registration_status=%s,
                        status=%s,
                        automation_status=%s,
                        processed_at=%s,
                        job_id=COALESCE(%s, job_id)
                    WHERE id=%s
                    """,
                    ("Upload Failed", "Registered", "Resume Pending", "Resume Pending", datetime.now(), job_id, candidate_id)
                )
                resume_status_val = "Upload Failed"

        connection.commit()

        # 4. Post-commit DB Verification Check
        cursor.execute("SELECT id, email, user_id, job_id, upload_id FROM candidates WHERE id=%s LIMIT 1", (candidate_id,))
        verify_cand = cursor.fetchone()
        if not verify_cand or not verify_cand.get("user_id"):
            raise Exception(f"Database persistence verification failed for candidate ID #{candidate_id} after commit!")

        logger.info(
            "AUTOMATION REGISTRATION candidate_id=%s email=%s job_id=%s upload_id=%s database_save=SUCCESS database_commit=SUCCESS database_verify=SUCCESS",
            candidate_id, email, job_id or "N/A", upload_id or "N/A"
        )
        logger.info("AUTOMATION REGISTRATION COMPLETE")

        if is_new_user:
            email_result = send_candidate_confirmation_email({
                "email": email,
                "username": cand_username,
                "temp_password": temp_pw
            }, base_url=request.host_url)
            email_status_val = "Sent" if email_result.get("success") else "Failed"
        else:
            email_status_val = "Already Exists"
            email_result = {"success": True, "message": "Account already exists"}

        try:
            cursor.execute(
                "UPDATE candidates SET email_status=%s WHERE id=%s",
                (email_status_val, candidate_id)
            )
            connection.commit()
        except Exception as e_email_db:
            print("Notice updating candidate email_status in DB:", e_email_db)

        return jsonify({
            "success": True,
            "message": "Candidate registered successfully via automation backend API",
            "candidate_id": candidate_id,
            "registration": "success",
            "registration_status": "Registered",
            "resume_upload": "success" if resume_uploaded else "failed",
            "resume_status": resume_status_val,
            "resume_filename": resume_filename_val,
            "email": "success" if email_result.get("success") else "failed",
            "email_status": email_status_val,
            "email_message": email_result.get("message", ""),
            "status": "Processed" if resume_uploaded else "Resume Pending"
        })


    except Exception as e:
        if connection:
            connection.rollback()
        print("API AUTOMATION REGISTER CANDIDATE ERROR:", e)
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ============================================================
# AUTOMATION RESULTS API
# ============================================================

@app.route("/api/automation/results", methods=["GET"])
@app.route("/api/automation/results/<job_id>", methods=["GET"])
def api_automation_results(job_id=None):

    if "logged_in" not in session:

        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    if not job_id:
        job_id = request.args.get("job_id", "").strip()

    connection = None
    cursor = None

    try:

        connection = get_connection()

        if connection is None:

            return jsonify({
                "success": False,
                "message": "Database connection failed"
            }), 500

        cursor = connection.cursor(dictionary=True)

        user_role = str(session.get("role") or "").strip().lower()
        is_admin = (user_role == "admin")
        auth_hr_id = get_authenticated_hr_id()

        if user_role == "candidate":
            user_email = session.get("email") or ""
            current_user_id = resolve_user_id()
            where_sql = "WHERE (user_id = %s OR email = %s)"
            where_params = [current_user_id, user_email]
        elif is_admin:
            if job_id:
                where_sql = "WHERE job_id = %s"
                where_params = [job_id]
            else:
                where_sql = ""
                where_params = []
        else:
            if job_id:
                if not verify_job_ownership(cursor, job_id, auth_hr_id, is_admin=False):
                    cursor.close()
                    connection.close()
                    return jsonify({
                        "success": True,
                        "job_id": job_id,
                        "status": "completed",
                        "total": 0,
                        "success_count": 0,
                        "failure_count": 0,
                        "resumes_uploaded_count": 0,
                        "candidates": []
                    })
                where_sql = "WHERE job_id = %s AND (hr_id = %s OR (hr_id IS NULL AND user_id = %s))"
                where_params = [job_id, auth_hr_id, auth_hr_id]
            else:
                where_sql = "WHERE (hr_id = %s OR (hr_id IS NULL AND user_id = %s))"
                where_params = [auth_hr_id, auth_hr_id]

        limit_sql = "" if job_id else "LIMIT 50"
        order_sql = "ORDER BY id ASC" if job_id else "ORDER BY id DESC"

        query = f"""
            SELECT
                id,
                name,
                email,
                phone,
                position,
                resume,
                resume_filename,
                COALESCE(resume_status, 'Not Uploaded') AS resume_status,
                COALESCE(registration_status, 'Registered') AS registration_status,
                COALESCE(automation_status, 'Processed') AS automation_status,
                status,
                created_at,
                processed_at,
                job_id
            FROM candidates
            {where_sql}
            {order_sql}
            {limit_sql}
        """
        cursor.execute(query, where_params)
        candidates_data = cursor.fetchall()
        if not job_id:
            candidates_data.reverse()

        total = len(candidates_data)
        registered_count = 0
        resumes_uploaded_count = 0
        failed_count = 0

        for candidate in candidates_data:

            candidate["candidate_id"] = candidate["id"]

            # Timestamp format
            p_at = candidate.get("processed_at") or candidate.get("created_at")
            if p_at:
                candidate["processed_at_formatted"] = p_at.strftime("%d %b %Y %H:%M")
                candidate["processed_at"] = p_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                candidate["processed_at_formatted"] = "N/A"
                candidate["processed_at"] = ""

            if candidate.get("created_at"):
                candidate["created_at"] = candidate["created_at"].strftime("%Y-%m-%d %H:%M:%S")

            # Resume URL
            cand_res_file = candidate.get("resume") or candidate.get("resume_filename")
            if cand_res_file:
                phys_file = (Path(RESUME_FOLDER) / str(cand_res_file)).resolve()
                if phys_file.is_file() and phys_file.stat().st_size > 0:
                    candidate["resume_url"] = url_for("candidate_resume", filename=cand_res_file)
                    candidate["resume_status"] = "Uploaded"
                else:
                    candidate["resume_url"] = None
            else:
                candidate["resume_url"] = None

            # Stats accumulation
            reg_st = candidate.get("registration_status", "Registered")
            res_st = candidate.get("resume_status", "Not Uploaded")

            if reg_st in ("Registered", "Success", "Processed"):
                registered_count += 1
            else:
                failed_count += 1

            if res_st in ("Uploaded", "Success", "Resume Uploaded"):
                resumes_uploaded_count += 1

        # Check job in memory status
        job_info = AUTOMATION_JOBS.get(job_id, {})
        job_status = job_info.get("status", "completed" if total > 0 else "completed")

        return jsonify({
            "success": True,
            "job_id": job_id,
            "status": job_status,
            "total": total,
            "success_count": registered_count,
            "failure_count": failed_count,
            "resume_success_count": resumes_uploaded_count,
            "registered": registered_count,
            "resumes_uploaded": resumes_uploaded_count,
            "failed": failed_count,
            "candidates": candidates_data
        })

    except Exception as e:

        print("AUTOMATION RESULTS API ERROR:", e)

        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================================
# RESUME SCANNER API — UPLOAD & PARSE RESUME
# ============================================================

@app.route("/api/resume-scanner/upload", methods=["POST"])
def api_resume_scanner_upload():

    if "logged_in" not in session:
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    if "resume" not in request.files:
        return jsonify({
            "success": False,
            "message": "No resume file was provided in the upload request."
        }), 400

    resume_file = request.files["resume"]

    if not resume_file or not resume_file.filename:
        return jsonify({
            "success": False,
            "message": "Please select a resume file to upload."
        }), 400

    if not allowed_file(resume_file.filename, ALLOWED_RESUME_FILES):
        return jsonify({
            "success": False,
            "message": "Unsupported resume format. Please upload PDF, DOC, or DOCX."
        }), 400

    original_filename = secure_filename(resume_file.filename)
    extension = ""
    if "." in original_filename:
        extension = "." + original_filename.rsplit(".", 1)[1].lower()

    timestamp = int(datetime.now().timestamp())
    saved_filename = f"scan_{timestamp}_{original_filename}"
    saved_path = os.path.join(RESUME_FOLDER, saved_filename)

    try:
        resume_file.save(saved_path)
    except Exception as e:
        print("RESUME SCANNER SAVE ERROR:", e)
        return jsonify({
            "success": False,
            "message": f"Failed to save resume file to disk: {str(e)}"
        }), 500

    # Extract text from saved resume
    extracted_text = extract_resume_text(saved_path, original_filename)
    parsed_info = parse_candidate_info(extracted_text, original_filename)

    name = parsed_info.get("name") or "Candidate"
    email = parsed_info.get("email") or f"candidate_{timestamp}@recruitment.local"
    phone = parsed_info.get("phone") or "Not detected"
    position = parsed_info.get("position") or "Software Engineer"
    skills_str = parsed_info.get("skills_str") or "Not detected"
    education = parsed_info.get("education") or "Not detected"
    experience = parsed_info.get("experience") or "Not detected"

    connection = None
    cursor = None
    candidate_id = None
    is_duplicate = False

    try:
        connection = get_connection()
        if connection is None:
            return jsonify({
                "success": False,
                "message": "Database connection failed while storing candidate."
            }), 500

        cursor = connection.cursor(dictionary=True)
        current_user_id = resolve_user_id()

        # Check existing candidate by email if email was detected
        if parsed_info.get("email"):
            cursor.execute(
                "SELECT id, name, email, phone, position FROM candidates WHERE email=%s AND (hr_id=%s OR (hr_id IS NULL AND user_id=%s)) LIMIT 1",
                (parsed_info["email"], current_user_id, current_user_id)
            )
            existing = cursor.fetchone()
            if existing:
                is_duplicate = True
                candidate_id = existing["id"]
                cursor.execute(
                    """
                    UPDATE candidates
                    SET name=COALESCE(NULLIF(%s, 'Candidate'), name),
                        phone=COALESCE(NULLIF(%s, 'Not detected'), phone),
                        position=COALESCE(NULLIF(%s, 'Software Engineer'), position),
                        resume=%s,
                        resume_filename=%s,
                        resume_status=%s,
                        status=%s,
                        skills=%s,
                        education=%s,
                        experience=%s,
                        processed_at=%s,
                        hr_id=COALESCE(hr_id, %s)
                    WHERE id=%s
                    """,
                    (
                        name,
                        phone,
                        position,
                        saved_filename,
                        original_filename,
                        "Uploaded",
                        "Processed",
                        skills_str,
                        education,
                        experience,
                        datetime.now(),
                        current_user_id,
                        candidate_id
                    )
                )

        if not is_duplicate:
            cursor.execute(
                """
                INSERT INTO candidates
                (name, email, phone, position, resume, resume_filename, resume_status,
                 registration_status, automation_status, status, created_at, processed_at,
                 email_status, skills, education, experience, user_id, hr_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    name,
                    email,
                    phone,
                    position,
                    saved_filename,
                    original_filename,
                    "Uploaded",
                    "Registered",
                    "Pending",
                    "Processed",
                    datetime.now(),
                    datetime.now(),
                    "Not Sent",
                    skills_str,
                    education,
                    experience,
                    current_user_id,
                    current_user_id
                )
            )
            candidate_id = cursor.lastrowid

        connection.commit()

        resume_url = url_for("candidate_resume", filename=saved_filename)
        extraction_success = bool(
            extracted_text.strip() and (
                parsed_info.get("email") or
                parsed_info.get("phone") or
                parsed_info.get("skills")
            )
        )

        response_message = (
            "Resume uploaded and candidate information extracted successfully."
            if extraction_success
            else "Resume uploaded. Unable to fully extract candidate information. Please review the resume manually."
        )

        return jsonify({
            "success": True,
            "message": response_message,
            "extraction_success": extraction_success,
            "candidate_id": candidate_id,
            "is_duplicate": is_duplicate,
            "candidate": {
                "id": candidate_id,
                "name": name,
                "email": email,
                "phone": phone,
                "position": position,
                "skills": parsed_info.get("skills", []),
                "skills_str": skills_str,
                "education": education,
                "experience": experience,
                "resume_filename": original_filename,
                "resume_url": resume_url,
                "resume_status": "Uploaded",
                "registration_status": "Registered",
                "status": "Processed",
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        })

    except Exception as db_err:
        if connection:
            connection.rollback()
        print("DATABASE ERROR ON RESUME SCAN:", db_err)
        return jsonify({
            "success": False,
            "message": f"Database error during candidate save: {str(db_err)}"
        }), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ============================================================
# HR ANALYTICS API — LIVE DATABASE METRICS
# ============================================================

@app.route("/api/analytics", methods=["GET"])
def api_analytics():

    if "logged_in" not in session:
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    user_role = str(session.get("role") or "").strip().lower()
    if user_role not in ["hr", "admin"]:
        return jsonify({
            "success": False,
            "message": "Access Denied: HR authorization required"
        }), 403

    connection = None
    cursor = None

    try:
        connection = get_connection()
        if connection is None:
            return jsonify({
                "success": False,
                "message": "Database connection failed"
            }), 500

        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (user_role == "admin")

        if is_admin:
            cand_filter = "1=1"
            cand_params = []
        else:
            cand_filter = "(hr_id = %s OR (hr_id IS NULL AND user_id = %s))"
            cand_params = [auth_hr_id, auth_hr_id]

        # 1. Total Candidates
        cursor.execute(f"SELECT COUNT(*) AS total FROM candidates WHERE {cand_filter}", cand_params)
        total_candidates = cursor.fetchone()["total"] or 0

        # 2. Registered Candidates
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt FROM candidates
            WHERE registration_status IN ('Registered', 'Success', 'Processed') AND {cand_filter}
            """,
            cand_params
        )
        registered_candidates = cursor.fetchone()["cnt"] or 0

        # 3. Pending Candidates
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt FROM candidates
            WHERE (registration_status = 'Pending'
               OR automation_status = 'Pending'
               OR status = 'Pending'
               OR status = 'New') AND {cand_filter}
            """,
            cand_params
        )
        pending_candidates = cursor.fetchone()["cnt"] or 0

        # 4. Failed Candidates
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt FROM candidates
            WHERE (registration_status = 'Failed'
               OR status = 'Failed'
               OR resume_status = 'Upload Failed') AND {cand_filter}
            """,
            cand_params
        )
        failed_candidates = cursor.fetchone()["cnt"] or 0

        # 5. Processed Candidates
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt FROM candidates
            WHERE (status = 'Processed'
               OR automation_status = 'Processed') AND {cand_filter}
            """,
            cand_params
        )
        processed_candidates = cursor.fetchone()["cnt"] or 0

        # 6. Resumes Uploaded
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt FROM candidates
            WHERE resume_status IN ('Uploaded', 'Success', 'Resume Uploaded') AND {cand_filter}
            """,
            cand_params
        )
        resumes_uploaded = cursor.fetchone()["cnt"] or 0

        # 7. Resumes Pending / Not Uploaded
        cursor.execute(
            f"""
            SELECT COUNT(*) AS cnt FROM candidates
            WHERE resume_status NOT IN ('Uploaded', 'Success', 'Resume Uploaded') AND {cand_filter}
            """,
            cand_params
        )
        resumes_pending = cursor.fetchone()["cnt"] or 0

        # 8. Position Distribution
        cursor.execute(
            f"""
            SELECT
                COALESCE(NULLIF(TRIM(position), ''), 'Unassigned') AS position,
                COUNT(*) AS count
            FROM candidates
            WHERE {cand_filter}
            GROUP BY position
            ORDER BY count DESC
            LIMIT 10
            """,
            cand_params
        )
        raw_positions = cursor.fetchall()
        positions_data = []
        for p in raw_positions:
            pct = round((p["count"] / total_candidates * 100), 1) if total_candidates > 0 else 0
            positions_data.append({
                "position": p["position"],
                "count": p["count"],
                "percentage": pct
            })

        # 9. Candidate Status Breakdown
        status_breakdown = {
            "registered": registered_candidates,
            "pending": pending_candidates,
            "processed": processed_candidates,
            "failed": failed_candidates
        }

        # 10. Resume Status Breakdown
        resume_breakdown = {
            "uploaded": resumes_uploaded,
            "not_uploaded": resumes_pending,
            "failed": failed_candidates
        }

        # 11. Candidate Pipeline Funnel
        pipeline_stages = [
            {
                "stage": "Candidates Sourced",
                "count": total_candidates,
                "key": "total",
                "description": "Total candidates captured in the system"
            },
            {
                "stage": "Resumes Uploaded",
                "count": resumes_uploaded,
                "key": "resume_uploaded",
                "description": "Verified candidate resumes attached"
            },
            {
                "stage": "Resumes Processed",
                "count": processed_candidates,
                "key": "processed",
                "description": "Resumes parsed and skills extracted"
            },
            {
                "stage": "Registered Candidates",
                "count": registered_candidates,
                "key": "registered",
                "description": "Candidates successfully registered"
            },
            {
                "stage": "Automation Complete",
                "count": processed_candidates,
                "key": "automation",
                "description": "End-to-end automation workflow complete"
            }
        ]

        # 12. Real Recent Activity Feed
        cursor.execute(
            f"""
            SELECT
                id,
                name,
                email,
                position,
                resume_status,
                registration_status,
                status,
                created_at,
                processed_at
            FROM candidates
            WHERE {cand_filter}
            ORDER BY COALESCE(processed_at, created_at, id) DESC
            LIMIT 12
            """,
            cand_params
        )
        recent_rows = cursor.fetchall()
        activities = []

        for row in recent_rows:
            c_name = row.get("name") or "Candidate"
            event_dt = row.get("processed_at") or row.get("created_at") or datetime.now()
            time_str = event_dt.strftime("%d %b, %H:%M") if hasattr(event_dt, "strftime") else str(event_dt)
            res_status = row.get("resume_status", "Not Uploaded")
            reg_status = row.get("registration_status", "Registered")

            if res_status == "Uploaded":
                act_type = "resume_uploaded"
                act_title = "Resume Uploaded"
                badge_type = "success"
            elif reg_status == "Registered":
                act_type = "candidate_registered"
                act_title = "Candidate Registered"
                badge_type = "primary"
            elif row.get("status") == "Processed":
                act_type = "candidate_processed"
                act_title = "Resume Processed"
                badge_type = "info"
            else:
                act_type = "candidate_added"
                act_title = "Candidate Added"
                badge_type = "neutral"

            activities.append({
                "id": row["id"],
                "candidate": c_name,
                "position": row.get("position", "N/A"),
                "activity": act_title,
                "type": act_type,
                "badge": badge_type,
                "status": reg_status,
                "resume_status": res_status,
                "time": time_str
            })

        # 13. Recent Candidates List (For Quick Overview)
        recent_candidates = []
        for row in recent_rows[:6]:
            c_date = row.get("created_at")
            recent_candidates.append({
                "id": row["id"],
                "name": row["name"],
                "position": row["position"],
                "email": row["email"],
                "registration_status": row["registration_status"],
                "resume_status": row["resume_status"],
                "date": c_date.strftime("%d %b %Y") if hasattr(c_date, "strftime") else "Recent"
            })

        response_data = {
            "success": True,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_candidates": total_candidates,
            "registered": registered_candidates,
            "pending": pending_candidates,
            "failed": failed_candidates,
            "processed": processed_candidates,
            "resume_uploaded": resumes_uploaded,
            "resume_pending": resumes_pending,
            "status_breakdown": status_breakdown,
            "resume_breakdown": resume_breakdown,
            "positions": positions_data,
            "pipeline": pipeline_stages,
            "activities": activities,
            "recent_candidates": recent_candidates
        }

        resp = make_response(jsonify(response_data))
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    except Exception as err:
        print("ANALYTICS API ERROR:", err)
        return jsonify({
            "success": False,
            "message": f"Analytics error: {str(err)}"
        }), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# ============================================================
# UPLOAD INDIVIDUAL RESUME
#
# Kept for existing candidate actions/API.
# ============================================================

@app.route(
    "/api/candidates/<int:candidate_id>/resume",
    methods=["GET", "POST"]
)
def upload_candidate_resume(candidate_id):

    if "logged_in" not in session and request.remote_addr not in ["127.0.0.1", "::1"]:

        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    if request.method == "GET":

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Upload Resume</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background-color: #ffffff;
                    color: #000000;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                }}
                .upload-card {{
                    background: #ffffff;
                    border: 1.5px solid #cbd5e1;
                    padding: 30px;
                    border-radius: 16px;
                    text-align: center;
                    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.05);
                }}
                input[type="file"] {{
                    margin: 20px 0;
                    display: block;
                }}
                button {{
                    background-color: #2563eb;
                    color: #ffffff;
                    border: 1.5px solid #1d4ed8;
                    padding: 10px 20px;
                    border-radius: 8px;
                    font-weight: bold;
                    cursor: pointer;
                }}
            </style>
        </head>
        <body>
            <div class="upload-card">
                <h3>Upload Resume for Candidate {candidate_id}</h3>
                <form method="POST" enctype="multipart/form-data">
                    <input type="file" name="resume" required />
                    <button type="submit">Upload Resume</button>
                </form>
            </div>
        </body>
        </html>
        """


    if "resume" not in request.files:

        return jsonify({
            "success": False,
            "message":
                "No resume selected"
        }), 400

    resume_file = request.files[
        "resume"
    ]

    if (
        not resume_file
        or not resume_file.filename
    ):

        return jsonify({
            "success": False,
            "message":
                "No resume selected"
        }), 400

    if not allowed_file(
        resume_file.filename,
        ALLOWED_RESUME_FILES
    ):

        return jsonify({
            "success": False,
            "message":
                "Only PDF, DOC and DOCX resumes are allowed"
        }), 400

    connection = None
    cursor = None

    try:

        connection = get_connection()

        if connection is None:

            return jsonify({
                "success": False,
                "message":
                    "Database connection failed"
            }), 500

        cursor = connection.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                name,
                email
            FROM candidates
            WHERE id=%s
            """,
            (candidate_id,)
        )

        candidate = cursor.fetchone()

        if candidate is None:
            return jsonify({
                "success": False,
                "message": "Candidate not found"
            }), 404

        user_role = str(session.get("role") or "").strip().lower()
        if user_role == "candidate":
            current_user_id = resolve_user_id()
            user_email = session.get("email") or ""
            if candidate.get("user_id") != current_user_id and candidate.get("email") != user_email:
                cursor.close()
                connection.close()
                return jsonify({"success": False, "message": "Access Denied: You cannot upload files to another candidate's account."}), 403

        original_filename = secure_filename(
            resume_file.filename
        )

        extension = ""

        if "." in original_filename:

            extension = (
                "."
                + original_filename
                .rsplit(".", 1)[1]
                .lower()
            )

        filename = (
            f"candidate_{candidate_id}_"
            f"{int(datetime.now().timestamp())}"
            f"{extension}"
        )

        resume_path = os.path.join(
            RESUME_FOLDER,
            filename
        )

        resume_file.save(
            resume_path
        )

        cursor.execute(
            """
            UPDATE candidates
            SET
                resume=%s,
                status=%s
            WHERE id=%s
            """,
            (
                filename,
                "Resume Uploaded",
                candidate_id
            )
        )

        connection.commit()

        return jsonify({

            "success": True,

            "message":
                "Resume uploaded successfully",

            "filename":
                filename

        })

    except Exception as e:

        if connection:
            connection.rollback()

        print(
            "RESUME UPLOAD ERROR:",
            e
        )

        return jsonify({

            "success": False,

            "message":
                str(e)

        }), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================================
# SERVE RESUME
# ============================================================

@app.route(
    "/candidate-resumes/<path:filename>"
)
def candidate_resume(filename):

    if "logged_in" not in session:

        return redirect(
            url_for("login")
        )

    safe_name = os.path.basename(filename)

    user_role = str(session.get("role") or "").strip().lower()
    is_admin = (user_role == "admin")
    if user_role == "candidate":
        current_user_id = resolve_user_id()
        user_email = session.get("email") or ""
        connection = get_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id FROM candidates WHERE (resume = %s OR resume_filename = %s) AND (user_id = %s OR email = %s) LIMIT 1",
                (safe_name, safe_name, current_user_id, user_email)
            )
            owned = cursor.fetchone()
            cursor.close()
            connection.close()
            if not owned:
                return jsonify({"success": False, "message": "Access Denied: You do not have permission to view this resume."}), 403
    elif not is_admin:
        auth_hr_id = get_authenticated_hr_id()
        if not auth_hr_id:
            return jsonify({"success": False, "message": "Access Denied: HR authorization required."}), 403
        connection = get_connection()
        if connection:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id FROM candidates
                WHERE (resume = %s OR resume_filename = %s)
                  AND (
                    hr_id = %s
                    OR (hr_id IS NULL AND user_id = %s)
                    OR (job_id IS NOT NULL AND job_id IN (SELECT job_code FROM automation_jobs WHERE user_id = %s))
                    OR (upload_id IS NOT NULL AND upload_id IN (SELECT upload_id FROM uploaded_files WHERE user_id = %s))
                  )
                LIMIT 1
                """,
                (safe_name, safe_name, auth_hr_id, auth_hr_id, auth_hr_id, auth_hr_id)
            )
            owned = cursor.fetchone()
            cursor.close()
            connection.close()
            if not owned:
                return jsonify({"success": False, "message": "Access Denied: You do not have permission to view this resume."}), 403

    file_path = (Path(RESUME_FOLDER) / safe_name).resolve()
    if not file_path.is_file():
        flash("Resume file not found on disk.", "error")
        return redirect(url_for("candidate_dashboard" if user_role == "candidate" else "candidates"))

    resp = send_from_directory(
        str(Path(RESUME_FOLDER).resolve()),
        safe_name,
        as_attachment=False
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


# ============================================================
# ============================================================
# CANDIDATE DELETION HELPERS & ENDPOINTS
# ============================================================

def delete_single_candidate_record(cursor, candidate_id, hr_id=None, is_admin=False):
    """
    Safely deletes a single candidate record and all associated relational data
    (exam attempts, answers, questions, security events, assignments, interviews, user accounts, files).
    Enforces that candidate record belongs to the authorized HR account unless caller is admin.
    Returns (success: bool, message: str, candidate_name: str).
    """
    if not is_admin and hr_id:
        cand = verify_candidate_ownership(cursor, candidate_id, hr_id, is_admin=False)
        if not cand:
            return False, "Access Denied: You do not have permission to delete this candidate", f"Candidate #{candidate_id}"
    else:
        cursor.execute("SELECT id, name, email, user_id, resume_filename, resume FROM candidates WHERE id = %s", (candidate_id,))
        cand = cursor.fetchone()
        if not cand:
            return False, "Candidate not found", f"Candidate #{candidate_id}"

    cand_name = cand.get("name") or cand.get("email") or f"Candidate #{candidate_id}"
    cand_user_id = cand.get("user_id")
    cand_email = cand.get("email")
    resume_fn = cand.get("resume_filename") or cand.get("resume")

    # 1. Clean up exam attempts and answers/questions/events
    cursor.execute("SELECT id FROM exam_attempts WHERE candidate_id = %s OR (user_id IS NOT NULL AND user_id = %s)", (candidate_id, cand_user_id or -1))
    attempts = cursor.fetchall()
    attempt_ids = [a["id"] for a in attempts if isinstance(a, dict) and "id" in a] if attempts else []

    if attempt_ids:
        format_strings = ','.join(['%s'] * len(attempt_ids))
        try:
            cursor.execute(f"DELETE FROM attempt_answers WHERE attempt_id IN ({format_strings})", tuple(attempt_ids))
        except Exception:
            pass
        try:
            cursor.execute(f"DELETE FROM attempt_questions WHERE attempt_id IN ({format_strings})", tuple(attempt_ids))
        except Exception:
            pass
        try:
            cursor.execute(f"DELETE FROM security_events WHERE attempt_id IN ({format_strings})", tuple(attempt_ids))
        except Exception:
            pass

    try:
        cursor.execute("DELETE FROM security_events WHERE candidate_id = %s", (candidate_id,))
    except Exception:
        pass

    try:
        cursor.execute("DELETE FROM exam_assignments WHERE candidate_id = %s", (candidate_id,))
    except Exception:
        pass

    try:
        cursor.execute("DELETE FROM candidate_exams WHERE candidate_id = %s", (candidate_id,))
    except Exception:
        pass

    cursor.execute("DELETE FROM exam_attempts WHERE candidate_id = %s OR (user_id IS NOT NULL AND user_id = %s)", (candidate_id, cand_user_id or -1))

    # 2. Clean up interviews
    try:
        cursor.execute("DELETE FROM interviews WHERE candidate_id = %s OR (candidate_email IS NOT NULL AND candidate_email = %s)", (candidate_id, cand_email or ""))
    except Exception:
        pass

    # 3. Delete candidate row
    cursor.execute("DELETE FROM candidates WHERE id = %s", (candidate_id,))

    # 4. Clean up associated candidate user account if role is 'candidate'
    if cand_user_id:
        try:
            cursor.execute("DELETE FROM users WHERE id = %s AND LOWER(role) = 'candidate'", (cand_user_id,))
        except Exception:
            pass
    elif cand_email:
        try:
            cursor.execute("DELETE FROM users WHERE LOWER(email) = %s AND LOWER(role) = 'candidate'", (cand_email.strip().lower(),))
        except Exception:
            pass

    # 5. Remove resume file on disk
    if resume_fn:
        resume_path = os.path.join(RESUME_FOLDER, resume_fn)
        if os.path.isfile(resume_path):
            try:
                os.remove(resume_path)
            except OSError:
                pass

    return True, "Candidate deleted successfully", cand_name


@app.route("/api/candidates/<int:candidate_id>", methods=["DELETE", "POST"])
@app.route("/api/candidate/delete/<int:candidate_id>", methods=["DELETE", "POST", "GET"])
@app.route("/api/candidates/delete/<int:candidate_id>", methods=["DELETE", "POST", "GET"])
def delete_candidate(candidate_id):
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user_role = str(session.get("role") or "").strip().lower()
    if user_role not in ["hr", "admin"]:
        return jsonify({"success": False, "message": "Access Denied: Candidate users are not authorized to delete candidate records."}), 403

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    auth_hr_id = get_authenticated_hr_id()
    is_admin = (user_role == "admin")

    try:
        cursor = connection.cursor(dictionary=True)
        success, msg, cand_name = delete_single_candidate_record(cursor, candidate_id, hr_id=auth_hr_id, is_admin=is_admin)
        if success:
            connection.commit()
            cursor.close()
            connection.close()
            return jsonify({"success": True, "message": msg, "candidate_name": cand_name})
        else:
            connection.rollback()
            cursor.close()
            connection.close()
            status_code = 403 if "Access Denied" in msg else 404
            return jsonify({"success": False, "message": msg, "candidate_name": cand_name}), status_code
    except Exception as e:
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/candidates/delete-batch", methods=["POST", "DELETE", "OPTIONS"])
def api_delete_candidates_batch():
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user_role = str(session.get("role") or "").strip().lower()
    if user_role not in ["hr", "admin"]:
        return jsonify({"success": False, "message": "Access Denied: Only authorized HR/Admin roles can delete candidate records."}), 403

    data = request.get_json(silent=True) or request.form or {}
    candidate_ids = data.get("candidate_ids") or []

    if isinstance(candidate_ids, str):
        try:
            candidate_ids = json.loads(candidate_ids)
        except Exception:
            candidate_ids = [c.strip() for c in candidate_ids.split(",") if c.strip()]

    if not candidate_ids or not isinstance(candidate_ids, list):
        return jsonify({"success": False, "message": "No candidate IDs provided for deletion."}), 400

    deleted = []
    failed = []

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    auth_hr_id = get_authenticated_hr_id()
    is_admin = (user_role == "admin")

    try:
        cursor = connection.cursor(dictionary=True)

        for cid in candidate_ids:
            try:
                cand_id_int = int(cid)
            except (ValueError, TypeError):
                failed.append({"id": cid, "name": f"Candidate #{cid}", "reason": "Invalid candidate ID format"})
                continue

            try:
                success, msg, cand_name = delete_single_candidate_record(cursor, cand_id_int, hr_id=auth_hr_id, is_admin=is_admin)
                if success:
                    connection.commit()
                    deleted.append({"id": cand_id_int, "name": cand_name})
                else:
                    connection.rollback()
                    failed.append({"id": cand_id_int, "name": cand_name, "reason": msg})
            except Exception as err:
                connection.rollback()
                failed.append({"id": cand_id_int, "name": f"Candidate #{cand_id_int}", "reason": str(err)})

        cursor.close()
        connection.close()

        return jsonify({
            "success": True,
            "deleted": deleted,
            "failed": failed,
            "deleted_count": len(deleted),
            "failed_count": len(failed),
            "deleted_ids": [d["id"] for d in deleted],
            "message": f"Processed batch deletion. Deleted {len(deleted)} candidate(s), {len(failed)} failed."
        })
    except Exception as e:
        print("ERROR in api_delete_candidates_batch:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "Logout Successful",
        "success"
    )

    resp = make_response(redirect(url_for("login")))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ============================================================
# VERIFY AUTHENTICATOR (FORGOT PASSWORD OTP)
# ============================================================

@app.route(
    "/verify-authenticator",
    methods=["POST"]
)
def verify_authenticator():
    try:
        user_input = (request.form.get("username") or "").strip()
        otp_code = (request.form.get("otp_code") or "").strip()

        if not user_input:
            flash("Username or Email is required", "error")
            return redirect(url_for("forgot_password"))

        connection = get_connection()
        if connection is None:
            flash("Database connection failed", "error")
            return redirect(url_for("forgot_password"))

        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, username, email, totp_secret, role
            FROM users
            WHERE LOWER(username)=LOWER(%s)
               OR LOWER(email)=LOWER(%s)
            LIMIT 1
            """,
            (user_input, user_input)
        )

        user = cursor.fetchone()

        if user is None:
            cursor.close()
            connection.close()
            flash("Username or Email not found", "error")
            return redirect(url_for("forgot_password"))

        if len(otp_code) != 6 or not otp_code.isdigit():
            cursor.close()
            connection.close()
            flash("Invalid OTP Code. Must be 6 digits.", "error")
            return redirect(url_for("forgot_password"))

        totp_secret = user.get("totp_secret")

        if not totp_secret:
            totp_secret = pyotp.random_base32()
            up_cur = connection.cursor()
            up_cur.execute("UPDATE users SET totp_secret = %s WHERE id = %s", (totp_secret, user["id"]))
            connection.commit()
            up_cur.close()

        cursor.close()
        connection.close()

        totp = pyotp.TOTP(totp_secret)

        if totp.verify(otp_code, valid_window=1):
            session["reset_username"] = user["username"]
            session["reset_user_id"] = user["id"]

            flash("OTP Verified Successfully. Please enter your new password.", "success")
            return redirect(url_for("reset_password"))

        flash("Invalid OTP Code. Please enter the correct code from Google Authenticator.", "error")
        return redirect(url_for("forgot_password"))

    except Exception as e:
        print("OTP ERROR:", e)
        flash("Verification Failed: " + str(e), "error")
        return redirect(url_for("forgot_password"))


# ============================================================
# RESET PASSWORD
# ============================================================

@app.route("/reset-password")
def reset_password():
    if "reset_username" not in session:
        flash("Session expired or invalid recovery attempt. Please start again.", "error")
        return redirect(url_for("forgot_password"))

    return render_template("reset_password.html")


# ============================================================
# UPDATE PASSWORD (FORGOT PASSWORD FLOW)
# ============================================================

@app.route(
    "/update-password",
    methods=["POST"]
)
def update_password():
    if "reset_username" not in session:
        flash("Session expired. Please try again.", "error")
        return redirect(url_for("forgot_password"))

    new_password = request.form.get("new_password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()

    if not new_password or not confirm_password:
        flash("All fields are required.", "error")
        return redirect(url_for("reset_password"))

    if new_password != confirm_password:
        flash("Passwords do not match.", "error")
        return redirect(url_for("reset_password"))

    if not validate_password_strength(new_password):
        flash("Password must contain uppercase, lowercase, number and special character.", "error")
        return redirect(url_for("reset_password"))

    try:
        hashed_password = bcrypt.generate_password_hash(new_password).decode("utf-8")

        connection = get_connection()
        if connection is None:
            flash("Database connection failed", "error")
            return redirect(url_for("reset_password"))

        cursor = connection.cursor()

        reset_user_id = session.get("reset_user_id")
        reset_username = session.get("reset_username")

        cursor.execute(
            """
            UPDATE users
            SET password=%s, must_change_password=0, google_authenticator_configured=1
            WHERE id=%s OR username=%s OR LOWER(email)=LOWER(%s)
            """,
            (hashed_password, reset_user_id, reset_username, reset_username)
        )

        connection.commit()
        cursor.close()
        connection.close()

        session.pop("reset_username", None)
        session.pop("reset_user_id", None)

        flash("Password Updated Successfully! Please login with your new password.", "success")
        return redirect(url_for("login"))

    except Exception as e:
        print("PASSWORD UPDATE ERROR:", e)
        flash("Password update failed: " + str(e), "error")
        return redirect(url_for("reset_password"))

# ============================================================
# CHANGE PASSWORD (FOR LOGGED-IN USERS / CANDIDATES)
# ============================================================

@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    if "logged_in" not in session:
        flash("Please login first to change your password.", "error")
        return redirect(url_for("login"))

    user_role = str(session.get("role") or "").strip().lower()
    must_change_pw = session.get("must_change_password")

    if user_role == "candidate" and must_change_pw and not session.get("cand_otp_verified"):
        flash("Please scan QR code and verify Google Authenticator OTP first.", "warning")
        return redirect(url_for("candidate_setup_2fa"))

    if request.method == "POST":
        current_password = request.form.get("current_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not current_password or not new_password or not confirm_password:
            flash("All fields are required.", "error")
            return render_template("change_password.html")

        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return render_template("change_password.html")

        if not validate_password_strength(new_password):
            flash("New password must be at least 8 characters and include uppercase, lowercase, digit, and special character.", "error")
            return render_template("change_password.html")

        user_id = session.get("user_id")
        username = session.get("username")

        try:
            connection = get_connection()
            if connection is None:
                flash("Database connection failed", "error")
                return render_template("change_password.html")

            cursor = connection.cursor(dictionary=True)

            cursor.execute("SELECT * FROM users WHERE id = %s OR username = %s OR email = %s LIMIT 1", (user_id, username, username))
            user_rec = cursor.fetchone()

            if not user_rec:
                cursor.execute("SELECT id, name, email FROM candidates WHERE email = %s LIMIT 1", (username,))
                cand_rec = cursor.fetchone()
                if cand_rec and str(cand_rec["id"]) == current_password:
                    hashed_new_pw = bcrypt.generate_password_hash(new_password).decode("utf-8")
                    clean_u = re.sub(r"[^a-z0-9._-]", "", username.split("@")[0].lower()) if "@" in str(username) else str(username)
                    totp_sec = pyotp.random_base32()
                    cursor.execute(
                        """
                        INSERT INTO users (fullname, username, email, password, role, must_change_password, google_authenticator_configured, totp_secret)
                        VALUES (%s, %s, %s, %s, 'candidate', 0, 1, %s)
                        ON DUPLICATE KEY UPDATE password = VALUES(password), must_change_password = 0, google_authenticator_configured = 1
                        """,
                        (session.get("fullname") or cand_rec.get("name") or "Candidate", clean_u, username, hashed_new_pw, totp_sec)
                    )
                    connection.commit()
                    cursor.close()
                    connection.close()

                    session["must_change_password"] = False
                    session.pop("cand_otp_verified", None)

                    flash("Password updated successfully!", "success")
                    return redirect(url_for("candidate_dashboard"))
                else:
                    cursor.close()
                    connection.close()
                    flash("Invalid current password.", "error")
                    return render_template("change_password.html")

            if not bcrypt.check_password_hash(user_rec["password"], current_password):
                if current_password != str(user_rec["id"]):
                    cursor.close()
                    connection.close()
                    flash("Invalid current password.", "error")
                    return render_template("change_password.html")

            hashed_new_pw = bcrypt.generate_password_hash(new_password).decode("utf-8")
            cursor.execute(
                "UPDATE users SET password = %s, must_change_password = 0, google_authenticator_configured = 1 WHERE id = %s",
                (hashed_new_pw, user_rec["id"])
            )
            connection.commit()
            cursor.close()
            connection.close()

            session["must_change_password"] = False
            session.pop("cand_otp_verified", None)

            flash("Password changed successfully! Your temporary password is no longer active.", "success")
            if str(session.get("role") or "").strip().lower() == "candidate":
                return redirect(url_for("candidate_dashboard"))
            else:
                return redirect(url_for("home"))

        except Exception as err:
            print("CHANGE PASSWORD ERROR:", err)
            flash("An error occurred while changing password.", "error")
            return render_template("change_password.html")

    return render_template("change_password.html")


# ============================================================
# APTITUDE EXAMINATION SYSTEM ROUTES & APIS
# ============================================================

def generate_attempt_questions_snapshot(attempt_id, exam, cursor):
    """
    Creates an attempt-specific question snapshot for candidate exams.
    Randomly selects N complete questions (default 30) from the question bank.
    Supports difficulty distribution if configured.
    Randomizes question order and option choices if configured, keeping correct answer mapping intact.
    """
    try:
        # Check if snapshot already exists
        cursor.execute("SELECT COUNT(*) as cnt FROM attempt_questions WHERE attempt_id = %s", (attempt_id,))
        res = cursor.fetchone()
        if res and (res.get("cnt") or res.get("COUNT(*)") or 0) > 0:
            return True

        # Fetch all questions available in this exam's question bank
        cursor.execute("""
            SELECT q.* FROM questions q
            JOIN exam_questions eq ON q.id = eq.question_id
            WHERE eq.exam_id = %s
            ORDER BY eq.question_order ASC, q.id ASC
        """, (exam["id"],))
        all_bank_questions = cursor.fetchall() or []

        if not all_bank_questions:
            # Fallback: check questions belonging to this exam's owner (HR)
            exam_owner_id = exam.get("user_id")
            if exam_owner_id:
                cursor.execute("SELECT * FROM questions WHERE user_id = %s ORDER BY id ASC", (exam_owner_id,))
                all_bank_questions = cursor.fetchall() or []

            # If still none, check all available questions in questions table
            if not all_bank_questions:
                cursor.execute("SELECT * FROM questions ORDER BY id ASC LIMIT 50")
                all_bank_questions = cursor.fetchall() or []

            # Auto-link questions to exam_questions so this exam has them permanently
            if all_bank_questions:
                for ord_idx, q_item in enumerate(all_bank_questions, 1):
                    cursor.execute("""
                        INSERT IGNORE INTO exam_questions (exam_id, question_id, question_order)
                        VALUES (%s, %s, %s)
                    """, (exam["id"], q_item["id"], ord_idx))

        if not all_bank_questions:
            return False

        # Determine how many questions to show (default 30 if total_questions_to_show is not set or > total available)
        target_count = exam.get("total_questions_to_show")
        if not target_count or not isinstance(target_count, int) or target_count <= 0:
            target_count = 30
        target_count = min(target_count, len(all_bank_questions))

        import random

        # Difficulty Distribution Sampling (if configured)
        easy_target = exam.get("easy_count") or 0
        medium_target = exam.get("medium_count") or 0
        hard_target = exam.get("hard_count") or 0

        selected_questions = []

        if easy_target > 0 or medium_target > 0 or hard_target > 0:
            easy_qs = [q for q in all_bank_questions if str(q.get("difficulty")).capitalize() == "Easy"]
            medium_qs = [q for q in all_bank_questions if str(q.get("difficulty")).capitalize() == "Medium"]
            hard_qs = [q for q in all_bank_questions if str(q.get("difficulty")).capitalize() == "Hard"]

            easy_sampled = random.sample(easy_qs, min(easy_target, len(easy_qs)))
            medium_sampled = random.sample(medium_qs, min(medium_target, len(medium_qs)))
            hard_sampled = random.sample(hard_qs, min(hard_target, len(hard_qs)))

            selected_questions = easy_sampled + medium_sampled + hard_sampled
            selected_ids = {q["id"] for q in selected_questions}

            # If sampled count is less than target_count, fill remaining randomly from unselected
            remaining_needed = target_count - len(selected_questions)
            if remaining_needed > 0:
                unselected = [q for q in all_bank_questions if q["id"] not in selected_ids]
                fill_sampled = random.sample(unselected, min(remaining_needed, len(unselected)))
                selected_questions.extend(fill_sampled)
        else:
            # Uniform Random Selection of complete question records
            selected_questions = random.sample(all_bank_questions, target_count)

        # Question Order Randomization (if configured)
        if exam.get("randomize_questions"):
            random.shuffle(selected_questions)

        # Option Randomization & Insertion into attempt_questions
        do_randomize_options = bool(exam.get("randomize_options"))

        for idx, q in enumerate(selected_questions, start=1):
            q_id = q["id"]
            orig_opt_a = str(q.get("option_a") or "").strip()
            orig_opt_b = str(q.get("option_b") or "").strip()
            orig_opt_c = str(q.get("option_c") or "").strip()
            orig_opt_d = str(q.get("option_d") or "").strip()
            orig_correct = str(q.get("correct_answer") or "").strip().upper()

            if do_randomize_options:
                opts_list = [
                    ("A", orig_opt_a),
                    ("B", orig_opt_b),
                    ("C", orig_opt_c),
                    ("D", orig_opt_d)
                ]
                random.shuffle(opts_list)
                keys = ["A", "B", "C", "D"]
                shuffled_map = {}
                new_correct_opt = "A"

                for new_key, (orig_key, opt_text) in zip(keys, opts_list):
                    shuffled_map[f"option_{new_key.lower()}"] = opt_text
                    if orig_key == orig_correct:
                        new_correct_opt = new_key

                opt_a_val = shuffled_map.get("option_a", orig_opt_a)
                opt_b_val = shuffled_map.get("option_b", orig_opt_b)
                opt_c_val = shuffled_map.get("option_c", orig_opt_c)
                opt_d_val = shuffled_map.get("option_d", orig_opt_d)
                final_correct = new_correct_opt
            else:
                opt_a_val = orig_opt_a
                opt_b_val = orig_opt_b
                opt_c_val = orig_opt_c
                opt_d_val = orig_opt_d
                final_correct = orig_correct

            cursor.execute("""
                INSERT INTO attempt_questions (attempt_id, question_id, question_order, option_a, option_b, option_c, option_d, correct_option)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (attempt_id, q_id, idx, opt_a_val, opt_b_val, opt_c_val, opt_d_val, final_correct))

        return True
    except Exception as e:
        print("Error generating attempt questions snapshot:", e)
        return False


def calculate_attempt_score(attempt_id, final_status='SUBMITTED'):
    """
    Computes candidate score, percentage, pass/fail status securely on the backend.
    """
    connection = get_connection()
    if not connection:
        return False
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM exam_attempts WHERE id = %s LIMIT 1", (attempt_id,))
        attempt = cursor.fetchone()
        if not attempt:
            cursor.close()
            connection.close()
            return False

        cursor.execute("SELECT * FROM exams WHERE id = %s LIMIT 1", (attempt["exam_id"],))
        exam = cursor.fetchone()
        if not exam:
            cursor.close()
            connection.close()
            return False

        # Attempt question snapshot query
        cursor.execute("""
            SELECT aq.question_id as id, aq.correct_option as correct_answer, q.marks, q.negative_marks
            FROM attempt_questions aq
            JOIN questions q ON aq.question_id = q.id
            WHERE aq.attempt_id = %s
            ORDER BY aq.question_order ASC
        """, (attempt_id,))
        questions = cursor.fetchall() or []

        # Fallback to exam bank if snapshot doesn't exist
        if not questions:
            cursor.execute("""
                SELECT q.* FROM questions q
                JOIN exam_questions eq ON q.id = eq.question_id
                WHERE eq.exam_id = %s
                ORDER BY eq.question_order ASC
            """, (exam["id"],))
            questions = cursor.fetchall() or []

        cursor.execute("SELECT * FROM attempt_answers WHERE attempt_id = %s", (attempt_id,))
        saved_ans = {a["question_id"]: a for a in cursor.fetchall()}

        total_score = 0.0
        neg_mark_val = float(exam["negative_mark_value"] or 0.25) if exam["negative_marking"] else 0.0
        total_assigned_marks = 0.0

        for q in questions:
            q_id = q["id"]
            q_mark = float(q.get("marks") or 1.0)
            total_assigned_marks += q_mark
            ans_rec = saved_ans.get(q_id)
            sel_opt = ans_rec["selected_option"] if ans_rec else None

            is_correct = 0
            marks_awarded = 0.0

            if sel_opt and str(sel_opt).strip().upper() == str(q["correct_answer"]).strip().upper():
                is_correct = 1
                marks_awarded = q_mark
            elif sel_opt:
                is_correct = 0
                marks_awarded = -neg_mark_val
            else:
                is_correct = 0
                marks_awarded = 0.0

            total_score += marks_awarded

            if ans_rec:
                cursor.execute("""
                    UPDATE attempt_answers
                    SET is_correct = %s, marks_awarded = %s
                    WHERE id = %s
                """, (is_correct, marks_awarded, ans_rec["id"]))
            else:
                cursor.execute("""
                    INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_correct, marks_awarded)
                    VALUES (%s, %s, %s, %s, %s)
                """, (attempt_id, q_id, sel_opt, is_correct, marks_awarded))

        total_marks = total_assigned_marks if total_assigned_marks > 0 else float(exam["total_marks"] or 1.0)
        percentage = max(0.0, (total_score / total_marks) * 100.0) if total_marks > 0 else 0.0
        passing_marks = float(exam["passing_marks"] or 0.0)
        passed = 1 if (total_score >= passing_marks and final_status != 'DISQUALIFIED') else 0

        cursor.execute("""
            UPDATE exam_attempts
            SET score = %s,
                percentage = %s,
                passed = %s,
                status = %s,
                submitted_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (total_score, percentage, passed, final_status, attempt_id))

        connection.commit()
        cursor.close()
        connection.close()
        return True
    except Exception as err:
        print("Notice calculating attempt score:", err)
        if connection:
            connection.close()
        return False


# --- CANDIDATE EXAM ROUTES ---

@app.route("/candidate/exam/<int:exam_id>/instructions")
def candidate_exam_instructions(exam_id):
    if "logged_in" not in session:
        flash("Please login first", "error")
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        flash("Database connection error", "error")
        return redirect(url_for("candidate_dashboard"))

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM exams WHERE id = %s AND is_published = 1 LIMIT 1", (exam_id,))
        exam = cursor.fetchone()

        if not exam:
            cursor.close()
            connection.close()
            flash("Examination not found or not published", "error")
            return redirect(url_for("candidate_dashboard"))

        cursor.execute("SELECT COUNT(*) as q_count FROM exam_questions WHERE exam_id = %s", (exam_id,))
        q_rec = cursor.fetchone()
        q_count = q_rec["q_count"] if q_rec else 0

        if q_count == 0:
            exam_owner_id = exam.get("user_id")
            if exam_owner_id:
                cursor.execute("SELECT id FROM questions WHERE user_id = %s ORDER BY id ASC", (exam_owner_id,))
                qs = cursor.fetchall()
            else:
                qs = []
            if not qs:
                cursor.execute("SELECT id FROM questions ORDER BY id ASC LIMIT 50")
                qs = cursor.fetchall()
            if qs:
                for idx, q_row in enumerate(qs, 1):
                    cursor.execute("""
                        INSERT IGNORE INTO exam_questions (exam_id, question_id, question_order)
                        VALUES (%s, %s, %s)
                    """, (exam_id, q_row["id"], idx))
                connection.commit()
                q_count = len(qs)

        cursor.close()
        connection.close()

        return render_template("exam_instructions.html", exam=exam, question_count=q_count)
    except Exception as err:
        print("Error fetching exam instructions:", err)
        flash("Error loading examination instructions", "error")
        return redirect(url_for("candidate_dashboard"))


@app.route("/candidate/exam/<int:exam_id>/camera-check")
def candidate_exam_camera_check(exam_id):
    if "logged_in" not in session:
        flash("Please login first", "error")
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        return redirect(url_for("candidate_dashboard"))

    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM exams WHERE id = %s LIMIT 1", (exam_id,))
    exam = cursor.fetchone()
    cursor.close()
    connection.close()

    if not exam:
        flash("Exam not found", "error")
        return redirect(url_for("candidate_dashboard"))

    return render_template("exam_camera_check.html", exam=exam)


@app.route("/candidate/exam/<int:exam_id>/start", methods=["POST"])
def start_candidate_exam(exam_id):
    if "logged_in" not in session:
        return redirect(url_for("login"))

    user_id = session.get("user_id")
    user_email = session.get("email") or session.get("username")

    connection = get_connection()
    if not connection:
        flash("Database error", "error")
        return redirect(url_for("candidate_dashboard"))

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM exams WHERE id = %s AND is_published = 1 LIMIT 1", (exam_id,))
        exam = cursor.fetchone()
        if not exam:
            cursor.close()
            connection.close()
            flash("Exam not available", "error")
            return redirect(url_for("candidate_dashboard"))

        cursor.execute("SELECT * FROM candidates WHERE user_id = %s OR email = %s LIMIT 1", (user_id, user_email))
        cand = cursor.fetchone()

        cand_id = cand["id"] if cand else 0
        job_id = cand.get("job_id") if cand else None
        upload_id = cand.get("upload_id") if cand else None

        cursor.execute("""
            SELECT * FROM exam_attempts
            WHERE exam_id = %s AND (candidate_id = %s OR user_id = %s)
            ORDER BY id DESC LIMIT 1
        """, (exam_id, cand_id, user_id or 0))
        att = cursor.fetchone()

        if not att:
            duration = int(exam["duration_minutes"] or 30)
            cursor.execute("""
                INSERT INTO exam_attempts (exam_id, candidate_id, user_id, job_id, upload_id, started_at, expires_at, status)
                VALUES (%s, %s, %s, %s, %s, NOW(), DATE_ADD(NOW(), INTERVAL %s MINUTE), 'IN_PROGRESS')
            """, (exam_id, cand_id, user_id or 0, job_id, upload_id, duration))
            attempt_id = cursor.lastrowid
            connection.commit()
            generate_attempt_questions_snapshot(attempt_id, exam, cursor)
            connection.commit()
        else:
            generate_attempt_questions_snapshot(att["id"], exam, cursor)
            connection.commit()

        cursor.close()
        connection.close()

        return redirect(url_for("take_candidate_exam", exam_id=exam_id))
    except Exception as err:
        print("Error starting exam attempt:", err)
        flash("Could not start examination session.", "error")
        return redirect(url_for("candidate_dashboard"))


@app.route("/candidate/exam/<int:exam_id>/take")
def take_candidate_exam(exam_id):
    if "logged_in" not in session:
        return redirect(url_for("login"))

    user_id = session.get("user_id")
    user_email = session.get("email") or session.get("username")

    connection = get_connection()
    if not connection:
        return redirect(url_for("candidate_dashboard"))

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM exams WHERE id = %s LIMIT 1", (exam_id,))
        exam = cursor.fetchone()

        cursor.execute("SELECT * FROM candidates WHERE user_id = %s OR email = %s LIMIT 1", (user_id, user_email))
        cand = cursor.fetchone()
        cand_id = cand["id"] if cand else 0

        cursor.execute("""
            SELECT * FROM exam_attempts
            WHERE exam_id = %s AND (candidate_id = %s OR user_id = %s)
            ORDER BY id DESC LIMIT 1
        """, (exam_id, cand_id, user_id or 0))
        attempt = cursor.fetchone()

        if not attempt:
            cursor.close()
            connection.close()
            flash("Please start the examination from instructions page.", "warning")
            return redirect(url_for("candidate_exam_instructions", exam_id=exam_id))

        if attempt["status"] in ["SUBMITTED", "AUTO_SUBMITTED", "TIME_EXPIRED", "DISQUALIFIED"]:
            cursor.close()
            connection.close()
            return redirect(url_for("candidate_exam_result", exam_id=exam_id))

        expires_at = attempt["expires_at"]
        now = datetime.now()
        remaining_seconds = 0

        if expires_at:
            delta = (expires_at - now).total_seconds()
            remaining_seconds = max(0, int(delta))

        if remaining_seconds <= 0:
            cursor.close()
            connection.close()
            calculate_attempt_score(attempt["id"], final_status="TIME_EXPIRED")
            return redirect(url_for("candidate_exam_result", exam_id=exam_id))

        # Ensure snapshot generated for existing attempts
        generate_attempt_questions_snapshot(attempt["id"], exam, cursor)
        connection.commit()

        # Query assigned questions from snapshot table
        cursor.execute("""
            SELECT q.id, q.question_text, aq.option_a, aq.option_b, aq.option_c, aq.option_d, q.marks, q.negative_marks
            FROM attempt_questions aq
            JOIN questions q ON aq.question_id = q.id
            WHERE aq.attempt_id = %s
            ORDER BY aq.question_order ASC
        """, (attempt["id"],))
        questions = cursor.fetchall() or []

        # Fallback 1: Exam bank questions
        if not questions:
            cursor.execute("""
                SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, q.marks, q.negative_marks
                FROM questions q
                JOIN exam_questions eq ON q.id = eq.question_id
                WHERE eq.exam_id = %s
                ORDER BY eq.question_order ASC
            """, (exam_id,))
            questions = cursor.fetchall() or []

        # Fallback 2: HR Owner's questions
        if not questions:
            exam_owner_id = exam.get("user_id")
            if exam_owner_id:
                cursor.execute("""
                    SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, q.marks, q.negative_marks
                    FROM questions q
                    WHERE q.user_id = %s
                    ORDER BY q.id ASC
                """, (exam_owner_id,))
                questions = cursor.fetchall() or []

        # Fallback 3: Any questions in bank
        if not questions:
            cursor.execute("""
                SELECT q.id, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d, q.marks, q.negative_marks
                FROM questions q
                ORDER BY q.id ASC
                LIMIT 50
            """)
            questions = cursor.fetchall() or []

        # Normalize text and strip option prefixes for candidate display
        import re
        for q in questions:
            if q.get("question_text"):
                q_text = re.sub(r'^(?:Question\s*\d+|Q\s*\d+|\d+)[\.\:\)]\s*', '', str(q["question_text"]), flags=re.IGNORECASE).strip()
                q["question_text"] = " ".join([l.strip() for l in q_text.split("\n") if l.strip()]).strip()

            for opt_key in ["option_a", "option_b", "option_c", "option_d"]:
                if q.get(opt_key):
                    opt_val = str(q[opt_key]).strip()
                    opt_val = re.sub(r'^(?:[A-D][\.\:\)]|\([A-D]\)|\[[A-D]\])\s*', '', opt_val, flags=re.IGNORECASE).strip()
                    q[opt_key] = " ".join([l.strip() for l in opt_val.split("\n") if l.strip()]).strip()

            q["options"] = [
                {"key": "A", "text": q.get("option_a") or ""},
                {"key": "B", "text": q.get("option_b") or ""},
                {"key": "C", "text": q.get("option_c") or ""},
                {"key": "D", "text": q.get("option_d") or ""}
            ]

        # Apply question randomization if configured
        if exam and exam.get("randomize_questions"):
            import random
            rng = random.Random(attempt["id"])
            rng.shuffle(questions)

        # Apply total questions limit if configured
        total_show = exam.get("total_questions_to_show") if exam else None
        if total_show and isinstance(total_show, int) and total_show > 0 and total_show < len(questions):
            questions = questions[:total_show]

        cursor.execute("SELECT * FROM attempt_answers WHERE attempt_id = %s", (attempt["id"],))
        saved_ans = cursor.fetchall()

        cursor.close()
        connection.close()

        return render_template(
            "exam_portal.html",
            exam=exam,
            attempt=attempt,
            questions=questions,
            saved_answers=saved_ans,
            remaining_seconds=remaining_seconds
        )
    except Exception as err:
        print("Error loading exam portal:", err)
        flash("Error loading examination portal.", "error")
        return redirect(url_for("candidate_dashboard"))


@app.route("/api/exam/attempt/<int:attempt_id>/save-answer", methods=["POST"])
def api_save_attempt_answer(attempt_id):
    data = request.get_json() or {}
    question_id = data.get("question_id")
    selected_option = data.get("selected_option")
    is_marked_for_review = data.get("is_marked_for_review", 0)

    if not question_id:
        return jsonify({"success": False, "message": "Missing question_id"}), 400

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection error"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT id, candidate_id, user_id, status FROM exam_attempts WHERE id = %s LIMIT 1", (attempt_id,))
        att = cursor.fetchone()

        if not att:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Attempt not found"}), 404

        user_role = str(session.get("role") or "").strip().lower()
        if user_role == "candidate":
            current_user_id = resolve_user_id()
            user_email = session.get("email") or session.get("username")
            cursor.execute("SELECT id, user_id, email FROM candidates WHERE id = %s LIMIT 1", (att["candidate_id"],))
            cand_rec = cursor.fetchone()
            if att.get("user_id") != current_user_id and (not cand_rec or (cand_rec.get("user_id") != current_user_id and cand_rec.get("email") != user_email)):
                cursor.close()
                connection.close()
                return jsonify({"success": False, "message": "Access Denied: Attempt does not belong to user."}), 403

        if att["status"] != "IN_PROGRESS":
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Attempt not active"}), 400

        cursor.execute("SELECT id FROM attempt_answers WHERE attempt_id = %s AND question_id = %s LIMIT 1", (attempt_id, question_id))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE attempt_answers
                SET selected_option = %s, is_marked_for_review = %s
                WHERE id = %s
            """, (selected_option, is_marked_for_review, existing["id"]))
        else:
            cursor.execute("""
                INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_marked_for_review)
                VALUES (%s, %s, %s, %s)
            """, (attempt_id, question_id, selected_option, is_marked_for_review))

        cursor.execute("UPDATE exam_attempts SET last_activity = NOW() WHERE id = %s", (attempt_id,))

        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"success": True})
    except Exception as err:
        print("Error autosaving answer:", err)
        return jsonify({"success": False, "message": str(err)}), 500


@app.route("/api/exam/attempt/<int:attempt_id>/security-event", methods=["POST"])
def api_log_security_event(attempt_id):
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json() or {}
    violation_type = data.get("violation_type", "SECURITY_VIOLATION")
    details = data.get("details", "")

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database error"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT ea.*, ex.allowed_warnings, ex.auto_submit_on_violation
            FROM exam_attempts ea
            JOIN exams ex ON ea.exam_id = ex.id
            WHERE ea.id = %s LIMIT 1
        """, (attempt_id,))
        attempt = cursor.fetchone()

        if not attempt or attempt["status"] != "IN_PROGRESS":
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Attempt not active"}), 400

        user_role = str(session.get("role") or "").strip().lower()
        if user_role == "candidate":
            current_user_id = resolve_user_id()
            user_email = session.get("email") or session.get("username")
            cursor.execute("SELECT id, user_id, email FROM candidates WHERE id = %s LIMIT 1", (attempt["candidate_id"],))
            cand_rec = cursor.fetchone()
            if attempt.get("user_id") != current_user_id and (not cand_rec or (cand_rec.get("user_id") != current_user_id and cand_rec.get("email") != user_email)):
                cursor.close()
                connection.close()
                return jsonify({"success": False, "message": "Access Denied: Attempt does not belong to user."}), 403

        new_warning_count = int(attempt["warning_count"] or 0) + 1
        max_allowed = int(attempt["allowed_warnings"] or 3)

        cursor.execute("""
            INSERT INTO security_events (attempt_id, exam_id, candidate_id, violation_type, warning_number, details)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (attempt_id, attempt["exam_id"], attempt["candidate_id"], violation_type, new_warning_count, details))

        cursor.execute("UPDATE exam_attempts SET warning_count = %s WHERE id = %s", (new_warning_count, attempt_id))
        connection.commit()

        if new_warning_count >= max_allowed and attempt["auto_submit_on_violation"]:
            cursor.close()
            connection.close()
            calculate_attempt_score(attempt_id, final_status="DISQUALIFIED")
            return jsonify({
                "success": True,
                "warning_count": new_warning_count,
                "auto_submitted": True
            })

        cursor.close()
        connection.close()
        return jsonify({
            "success": True,
            "warning_count": new_warning_count,
            "auto_submitted": False
        })
    except Exception as err:
        print("Error logging security event:", err)
        return jsonify({"success": False, "message": str(err)}), 500


@app.route("/api/exam/attempt/<int:attempt_id>/submit", methods=["POST"])
def api_submit_attempt(attempt_id):
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    user_role = str(session.get("role") or "").strip().lower()
    if user_role == "candidate":
        current_user_id = resolve_user_id()
        user_email = session.get("email") or session.get("username")
        conn_chk = get_connection()
        if conn_chk:
            cur_chk = conn_chk.cursor(dictionary=True)
            cur_chk.execute("SELECT id, candidate_id, user_id FROM exam_attempts WHERE id = %s LIMIT 1", (attempt_id,))
            att_chk = cur_chk.fetchone()
            if att_chk:
                cur_chk.execute("SELECT id, user_id, email FROM candidates WHERE id = %s LIMIT 1", (att_chk["candidate_id"],))
                cand_rec = cur_chk.fetchone()
                if att_chk.get("user_id") != current_user_id and (not cand_rec or (cand_rec.get("user_id") != current_user_id and cand_rec.get("email") != user_email)):
                    cur_chk.close()
                    conn_chk.close()
                    return jsonify({"success": False, "message": "Access Denied: Attempt does not belong to user."}), 403
            cur_chk.close()
            conn_chk.close()

    data = request.get_json() or {}
    final_status = data.get("status", "SUBMITTED")

    success = calculate_attempt_score(attempt_id, final_status=final_status)
    if success:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "Error finalizing score"}), 500


@app.route("/candidate/exam/<int:exam_id>/submit", methods=["POST"])
def submit_candidate_exam(exam_id):
    if "logged_in" not in session:
        return redirect(url_for("login"))

    user_id = session.get("user_id")
    user_email = session.get("email") or session.get("username")

    connection = get_connection()
    if not connection:
        flash("Database connection failed.", "error")
        return redirect(url_for("candidate_dashboard"))

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM candidates WHERE user_id = %s OR email = %s LIMIT 1", (user_id, user_email))
        cand = cursor.fetchone()
        cand_id = cand["id"] if cand else 0

        cursor.execute("""
            SELECT * FROM exam_attempts
            WHERE exam_id = %s AND (candidate_id = %s OR user_id = %s)
            ORDER BY id DESC LIMIT 1
        """, (exam_id, cand_id, user_id or 0))
        attempt = cursor.fetchone()

        if not attempt:
            cursor.close()
            connection.close()
            flash("No active examination attempt found.", "error")
            return redirect(url_for("candidate_dashboard"))

        attempt_id = attempt["id"]

        # Parse submitted answers if passed via form
        answers_json_str = request.form.get("answers_json")
        if answers_json_str:
            try:
                answers_dict = json.loads(answers_json_str)
                for q_id_str, selected_opt in answers_dict.items():
                    try:
                        q_id = int(q_id_str)
                        cursor.execute("SELECT id FROM attempt_answers WHERE attempt_id = %s AND question_id = %s LIMIT 1", (attempt_id, q_id))
                        exist = cursor.fetchone()
                        if exist:
                            cursor.execute("UPDATE attempt_answers SET selected_option = %s WHERE id = %s", (selected_opt, exist["id"]))
                        else:
                            cursor.execute("INSERT INTO attempt_answers (attempt_id, question_id, selected_option, is_marked_for_review) VALUES (%s, %s, %s, 0)", (attempt_id, q_id, selected_opt))
                    except Exception as ans_err:
                        print("Notice parsing answer item on submit:", ans_err)
                connection.commit()
            except Exception as j_err:
                print("Notice parsing answers_json on submit:", j_err)

        sub_reason = request.form.get("submission_reason", "MANUAL_SUBMIT")
        final_status = "AUTO_SUBMITTED" if "AUTO" in sub_reason.upper() else "SUBMITTED"
        if sub_reason == "DISQUALIFIED":
            final_status = "DISQUALIFIED"

        cursor.close()
        connection.close()

        calculate_attempt_score(attempt_id, final_status=final_status)
        flash("Examination submitted successfully!", "success")
        return redirect(url_for("candidate_exam_result", exam_id=exam_id))
    except Exception as e:
        print("Error in submit_candidate_exam:", e)
        if connection:
            connection.close()
        flash("Error recording exam submission.", "error")
        return redirect(url_for("candidate_exam_result", exam_id=exam_id))


@app.route("/candidate/exam/<int:exam_id>/result")
def candidate_exam_result(exam_id):
    if "logged_in" not in session:
        return redirect(url_for("login"))

    user_id = session.get("user_id")
    user_email = session.get("email") or session.get("username")

    connection = get_connection()
    if not connection:
        return redirect(url_for("candidate_dashboard"))

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM exams WHERE id = %s LIMIT 1", (exam_id,))
        exam = cursor.fetchone()

        cursor.execute("SELECT * FROM candidates WHERE user_id = %s OR email = %s LIMIT 1", (user_id, user_email))
        cand = cursor.fetchone()
        cand_id = cand["id"] if cand else 0

        cursor.execute("""
            SELECT * FROM exam_attempts
            WHERE exam_id = %s AND (candidate_id = %s OR user_id = %s)
            ORDER BY id DESC LIMIT 1
        """, (exam_id, cand_id, user_id or 0))
        attempt = cursor.fetchone()

        if not attempt:
            cursor.close()
            connection.close()
            flash("No attempt found", "error")
            return redirect(url_for("candidate_dashboard"))

        visibility = str(exam["result_visibility"] or "IMMEDIATE").upper()
        is_visible = True

        if visibility == "HIDDEN":
            is_visible = False
        elif visibility == "AFTER_END_DATE":
            if exam["end_time"] and datetime.now() < exam["end_time"]:
                is_visible = False

        cursor.execute("SELECT COUNT(*) as c FROM attempt_answers WHERE attempt_id = %s AND is_correct = 1", (attempt["id"],))
        corr_rec = cursor.fetchone()
        correct_count = corr_rec["c"] if corr_rec else 0

        cursor.execute("SELECT COUNT(*) as c FROM attempt_answers WHERE attempt_id = %s AND is_correct = 0 AND selected_option IS NOT NULL", (attempt["id"],))
        wrg_rec = cursor.fetchone()
        wrong_count = wrg_rec["c"] if wrg_rec else 0

        cursor.execute("SELECT COUNT(*) as c FROM exam_questions WHERE exam_id = %s", (exam_id,))
        q_tot = cursor.fetchone()
        total_qs = q_tot["c"] if q_tot else 0
        unanswered_count = max(0, total_qs - (correct_count + wrong_count))

        cursor.close()
        connection.close()

        return render_template(
            "exam_result.html",
            exam=exam,
            attempt=attempt,
            is_visible=is_visible,
            correct_count=correct_count,
            wrong_count=wrong_count,
            unanswered_count=unanswered_count
        )
    except Exception as err:
        print("Error viewing candidate result:", err)
        flash("Error loading result page.", "error")
        return redirect(url_for("candidate_dashboard"))


# --- HR EXAM MANAGEMENT ROUTES ---

@app.route("/hr/exams")
def hr_exams_list():
    if "logged_in" not in session or session.get("role") != "hr":
        flash("HR access required", "error")
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        return render_template("hr_exams.html", exams=[])

    try:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role") == "admin")
        if is_admin:
            cursor.execute("SELECT * FROM exams ORDER BY id DESC")
        else:
            cursor.execute("SELECT * FROM exams WHERE user_id = %s ORDER BY id DESC", (auth_hr_id,))
        exams = cursor.fetchall()

        for ex in exams:
            cursor.execute("SELECT COUNT(*) as c FROM exam_questions WHERE exam_id = %s", (ex["id"],))
            q_c = cursor.fetchone()
            ex["question_count"] = q_c["c"] if q_c else 0

        cursor.close()
        connection.close()
        return render_template("hr_exams.html", exams=exams)
    except Exception as err:
        print("Error fetching HR exams:", err)
        return render_template("hr_exams.html", exams=[])


@app.route("/hr/exams/create", methods=["GET", "POST"])
def hr_create_exam():
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        duration_minutes = int(request.form.get("duration_minutes") or 30)
        total_marks = float(request.form.get("total_marks") or 30.0)
        passing_marks = float(request.form.get("passing_marks") or 18.0)
        negative_marking = int(request.form.get("negative_marking") or 0)
        negative_mark_value = float(request.form.get("negative_mark_value") or 0.25)
        allowed_warnings = int(request.form.get("allowed_warnings") or 3)
        auto_submit_on_violation = int(request.form.get("auto_submit_on_violation") or 1)
        camera_required = int(request.form.get("camera_required") or 1)
        fullscreen_required = int(request.form.get("fullscreen_required") or 1)
        result_visibility = request.form.get("result_visibility", "IMMEDIATE")
        start_time = request.form.get("start_time") or None
        end_time = request.form.get("end_time") or None

        randomize_questions = int(request.form.get("randomize_questions") or 1)
        randomize_options = int(request.form.get("randomize_options") or 1)
        total_qs = request.form.get("total_questions_to_show")
        total_questions_to_show = int(total_qs) if (total_qs and total_qs.isdigit()) else 30
        easy_count = int(request.form.get("easy_count") or 0)
        medium_count = int(request.form.get("medium_count") or 0)
        hard_count = int(request.form.get("hard_count") or 0)

        connection = get_connection()
        if connection:
            cursor = connection.cursor()
            cursor.execute("""
                INSERT INTO exams (
                    user_id, title, description, duration_minutes, total_marks, passing_marks,
                    negative_marking, negative_mark_value, allowed_warnings, auto_submit_on_violation,
                    camera_required, fullscreen_required, result_visibility, start_time, end_time,
                    randomize_questions, randomize_options, total_questions_to_show,
                    easy_count, medium_count, hard_count, is_published
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            """, (
                session.get("user_id"), title, description, duration_minutes, total_marks, passing_marks,
                negative_marking, negative_mark_value, allowed_warnings, auto_submit_on_violation,
                camera_required, fullscreen_required, result_visibility, start_time, end_time,
                randomize_questions, randomize_options, total_questions_to_show,
                easy_count, medium_count, hard_count
            ))
            connection.commit()
            cursor.close()
            connection.close()
            flash("Examination created successfully!", "success")
            return redirect(url_for("hr_exams_list"))

    return render_template("hr_exam_form.html", is_edit=False, exam={})


@app.route("/hr/exams/upload-pdf-page", methods=["GET"])
def hr_upload_exam_pdf_page():
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))
    return render_template("hr_exam_pdf_upload.html")


@app.route("/hr/exams/upload-pdf", methods=["POST"])
def hr_upload_exam_pdf():
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    pdf_file = request.files.get("pdf_file")
    if not pdf_file or not pdf_file.filename:
        flash("Please select a PDF file.", "error")
        return redirect(url_for("hr_upload_exam_pdf_page"))

    if not pdf_file.filename.lower().endswith(".pdf"):
        flash("Only .pdf files are supported.", "error")
        return redirect(url_for("hr_upload_exam_pdf_page"))

    exam_config = {
        "title": str(request.form.get("title") or "Aptitude Exam (PDF Import)").strip(),
        "description": str(request.form.get("description") or "").strip(),
        "duration_minutes": int(request.form.get("duration_minutes") or 30),
        "total_marks": float(request.form.get("total_marks") or 30.0),
        "passing_marks": float(request.form.get("passing_marks") or 18.0),
        "negative_marking": int(request.form.get("negative_marking") or 0),
        "randomize_questions": int(request.form.get("randomize_questions") or 1),
        "randomize_options": int(request.form.get("randomize_options") or 1),
        "total_questions_to_show": request.form.get("total_questions_to_show") or None,
        "allowed_warnings": int(request.form.get("allowed_warnings") or 3),
        "auto_submit_on_violation": int(request.form.get("auto_submit_on_violation") or 1),
        "camera_required": int(request.form.get("camera_required") or 1),
        "fullscreen_required": int(request.form.get("fullscreen_required") or 1)
    }

    try:
        parsed_result = parse_exam_pdf_file(pdf_file)
        if parsed_result.get("error_message") or not parsed_result.get("questions"):
            flash(parsed_result.get("error_message") or "Could not extract any questions from the uploaded PDF.", "error")
            return redirect(url_for("hr_upload_exam_pdf_page"))

        return render_template(
            "hr_exam_pdf_review.html",
            exam_config=exam_config,
            questions=parsed_result["questions"],
            total_count=parsed_result["total_count"],
            valid_count=parsed_result["valid_count"],
            review_count=parsed_result["review_count"]
        )
    except Exception as e:
        print("Error processing PDF exam:", e)
        flash(f"PDF processing failed: {str(e)}", "error")
        return redirect(url_for("hr_upload_exam_pdf_page"))


@app.route("/hr/exams/publish-pdf-exam", methods=["POST"])
def hr_publish_pdf_exam():
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    try:
        title = request.form.get("title") or "Aptitude Assessment"
        description = request.form.get("description") or ""
        duration_minutes = int(request.form.get("duration_minutes") or 30)
        total_marks = float(request.form.get("total_marks") or 30.0)
        passing_marks = float(request.form.get("passing_marks") or 18.0)
        negative_marking = int(request.form.get("negative_marking") or 0)
        randomize_questions = int(request.form.get("randomize_questions") or 1)
        randomize_options = int(request.form.get("randomize_options") or 1)
        total_qs_show = request.form.get("total_questions_to_show")
        total_questions_to_show = int(total_qs_show) if total_qs_show and total_qs_show.isdigit() else None
        allowed_warnings = int(request.form.get("allowed_warnings") or 3)
        auto_submit_on_violation = int(request.form.get("auto_submit_on_violation") or 1)
        camera_required = int(request.form.get("camera_required") or 1)
        fullscreen_required = int(request.form.get("fullscreen_required") or 1)

        question_count = int(request.form.get("question_count") or 0)
        if question_count <= 0:
            flash("Cannot publish exam without any questions.", "error")
            return redirect(url_for("hr_upload_exam_pdf_page"))

        connection = get_connection()
        if not connection:
            flash("Database connection error.", "error")
            return redirect(url_for("hr_exams_list"))

        cursor = connection.cursor()
        auth_hr_id = get_authenticated_hr_id()

        # 1. Insert Exam record
        cursor.execute("""
            INSERT INTO exams (
                user_id, title, description, duration_minutes, total_marks, passing_marks,
                negative_marking, allowed_warnings, auto_submit_on_violation, camera_required,
                fullscreen_required, result_visibility, is_published, randomize_questions,
                randomize_options, total_questions_to_show
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'IMMEDIATE', 1, %s, %s, %s)
        """, (
            auth_hr_id, title, description, duration_minutes, total_marks, passing_marks,
            negative_marking, allowed_warnings, auto_submit_on_violation, camera_required,
            fullscreen_required, randomize_questions, randomize_options, total_questions_to_show
        ))
        exam_id = cursor.lastrowid

        # 2. Insert Questions & Link
        inserted_q_ids = []
        for i in range(1, question_count + 1):
            q_text = str(request.form.get(f"q_text_{i}") or "").strip()
            opt_a = str(request.form.get(f"q_opt_a_{i}") or "").strip()
            opt_b = str(request.form.get(f"q_opt_b_{i}") or "").strip()
            opt_c = str(request.form.get(f"q_opt_c_{i}") or "").strip()
            opt_d = str(request.form.get(f"q_opt_d_{i}") or "").strip()
            correct_ans = str(request.form.get(f"q_ans_{i}") or "A").strip().upper()
            q_marks = float(request.form.get(f"q_marks_{i}") or 1.0)
            q_neg = float(request.form.get(f"q_neg_{i}") or 0.0)
            q_diff = str(request.form.get(f"q_diff_{i}") or "Medium").capitalize()

            if not q_text or not opt_a or not opt_b or not opt_c or not opt_d:
                continue

            cursor.execute("""
                INSERT INTO questions (
                    user_id, question_text, option_a, option_b, option_c, option_d,
                    correct_answer, marks, negative_marks, category, difficulty
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Aptitude', %s)
            """, (auth_hr_id, q_text, opt_a, opt_b, opt_c, opt_d, correct_ans, q_marks, q_neg, q_diff))
            q_id = cursor.lastrowid
            inserted_q_ids.append(q_id)

            cursor.execute("""
                INSERT INTO exam_questions (exam_id, question_id, question_order)
                VALUES (%s, %s, %s)
            """, (exam_id, q_id, i))

        # 3. Assign exam to candidate pool so candidates see notifications (scoped to this HR)
        cursor.execute("""
            SELECT id FROM candidates 
            WHERE (registration_status IN ('Registered', 'Processed') OR user_id IS NOT NULL)
              AND (hr_id = %s OR (hr_id IS NULL AND user_id = %s))
        """, (auth_hr_id, auth_hr_id))
        all_cands = cursor.fetchall()
        for cand_row in all_cands:
            cand_id_val = cand_row[0]
            cursor.execute("""
                INSERT INTO exam_assignments (exam_id, candidate_id, status)
                VALUES (%s, %s, 'ASSIGNED')
                ON DUPLICATE KEY UPDATE status='ASSIGNED'
            """, (exam_id, cand_id_val))

        connection.commit()
        cursor.close()
        connection.close()

        flash(f"🎉 PDF Exam '{title}' published successfully with {len(inserted_q_ids)} questions!", "success")
        return redirect(url_for("hr_exams_list"))

    except Exception as err:
        print("Error publishing PDF exam:", err)
        flash(f"Publish failed: {str(err)}", "error")
        return redirect(url_for("hr_exams_list"))


@app.route("/hr/exams/<int:exam_id>/edit", methods=["GET", "POST"])
def hr_edit_exam(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        return redirect(url_for("hr_exams_list"))

    cursor = connection.cursor(dictionary=True)
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")
    exam = verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin)

    if not exam:
        cursor.close()
        connection.close()
        flash("Exam not found or unauthorized", "error")
        return redirect(url_for("hr_exams_list"))

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        duration_minutes = int(request.form.get("duration_minutes") or 30)
        total_marks = float(request.form.get("total_marks") or 30.0)
        passing_marks = float(request.form.get("passing_marks") or 18.0)
        negative_marking = int(request.form.get("negative_marking") or 0)
        negative_mark_value = float(request.form.get("negative_mark_value") or 0.25)
        allowed_warnings = int(request.form.get("allowed_warnings") or 3)
        auto_submit_on_violation = int(request.form.get("auto_submit_on_violation") or 1)
        camera_required = int(request.form.get("camera_required") or 1)
        fullscreen_required = int(request.form.get("fullscreen_required") or 1)
        result_visibility = request.form.get("result_visibility", "IMMEDIATE")
        start_time = request.form.get("start_time") or None
        end_time = request.form.get("end_time") or None

        cursor.execute("""
            UPDATE exams
            SET title=%s, description=%s, duration_minutes=%s, total_marks=%s, passing_marks=%s,
                negative_marking=%s, negative_mark_value=%s, allowed_warnings=%s, auto_submit_on_violation=%s,
                camera_required=%s, fullscreen_required=%s, result_visibility=%s, start_time=%s, end_time=%s
            WHERE id=%s
        """, (title, description, duration_minutes, total_marks, passing_marks, negative_marking, negative_mark_value, allowed_warnings, auto_submit_on_violation, camera_required, fullscreen_required, result_visibility, start_time, end_time, exam_id))

        connection.commit()
        cursor.close()
        connection.close()
        flash("Examination updated successfully!", "success")
        return redirect(url_for("hr_exams_list"))

    exam["start_time_str"] = exam["start_time"].strftime("%Y-%m-%dT%H:%M") if exam["start_time"] else ""
    exam["end_time_str"] = exam["end_time"].strftime("%Y-%m-%dT%H:%M") if exam["end_time"] else ""

    cursor.close()
    connection.close()
    return render_template("hr_exam_form.html", is_edit=True, exam=exam)


@app.route("/hr/exams/<int:exam_id>/toggle-publish", methods=["POST"])
def hr_toggle_publish_exam(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if connection:
        cursor = connection.cursor()
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role") == "admin")
        if not verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin):
            cursor.close()
            connection.close()
            flash("Unauthorized access to exam", "error")
            return redirect(url_for("hr_exams_list"))

        cursor.execute("UPDATE exams SET is_published = NOT is_published WHERE id = %s", (exam_id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash("Exam status updated", "success")

    return redirect(url_for("hr_exams_list"))


@app.route("/hr/exams/<int:exam_id>/delete", methods=["POST"])
def hr_delete_exam(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if connection:
        cursor = connection.cursor()
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role") == "admin")
        if not verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin):
            cursor.close()
            connection.close()
            flash("Unauthorized access to exam", "error")
            return redirect(url_for("hr_exams_list"))

        cursor.execute("DELETE FROM exams WHERE id = %s", (exam_id,))
        cursor.execute("DELETE FROM exam_questions WHERE exam_id = %s", (exam_id,))
        cursor.execute("DELETE FROM exam_assignments WHERE exam_id = %s", (exam_id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash("Exam deleted", "success")

    return redirect(url_for("hr_exams_list"))


@app.route("/hr/questions")
def hr_question_bank():
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    questions = []
    if connection:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role") == "admin")
        if is_admin:
            cursor.execute("SELECT * FROM questions ORDER BY id DESC")
        else:
            cursor.execute("SELECT * FROM questions WHERE user_id = %s ORDER BY id DESC", (auth_hr_id,))
        questions = cursor.fetchall()
        cursor.close()
        connection.close()

    return render_template("hr_questions.html", questions=questions, exam=None)


@app.route("/hr/exams/<int:exam_id>/questions")
def hr_exam_questions(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        return redirect(url_for("hr_exams_list"))

    cursor = connection.cursor(dictionary=True)
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")
    exam = verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin)
    if not exam:
        cursor.close()
        connection.close()
        flash("Exam not found or unauthorized", "error")
        return redirect(url_for("hr_exams_list"))

    cursor.execute("""
        SELECT q.* FROM questions q
        JOIN exam_questions eq ON q.id = eq.question_id
        WHERE eq.exam_id = %s
        ORDER BY eq.question_order ASC
    """, (exam_id,))
    questions = cursor.fetchall()

    cursor.close()
    connection.close()
    return render_template("hr_questions.html", questions=questions, exam=exam)


@app.route("/hr/questions/add", methods=["POST"])
def hr_add_question():
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    exam_id = request.form.get("exam_id")
    question_text = request.form.get("question_text")
    option_a = request.form.get("option_a")
    option_b = request.form.get("option_b")
    option_c = request.form.get("option_c")
    option_d = request.form.get("option_d")
    correct_answer = request.form.get("correct_answer", "A").upper()
    marks = float(request.form.get("marks") or 1.0)
    negative_marks = float(request.form.get("negative_marks") or 0.0)

    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")

    connection = get_connection()
    if connection:
        cursor = connection.cursor()

        # If linking to an exam, verify exam ownership
        if exam_id and str(exam_id).isdigit():
            if not verify_exam_ownership(cursor, int(exam_id), auth_hr_id, is_admin):
                cursor.close()
                connection.close()
                flash("Unauthorized access to exam", "error")
                return redirect(url_for("hr_question_bank"))

        cursor.execute("""
            INSERT INTO questions (user_id, question_text, option_a, option_b, option_c, option_d, correct_answer, marks, negative_marks)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (auth_hr_id, question_text, option_a, option_b, option_c, option_d, correct_answer, marks, negative_marks))

        q_id = cursor.lastrowid

        if exam_id and str(exam_id).isdigit():
            cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (int(exam_id), q_id))

        connection.commit()
        cursor.close()
        connection.close()
        flash("MCQ Question added successfully", "success")

    if exam_id and str(exam_id).isdigit():
        return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
    return redirect(url_for("hr_question_bank"))


@app.route("/api/hr/questions/upload-pdf", methods=["POST"])
@app.route("/hr/questions/upload-pdf", methods=["POST"])
def hr_upload_questions_pdf():
    if "logged_in" not in session or session.get("role") != "hr":
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        return redirect(url_for("login"))

    exam_id = request.form.get("exam_id")
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")
    is_ajax = request.is_json or (request.headers.get("X-Requested-With") == "XMLHttpRequest") or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html)

    if exam_id and str(exam_id).isdigit():
        chk_conn = get_connection()
        if chk_conn:
            chk_cur = chk_conn.cursor(dictionary=True)
            owned_exam = verify_exam_ownership(chk_cur, int(exam_id), auth_hr_id, is_admin)
            chk_cur.close()
            chk_conn.close()
            if not owned_exam:
                if is_ajax:
                    return jsonify({"success": False, "message": "Unauthorized access to exam"}), 403
                flash("Unauthorized access to exam", "error")
                return redirect(url_for("hr_question_bank"))

    pdf_file = request.files.get("pdf_file") or request.files.get("file") or request.files.get("pdf")

    if not pdf_file or not pdf_file.filename:
        msg = "Please select a valid PDF file."
        if is_ajax:
            return jsonify({"success": False, "message": msg}), 400
        flash(msg, "error")
        if exam_id and str(exam_id).isdigit():
            return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
        return redirect(url_for("hr_question_bank"))

    original_filename = secure_filename(pdf_file.filename) or "uploaded_questions.pdf"
    if not original_filename.lower().endswith(".pdf"):
        msg = "Please select a valid PDF file."
        if is_ajax:
            return jsonify({"success": False, "message": msg}), 400
        flash(msg, "error")
        if exam_id and str(exam_id).isdigit():
            return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
        return redirect(url_for("hr_question_bank"))

    # Save physical PDF file to storage structure: uploads/exams/<exam_id or 'question_bank'>/
    target_folder_name = str(exam_id) if (exam_id and str(exam_id).isdigit()) else "question_bank"
    storage_dir = (Path(UPLOAD_FOLDER) / "exams" / target_folder_name).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = int(time.time())
    rand_id = uuid.uuid4().hex[:6]
    unique_saved_filename = f"questions_{timestamp_str}_{rand_id}_{original_filename}"
    saved_pdf_path = storage_dir / unique_saved_filename

    try:
        pdf_file.save(str(saved_pdf_path))
        file_size_bytes = saved_pdf_path.stat().st_size if saved_pdf_path.is_file() else 0

        logger.info(
            "PDF UPLOAD SUCCESS filename=%s stored_path=%s size_bytes=%s upload_id=UP-%s-%s status=SAVED",
            original_filename, saved_pdf_path, file_size_bytes, timestamp_str, rand_id
        )
    except Exception as save_err:
        logger.error("Failed saving uploaded PDF file: %s", save_err)
        msg = f"Failed to save uploaded PDF file: {str(save_err)}"
        if is_ajax:
            return jsonify({"success": False, "message": msg}), 500
        flash(msg, "error")
        if exam_id and str(exam_id).isdigit():
            return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
        return redirect(url_for("hr_question_bank"))

    # Parse questions using PDF processing service
    try:
        parsed_result = parse_exam_pdf_file(str(saved_pdf_path))
        
        if parsed_result.get("error_message") or not parsed_result.get("questions"):
            msg = parsed_result.get("error_message") or "PDF uploaded successfully, but questions could not be extracted."
            if is_ajax:
                return jsonify({
                    "success": False,
                    "status": "EXTRACTION_FAILED",
                    "filename": original_filename,
                    "message": msg
                }), 400
            flash(msg, "error")
            if exam_id and str(exam_id).isdigit():
                return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
            return redirect(url_for("hr_question_bank"))

        if is_ajax:
            return jsonify({
                "success": True,
                "filename": original_filename,
                "questions_found": parsed_result["total_count"],
                "valid_count": parsed_result["valid_count"],
                "review_count": parsed_result["review_count"],
                "status": "PROCESSED",
                "questions": parsed_result["questions"]
            })

        return render_template(
            "hr_questions_pdf_review.html",
            exam_id=exam_id,
            questions=parsed_result["questions"],
            total_count=parsed_result["total_count"],
            valid_count=parsed_result["valid_count"],
            review_count=parsed_result["review_count"]
        )
    except Exception as e:
        logger.error("Error processing PDF questions: %s", e)
        msg = f"PDF processing failed: {str(e)}"
        if is_ajax:
            return jsonify({"success": False, "message": msg}), 500
        flash(msg, "error")
        if exam_id and str(exam_id).isdigit():
            return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
        return redirect(url_for("hr_question_bank"))


@app.route("/hr/questions/save-pdf-questions", methods=["POST"])
def hr_save_pdf_questions():
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    try:
        exam_id = request.form.get("exam_id")
        question_count = int(request.form.get("question_count") or 0)

        if question_count <= 0:
            flash("No questions to save.", "error")
            if exam_id and str(exam_id).isdigit():
                return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
            return redirect(url_for("hr_question_bank"))

        connection = get_connection()
        if not connection:
            flash("Database connection error.", "error")
            return redirect(url_for("hr_question_bank"))

        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role") == "admin")

        if exam_id and str(exam_id).isdigit():
            if not verify_exam_ownership(cursor, int(exam_id), auth_hr_id, is_admin):
                cursor.close()
                connection.close()
                flash("Unauthorized access to exam", "error")
                return redirect(url_for("hr_question_bank"))

        cursor.close()
        cursor = connection.cursor()
        saved_count = 0

        for i in range(1, question_count + 1):
            q_text = str(request.form.get(f"q_text_{i}") or "").strip()
            opt_a = str(request.form.get(f"q_opt_a_{i}") or "").strip()
            opt_b = str(request.form.get(f"q_opt_b_{i}") or "").strip()
            opt_c = str(request.form.get(f"q_opt_c_{i}") or "").strip()
            opt_d = str(request.form.get(f"q_opt_d_{i}") or "").strip()
            correct_ans = str(request.form.get(f"q_ans_{i}") or "A").strip().upper()
            q_diff = str(request.form.get(f"q_diff_{i}") or "Medium").capitalize()
            q_marks = float(request.form.get(f"q_marks_{i}") or 1.0)
            q_neg = float(request.form.get(f"q_neg_{i}") or 0.0)

            if not q_text or not opt_a or not opt_b or not opt_c or not opt_d:
                continue

            cursor.execute("""
                INSERT INTO questions (
                    user_id, question_text, option_a, option_b, option_c, option_d,
                    correct_answer, marks, negative_marks, category, difficulty
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'Aptitude', %s)
            """, (auth_hr_id, q_text, opt_a, opt_b, opt_c, opt_d, correct_ans, q_marks, q_neg, q_diff))
            q_id = cursor.lastrowid
            saved_count += 1

            if exam_id and str(exam_id).isdigit():
                cursor.execute("""
                    INSERT INTO exam_questions (exam_id, question_id, question_order)
                    VALUES (%s, %s, %s)
                """, (int(exam_id), q_id, saved_count))

        connection.commit()
        cursor.close()
        connection.close()

        flash(f"{saved_count} MCQ questions have been added successfully to the question bank.", "success")

        if exam_id and str(exam_id).isdigit():
            return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
        return redirect(url_for("hr_question_bank"))

    except Exception as err:
        print("Error saving PDF questions:", err)
        flash(f"Save questions failed: {str(err)}", "error")
        return redirect(url_for("hr_question_bank"))


@app.route("/hr/questions/delete/<int:question_id>", methods=["POST"])
def hr_delete_question(question_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    exam_id = request.form.get("exam_id")
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")

    connection = get_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        q = verify_question_ownership(cursor, question_id, auth_hr_id, is_admin)
        if not q:
            cursor.close()
            connection.close()
            flash("Unauthorized access to question", "error")
            if exam_id and str(exam_id).isdigit():
                return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
            return redirect(url_for("hr_question_bank"))

        cursor.close()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM questions WHERE id = %s", (question_id,))
        cursor.execute("DELETE FROM exam_questions WHERE question_id = %s", (question_id,))
        connection.commit()
        cursor.close()
        connection.close()
        flash("Question deleted", "success")

    if exam_id and str(exam_id).isdigit():
        return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
    return redirect(url_for("hr_question_bank"))


@app.route("/api/hr/questions/remove-duplicates", methods=["POST"])
def api_hr_remove_duplicate_questions():
    if "logged_in" not in session or session.get("role") != "hr":
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    exam_id = request.form.get("exam_id") or request.args.get("exam_id")
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection error."}), 500

    try:
        cursor = connection.cursor(dictionary=True)

        if exam_id and str(exam_id).isdigit():
            if not verify_exam_ownership(cursor, int(exam_id), auth_hr_id, is_admin):
                cursor.close()
                connection.close()
                return jsonify({"success": False, "message": "Unauthorized access to exam"}), 403
            cursor.execute("""
                SELECT q.* FROM questions q
                JOIN exam_questions eq ON q.id = eq.question_id
                WHERE eq.exam_id = %s
                ORDER BY q.id ASC
            """, (int(exam_id),))
        else:
            if is_admin:
                cursor.execute("SELECT * FROM questions ORDER BY id ASC")
            else:
                cursor.execute("SELECT * FROM questions WHERE user_id = %s ORDER BY id ASC", (auth_hr_id,))

        all_questions = cursor.fetchall()
        total_scanned = len(all_questions)

        seen_normalized = {}
        duplicates_to_delete = []

        import re
        for q in all_questions:
            raw_text = q.get("question_text") or ""
            norm_text = re.sub(r'\s+', ' ', raw_text.strip().lower())

            if norm_text in seen_normalized:
                duplicates_to_delete.append(q["id"])
            else:
                seen_normalized[norm_text] = q["id"]

        duplicates_found = len(duplicates_to_delete)
        duplicates_removed = 0

        if duplicates_to_delete:
            del_cursor = connection.cursor()
            for dup_id in duplicates_to_delete:
                del_cursor.execute("DELETE FROM questions WHERE id = %s", (dup_id,))
                del_cursor.execute("DELETE FROM exam_questions WHERE question_id = %s", (dup_id,))
                duplicates_removed += 1
            del_cursor.close()

        connection.commit()
        cursor.close()
        connection.close()

        remaining_count = total_scanned - duplicates_removed

        return jsonify({
            "success": True,
            "message": f"Successfully removed {duplicates_removed} duplicate questions.",
            "total_scanned": total_scanned,
            "duplicates_found": duplicates_found,
            "duplicates_removed": duplicates_removed,
            "remaining_questions": remaining_count,
            "deleted_ids": duplicates_to_delete
        })
    except Exception as err:
        print("Error removing duplicate questions:", err)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(err)}), 500


@app.route("/api/hr/questions/import", methods=["POST"])
def hr_import_questions():
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    exam_id = request.form.get("exam_id")
    file = request.files.get("file")
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")

    if not file or not file.filename:
        flash("Please select a file", "error")
        return redirect(request.referrer or url_for("hr_question_bank"))

    try:
        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[-1].lower()

        if ext == "csv":
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        connection = get_connection()
        if not connection:
            flash("Database error", "error")
            return redirect(request.referrer or url_for("hr_question_bank"))

        cursor = connection.cursor(dictionary=True)
        if exam_id and str(exam_id).isdigit():
            if not verify_exam_ownership(cursor, int(exam_id), auth_hr_id, is_admin):
                cursor.close()
                connection.close()
                flash("Unauthorized access to exam", "error")
                return redirect(url_for("hr_question_bank"))

        cursor.close()
        cursor = connection.cursor()
        count = 0

        for _, row in df.iterrows():
            q_text = str(row.get("question") or row.get("question_text") or "").strip()
            opt_a = str(row.get("option_a") or "").strip()
            opt_b = str(row.get("option_b") or "").strip()
            opt_c = str(row.get("option_c") or "").strip()
            opt_d = str(row.get("option_d") or "").strip()
            corr = str(row.get("correct_answer") or "A").strip().upper()
            m = float(row.get("marks") or 1.0)
            nm = float(row.get("negative_marks") or 0.0)

            if q_text and opt_a and opt_b:
                cursor.execute("""
                    INSERT INTO questions (user_id, question_text, option_a, option_b, option_c, option_d, correct_answer, marks, negative_marks)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (auth_hr_id, q_text, opt_a, opt_b, opt_c, opt_d, corr, m, nm))
                q_id = cursor.lastrowid

                if exam_id and str(exam_id).isdigit():
                    cursor.execute("INSERT INTO exam_questions (exam_id, question_id) VALUES (%s, %s)", (int(exam_id), q_id))
                count += 1

        connection.commit()
        cursor.close()
        connection.close()
        flash(f"Successfully imported {count} MCQ questions!", "success")
    except Exception as err:
        print("Bulk import error:", err)
        flash(f"Import error: {err}", "error")

    if exam_id and str(exam_id).isdigit():
        return redirect(url_for("hr_exam_questions", exam_id=int(exam_id)))
    return redirect(url_for("hr_question_bank"))


@app.route("/api/hr/questions/template")
def hr_questions_csv_template():
    csv_data = "question,option_a,option_b,option_c,option_d,correct_answer,marks,negative_marks,category,difficulty\n"
    csv_data += '"What is the next number in the sequence 2, 4, 8, 16?","18","24","32","64","C",1.0,0.25,"Aptitude","Easy"\n'
    csv_data += '"Which data structure works on FIFO principle?","Stack","Queue","Tree","Graph","B",1.0,0.25,"Computer Science","Medium"\n'

    response = make_response(csv_data)
    response.headers["Content-Disposition"] = "attachment; filename=mcq_questions_template.csv"
    response.headers["Content-Type"] = "text/csv"
    return response


@app.route("/hr/exams/<int:exam_id>/assign", methods=["GET", "POST"])
def hr_assign_exam(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        return redirect(url_for("hr_exams_list"))

    cursor = connection.cursor(dictionary=True)
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")

    exam = verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin)
    if not exam:
        cursor.close()
        connection.close()
        flash("Exam not found or unauthorized", "error")
        return redirect(url_for("hr_exams_list"))

    if request.method == "POST":
        selected_cand_ids = request.form.getlist("candidate_ids")

        cursor.execute("DELETE FROM exam_assignments WHERE exam_id = %s AND candidate_id IS NOT NULL", (exam_id,))
        for cid in selected_cand_ids:
            try:
                cid_int = int(cid)
            except (ValueError, TypeError):
                continue
            if is_admin or verify_candidate_ownership(cursor, cid_int, auth_hr_id, is_admin):
                cursor.execute("INSERT INTO exam_assignments (exam_id, candidate_id) VALUES (%s, %s)", (exam_id, cid_int))

        connection.commit()
        flash("Candidate assignments updated successfully", "success")

    if is_admin:
        cursor.execute("SELECT * FROM candidates ORDER BY id DESC")
    else:
        cursor.execute("""
            SELECT * FROM candidates 
            WHERE hr_id = %s
               OR (job_id IS NOT NULL AND job_id IN (SELECT job_code FROM automation_jobs WHERE user_id = %s))
               OR (upload_id IS NOT NULL AND upload_id IN (SELECT upload_id FROM uploaded_files WHERE user_id = %s))
            ORDER BY id DESC
        """, (auth_hr_id, auth_hr_id, auth_hr_id))
    candidates = cursor.fetchall()

    cursor.execute("SELECT candidate_id FROM exam_assignments WHERE exam_id = %s AND candidate_id IS NOT NULL", (exam_id,))
    assigned_cand_ids = {row["candidate_id"] for row in cursor.fetchall()}

    if is_admin:
        cursor.execute("SELECT * FROM automation_jobs ORDER BY id DESC")
    else:
        cursor.execute("SELECT * FROM automation_jobs WHERE user_id = %s ORDER BY id DESC", (auth_hr_id,))
    automation_jobs = cursor.fetchall()

    if is_admin:
        cursor.execute("SELECT * FROM uploaded_files ORDER BY id DESC")
    else:
        cursor.execute("SELECT * FROM uploaded_files WHERE user_id = %s ORDER BY id DESC", (auth_hr_id,))
    uploaded_files = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "hr_exam_assign.html",
        exam=exam,
        candidates=candidates,
        assigned_cand_ids=assigned_cand_ids,
        automation_jobs=automation_jobs,
        uploaded_files=uploaded_files
    )


@app.route("/hr/exams/<int:exam_id>/assign-batch", methods=["POST"])
def hr_assign_exam_batch(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    job_upload_key = request.form.get("job_upload_key")
    if not job_upload_key:
        flash("Please select a batch", "warning")
        return redirect(url_for("hr_assign_exam", exam_id=exam_id))

    connection = get_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role") == "admin")

        if not verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin):
            cursor.close()
            connection.close()
            flash("Unauthorized access to exam", "error")
            return redirect(url_for("hr_exams_list"))

        if job_upload_key.startswith("job_"):
            job_code = job_upload_key.replace("job_", "")
            if not verify_job_ownership(cursor, job_code, auth_hr_id, is_admin):
                cursor.close()
                connection.close()
                flash("Unauthorized access to job batch", "error")
                return redirect(url_for("hr_assign_exam", exam_id=exam_id))
            cursor.execute("INSERT INTO exam_assignments (exam_id, candidate_id, job_id) SELECT %s, id, %s FROM candidates WHERE job_id = %s", (exam_id, job_code, job_code))
        elif job_upload_key.startswith("upload_"):
            up_id = job_upload_key.replace("upload_", "")
            if not verify_job_ownership(cursor, up_id, auth_hr_id, is_admin):
                cursor.close()
                connection.close()
                flash("Unauthorized access to upload batch", "error")
                return redirect(url_for("hr_assign_exam", exam_id=exam_id))
            cursor.execute("INSERT INTO exam_assignments (exam_id, candidate_id, upload_id) SELECT %s, id, %s FROM candidates WHERE upload_id = %s", (exam_id, up_id, up_id))

        connection.commit()
        cursor.close()
        connection.close()
        flash("Batch candidates assigned to exam successfully!", "success")

    return redirect(url_for("hr_assign_exam", exam_id=exam_id))


@app.route("/hr/exams/<int:exam_id>/monitor")
def hr_exam_monitor(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        return redirect(url_for("hr_exams_list"))

    cursor = connection.cursor(dictionary=True)
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")
    exam = verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin)
    cursor.close()
    connection.close()

    if not exam:
        flash("Exam not found or unauthorized", "error")
        return redirect(url_for("hr_exams_list"))

    return render_template("hr_exam_monitor.html", exam=exam)


@app.route("/api/hr/exam/<int:exam_id>/live-status")
def api_hr_exam_live_status(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database error"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role") == "admin")
        exam = verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin)
        if not exam:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Unauthorized access to exam"}), 403

        cursor.execute("SELECT COUNT(*) as c FROM exam_questions WHERE exam_id = %s", (exam_id,))
        tot_q = cursor.fetchone()["c"] or 0

        query = """
            SELECT DISTINCT c.id, c.name, c.email
            FROM candidates c
            JOIN exam_assignments ea ON c.id = ea.candidate_id OR c.job_id = ea.job_id OR c.upload_id = ea.upload_id
            WHERE ea.exam_id = %s
        """
        cursor.execute(query, (exam_id,))
        assigned_cands = cursor.fetchall()

        cand_list = []
        stats = {"total": len(assigned_cands), "not_started": 0, "in_progress": 0, "submitted": 0, "violations": 0}

        for c in assigned_cands:
            cursor.execute("""
                SELECT * FROM exam_attempts
                WHERE exam_id = %s AND candidate_id = %s
                ORDER BY id DESC LIMIT 1
            """, (exam_id, c["id"]))
            att = cursor.fetchone()

            status = att["status"] if att else "NOT_STARTED"
            warnings = att["warning_count"] if att else 0
            stats["violations"] += warnings

            if status == "NOT_STARTED":
                stats["not_started"] += 1
            elif status == "IN_PROGRESS":
                stats["in_progress"] += 1
            elif status in ["SUBMITTED", "AUTO_SUBMITTED", "TIME_EXPIRED", "DISQUALIFIED"]:
                stats["submitted"] += 1

            ans_count = 0
            if att:
                cursor.execute("SELECT COUNT(*) as c FROM attempt_answers WHERE attempt_id = %s AND selected_option IS NOT NULL", (att["id"],))
                ans_count = cursor.fetchone()["c"] or 0

            rem_str = "--:--"
            if att and att["expires_at"] and status == "IN_PROGRESS":
                delta = (att["expires_at"] - datetime.now()).total_seconds()
                if delta > 0:
                    mins = int(delta // 60)
                    secs = int(delta % 60)
                    rem_str = f"{mins:02d}:{secs:02d}"
                else:
                    rem_str = "00:00"

            cand_list.append({
                "candidate_id": c["id"],
                "name": c["name"],
                "email": c["email"],
                "status": status,
                "remaining_time": rem_str,
                "answered_count": ans_count,
                "total_questions": tot_q,
                "camera_status": "Connected" if status == "IN_PROGRESS" else "N/A",
                "fullscreen_status": "Active" if status == "IN_PROGRESS" else "N/A",
                "warnings": warnings,
                "last_activity": att["last_activity"].strftime("%I:%M:%S %p") if att and att.get("last_activity") else "N/A",
                "attempt_id": att["id"] if att else None
            })

        cursor.close()
        connection.close()
        return jsonify({"success": True, "stats": stats, "candidates": cand_list})
    except Exception as err:
        print("Error fetching live status:", err)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(err)}), 500


@app.route("/hr/exams/<int:exam_id>/results")
def hr_exam_results_list(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        return redirect(url_for("hr_exams_list"))

    cursor = connection.cursor(dictionary=True)
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")
    exam = verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin)
    if not exam:
        cursor.close()
        connection.close()
        flash("Exam not found or unauthorized", "error")
        return redirect(url_for("hr_exams_list"))

    cursor.execute("""
        SELECT ea.id
        FROM exam_attempts ea
        WHERE ea.exam_id = %s
        ORDER BY ea.id DESC LIMIT 1
    """, (exam_id,))
    attempt = cursor.fetchone()

    cursor.close()
    connection.close()

    if attempt:
        return redirect(url_for("hr_attempt_audit_detail", attempt_id=attempt["id"]))
    else:
        flash("No exam attempt results found yet.", "warning")
        return redirect(url_for("hr_exams_list"))


@app.route("/hr/exams/attempt/<int:attempt_id>")
def hr_attempt_audit_detail(attempt_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        return redirect(url_for("hr_exams_list"))

    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM exam_attempts WHERE id = %s LIMIT 1", (attempt_id,))
    attempt = cursor.fetchone()

    if not attempt:
        cursor.close()
        connection.close()
        flash("Attempt not found", "error")
        return redirect(url_for("hr_exams_list"))

    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")
    exam = verify_exam_ownership(cursor, attempt["exam_id"], auth_hr_id, is_admin)
    if not exam:
        cursor.close()
        connection.close()
        flash("Unauthorized access to exam attempt", "error")
        return redirect(url_for("hr_exams_list"))

    cursor.execute("SELECT * FROM candidates WHERE id = %s LIMIT 1", (attempt["candidate_id"],))
    candidate = cursor.fetchone() or {"name": "Candidate", "email": "N/A", "id": attempt["candidate_id"]}

    cursor.execute("SELECT * FROM security_events WHERE attempt_id = %s ORDER BY id ASC", (attempt_id,))
    security_events = cursor.fetchall()

    tab_switch_count = sum(1 for e in security_events if e["violation_type"] == "TAB_SWITCH")
    fs_exit_count = sum(1 for e in security_events if e["violation_type"] == "FULLSCREEN_EXIT")

    cursor.execute("""
        SELECT q.question_text, q.correct_answer, aa.selected_option, aa.is_correct, aa.marks_awarded
        FROM questions q
        JOIN exam_questions eq ON q.id = eq.question_id
        LEFT JOIN attempt_answers aa ON (q.id = aa.question_id AND aa.attempt_id = %s)
        WHERE eq.exam_id = %s
        ORDER BY eq.question_order ASC
    """, (attempt_id, exam["id"]))
    question_analysis = cursor.fetchall()

    correct_count = sum(1 for q in question_analysis if q["is_correct"])
    wrong_count = sum(1 for q in question_analysis if q["selected_option"] and not q["is_correct"])
    unanswered_count = sum(1 for q in question_analysis if not q["selected_option"])

    cursor.close()
    connection.close()

    return render_template(
        "hr_attempt_detail.html",
        exam=exam,
        attempt=attempt,
        candidate=candidate,
        security_events=security_events,
        tab_switch_count=tab_switch_count,
        fs_exit_count=fs_exit_count,
        question_analysis=question_analysis,
        correct_count=correct_count,
        wrong_count=wrong_count,
        unanswered_count=unanswered_count
    )


@app.route("/api/hr/exam/<int:exam_id>/export")
def api_export_exam_results(exam_id):
    if "logged_in" not in session or session.get("role") != "hr":
        return redirect(url_for("login"))

    connection = get_connection()
    if not connection:
        flash("Database error", "error")
        return redirect(url_for("hr_exams_list"))

    cursor = connection.cursor(dictionary=True)
    auth_hr_id = get_authenticated_hr_id()
    is_admin = (session.get("role") == "admin")
    exam = verify_exam_ownership(cursor, exam_id, auth_hr_id, is_admin)
    if not exam:
        cursor.close()
        connection.close()
        flash("Unauthorized access to exam", "error")
        return redirect(url_for("hr_exams_list"))

    cursor.execute("""
        SELECT c.name as candidate_name, c.email as candidate_email, u.username,
               ex.title as exam_title, ea.job_id, ea.upload_id, ea.id as attempt_id,
               ea.started_at, ea.submitted_at, ea.score, ea.percentage, ea.passed,
               ea.warning_count, ea.status as final_status
        FROM exam_attempts ea
        JOIN candidates c ON ea.candidate_id = c.id
        LEFT JOIN users u ON ea.user_id = u.id
        JOIN exams ex ON ea.exam_id = ex.id
        WHERE ea.exam_id = %s
        ORDER BY ea.id DESC
    """, (exam_id,))
    attempts = cursor.fetchall()
    cursor.close()
    connection.close()

    data_rows = []
    for att in attempts:
        data_rows.append({
            "Candidate Name": att["candidate_name"],
            "Email": att["candidate_email"],
            "Username": att["username"] or "",
            "Exam": att["exam_title"],
            "Job ID": att["job_id"] or "",
            "Upload ID": att["upload_id"] or "",
            "Attempt ID": att["attempt_id"],
            "Started At": att["started_at"],
            "Submitted At": att["submitted_at"],
            "Score": att["score"],
            "Percentage": f"{att['percentage']}%",
            "Pass/Fail": "PASSED" if att["passed"] else "FAILED",
            "Warnings": att["warning_count"],
            "Final Status": att["final_status"]
        })

    df = pd.DataFrame(data_rows)
    csv_str = df.to_csv(index=False)

    response = make_response(csv_str)
    response.headers["Content-Disposition"] = f"attachment; filename=exam_{exam_id}_results.csv"
    response.headers["Content-Type"] = "text/csv"
    return response


# ============================================================
# AUTOMATION PDF GENERATION & DOWNLOAD ROUTES
# ============================================================

@app.route("/download/automation-pdf", methods=["GET"])
@app.route("/api/generate-automation-pdf", methods=["GET", "POST"])
def download_automation_pdf():
    """Generates and serves Automation.pdf report of project automation status."""
    try:
        from services.generate_automation_pdf import generate_automation_pdf
        pdf_path = generate_automation_pdf()
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name="Automation.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        logger.error(f"Error generating Automation.pdf: {e}")
        pdf_fallback = os.path.join(app.root_path, "automation", "Automation.pdf")
        if os.path.exists(pdf_fallback):
            return send_file(
                pdf_fallback,
                as_attachment=True,
                download_name="Automation.pdf",
                mimetype="application/pdf"
            )
        return jsonify({"error": str(e), "message": "Automation.pdf generation failed"}), 500


# ============================================================
# HR INTERVIEW SCHEDULING & CALENDAR ROUTES
# ============================================================

@app.route("/hr/interviews", methods=["GET"])
def hr_interviews():
    """HR Interview Scheduling and Interactive Calendar Dashboard."""
    if "logged_in" not in session:
        flash("Please login first", "error")
        return redirect(url_for("login"))

    role = session.get("role", "").lower()
    if role != "hr":
        flash("Access restricted to HR staff only.", "error")
        return redirect(url_for("candidate_dashboard"))

    # Fetch candidates list for scheduling dropdown
    candidates_list = []
    connection = get_connection()
    if connection:
        try:
            cursor = connection.cursor(dictionary=True)
            auth_hr_id = get_authenticated_hr_id()
            if role == "admin":
                cursor.execute("""
                    SELECT id, name, email, position, status
                    FROM candidates
                    ORDER BY name ASC
                """)
            else:
                cursor.execute("""
                    SELECT id, name, email, position, status
                    FROM candidates
                    WHERE hr_id = %s
                       OR (job_id IS NOT NULL AND job_id IN (SELECT job_code FROM automation_jobs WHERE user_id = %s))
                       OR (upload_id IS NOT NULL AND upload_id IN (SELECT upload_id FROM uploaded_files WHERE user_id = %s))
                    ORDER BY name ASC
                """, (auth_hr_id, auth_hr_id, auth_hr_id))
            candidates_list = cursor.fetchall()
            cursor.close()
            connection.close()
        except Exception as e:
            print("Error fetching candidates for interviews:", e)

    return render_template(
        "hr_interviews.html",
        candidates=candidates_list
    )


@app.route("/api/interviews/candidates", methods=["GET"])
def api_get_interview_candidates():
    """Returns list of HR's candidates with IDs, names, emails, phones, and positions for the interview searchable dropdown."""
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    auth_hr_id = get_authenticated_hr_id()
    candidates = []
    connection = get_connection()
    if connection:
        try:
            cursor = connection.cursor(dictionary=True)
            if is_admin_authenticated():
                cursor.execute("SELECT id, name, email, phone, position, job_id, registration_status, status FROM candidates ORDER BY id DESC")
            else:
                cursor.execute("""
                    SELECT id, name, email, phone, position, job_id, registration_status, status 
                    FROM candidates 
                    WHERE hr_id = %s OR (hr_id IS NULL AND user_id = %s)
                    ORDER BY id DESC
                """, (auth_hr_id, auth_hr_id))
            raw_cands = cursor.fetchall() or []
            for c in raw_cands:
                candidates.append({
                    "id": c["id"],
                    "name": c["name"] or "Candidate",
                    "email": c["email"] or "",
                    "phone": c["phone"] or "",
                    "position": c["position"] or "Applicant",
                    "job_id": c.get("job_id") or "",
                    "status": c.get("status") or c.get("registration_status") or "Active"
                })
            cursor.close()
            connection.close()
        except Exception as e:
            print("Error fetching interview candidates:", e)

    return jsonify({"success": True, "candidates": candidates, "count": len(candidates)})


@app.route("/api/interviews/interviewers", methods=["GET"])
def api_get_interviewers():
    """Returns list of available interviewers and HR staff for search dropdown."""
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    interviewers = []
    connection = get_connection()
    if connection:
        try:
            cursor = connection.cursor(dictionary=True)
            # Fetch HR users
            cursor.execute("SELECT fullname as name, email FROM users WHERE LOWER(role) = 'hr'")
            hr_users = cursor.fetchall()
            for u in hr_users:
                if u["name"]:
                    interviewers.append({"name": u["name"], "email": u["email"] or ""})
            
            # Fetch distinct past interviewers
            cursor.execute("SELECT DISTINCT interviewer_name as name, interviewer_email as email FROM interviews WHERE interviewer_name IS NOT NULL AND interviewer_name != ''")
            past_intvs = cursor.fetchall()
            for p in past_intvs:
                if p["name"] and not any(i["name"].lower() == p["name"].lower() for i in interviewers):
                    interviewers.append({"name": p["name"], "email": p["email"] or ""})

            cursor.close()
            connection.close()
        except Exception as e:
            print("Error fetching interviewers:", e)
            
    return jsonify({"success": True, "interviewers": interviewers})


@app.route("/api/interviews/check-conflict", methods=["POST"])
def api_check_interview_conflict():
    """Checks whether an interviewer has an overlapping interview during the given time slot."""
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or request.form
    interviewer_name = (data.get("interviewer_name") or "").strip()
    interview_date = (data.get("interview_date") or "").strip()
    start_time = (data.get("start_time") or "").strip()
    end_time = (data.get("end_time") or "").strip()
    exclude_id = data.get("exclude_id")

    if not interviewer_name or not interview_date or not start_time or not end_time:
        return jsonify({"success": False, "message": "Missing required fields for conflict check."}), 400

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT id, candidate_name, candidate_email, interviewer_name,
                   DATE_FORMAT(interview_date, '%Y-%m-%d') as interview_date,
                   TIME_FORMAT(start_time, '%H:%i') as start_time,
                   TIME_FORMAT(end_time, '%H:%i') as end_time,
                   interview_type, status
            FROM interviews
            WHERE LOWER(interviewer_name) = LOWER(%s)
              AND interview_date = %s
              AND status != 'Cancelled'
              AND (%s IS NULL OR id != %s)
              AND (start_time < %s AND end_time > %s)
            LIMIT 1
        """
        cursor.execute(query, (interviewer_name, interview_date, exclude_id, exclude_id, end_time, start_time))
        conflict = cursor.fetchone()
        cursor.close()
        connection.close()

        if conflict:
            return jsonify({
                "has_conflict": True,
                "message": f"Conflict detected with {conflict['candidate_name']} ({conflict['start_time']} - {conflict['end_time']})",
                "conflict": conflict
            })
        return jsonify({"has_conflict": False})
    except Exception as e:
        print("Error checking interview conflict:", e)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/interviews/list", methods=["GET"])
def api_list_interviews():
    """Lists interviews filtered by candidate, interviewer, status, date range, or search keyword."""
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        status = request.args.get("status")
        search = request.args.get("search")
        cand_id = request.args.get("candidate_id")

        query = """
            SELECT id, candidate_id, candidate_name, candidate_email, interviewer_name, interviewer_email,
                   DATE_FORMAT(interview_date, '%Y-%m-%d') as interview_date,
                   TIME_FORMAT(start_time, '%H:%i') as start_time,
                   TIME_FORMAT(end_time, '%H:%i') as end_time,
                   interview_type, location_link, status, notes,
                   reschedule_reason, previous_schedule,
                   candidate_reschedule_reason,
                   DATE_FORMAT(candidate_preferred_date, '%Y-%m-%d') as candidate_preferred_date,
                   candidate_preferred_time, candidate_reschedule_message,
                   DATE_FORMAT(reschedule_requested_at, '%b %d, %Y %H:%i') as reschedule_requested_at_formatted,
                   DATE_FORMAT(rescheduled_at, '%b %d, %Y %H:%i') as rescheduled_at_formatted,
                   DATE_FORMAT(updated_at, '%b %d, %Y %H:%i') as updated_at_formatted,
                   DATE_FORMAT(created_at, '%b %d, %Y') as created_at_formatted
            FROM interviews
            WHERE 1=1
        """
        params = []

        user_role = str(session.get("role") or "").strip().lower()
        if user_role == "candidate":
            current_user_id = resolve_user_id()
            user_email = session.get("email") or ""
            cursor_cand = connection.cursor(dictionary=True)
            cursor_cand.execute("SELECT id FROM candidates WHERE user_id = %s OR email = %s LIMIT 1", (current_user_id, user_email))
            c_rec = cursor_cand.fetchone()
            user_cand_id = c_rec["id"] if c_rec else -1
            cursor_cand.close()

            query += " AND (candidate_id = %s OR candidate_email = %s)"
            params.extend([user_cand_id, user_email])
        elif user_role == "hr":
            auth_hr_id = get_authenticated_hr_id()
            query += """ AND (
                interviews.created_by = %s 
                OR interviews.candidate_id IN (
                    SELECT id FROM candidates WHERE hr_id = %s OR (hr_id IS NULL AND user_id = %s)
                )
            )"""
            params.extend([auth_hr_id, auth_hr_id, auth_hr_id])
            if cand_id:
                query += " AND candidate_id = %s"
                params.append(cand_id)
        elif cand_id:
            query += " AND candidate_id = %s"
            params.append(cand_id)

        if status and status != 'ALL':
            query += " AND status = %s"
            params.append(status)
        if search:
            query += " AND (LOWER(candidate_name) LIKE %s OR LOWER(candidate_email) LIKE %s OR LOWER(interviewer_name) LIKE %s OR LOWER(interview_type) LIKE %s)"
            search_param = f"%{search.lower()}%"
            params.extend([search_param, search_param, search_param, search_param])

        query += " ORDER BY interview_date ASC, start_time ASC"

        cursor = connection.cursor(dictionary=True)
        cursor.execute(query, params)
        interviews = cursor.fetchall()
        cursor.close()
        connection.close()

        return jsonify({"success": True, "interviews": interviews})
    except Exception as e:
        print("Error listing interviews:", e)
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================
# IN-APP NOTIFICATIONS & EMAIL HELPERS
# ============================================================

def create_notification(recipient_role, title, message, link=None, user_id=None, candidate_id=None, notification_type="general"):
    """Creates a persistent in-app notification record."""
    conn = get_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO notifications (user_id, candidate_id, recipient_role, title, message, link, notification_type, is_read, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, NOW())
            """, (user_id, candidate_id, recipient_role, title, message, link, notification_type))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print("Error creating notification:", e)
            if conn:
                conn.close()
    return False


def generate_reschedule_email_content(candidate_name, interview_type, old_schedule, new_date, new_start, new_end, interviewer_name, location_link, reason, notes=""):
    """Generates email subject, plaintext body, and modern responsive HTML body for interview rescheduling."""
    subject = f"[Rescheduled] {interview_type} Interview - SmartRecruitment"

    body_text = f"""Dear {candidate_name},

Your {interview_type} interview with SmartRecruitment has been rescheduled.

PREVIOUS SCHEDULE:
{old_schedule}

NEW SCHEDULE:
Date: {new_date}
Time: {new_start} - {new_end}
Interviewer: {interviewer_name}
Meeting Location / Link: {location_link or 'Will be provided shortly'}

REASON FOR RESCHEDULING:
{reason}

ADDITIONAL NOTES:
{notes or 'None'}

Please ensure you join on time. If this new time is not convenient, please contact HR immediately.

Best regards,
Smart Recruitment Automation Team
"""

    meeting_btn_html = ""
    if location_link:
        if location_link.startswith("http"):
            meeting_btn_html = f'<div style="margin: 16px 0;"><a href="{location_link}" style="display: inline-block; background: #2563eb; color: #ffffff !important; text-decoration: none; padding: 12px 24px; border-radius: 10px; font-weight: 700; text-align: center;" target="_blank">🔗 Join Interview Meeting</a></div>'
        else:
            meeting_btn_html = f'<div style="margin: 14px 0; padding: 10px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; font-size: 13px;"><strong>📍 Location:</strong> {location_link}</div>'

    notes_html = ""
    if notes:
        notes_html = f'<div style="margin: 14px 0; padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;"><strong style="font-size: 12px; color: #64748b; text-transform: uppercase;">Instructions / Notes:</strong><div style="color: #1e293b; font-size: 13px; margin-top: 4px;">{notes}</div></div>'

    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b;">
    <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; border: 1.5px solid #e2e8f0; box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06);">
        <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); padding: 26px 24px; color: #ffffff; text-align: center;">
            <div style="font-size: 32px; margin-bottom: 6px;">📅</div>
            <h1 style="margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -0.3px;">Interview Rescheduled</h1>
            <p style="margin: 6px 0 0 0; opacity: 0.9; font-size: 14px;">Your {interview_type} schedule has been updated</p>
        </div>
        <div style="padding: 24px;">
            <p style="font-size: 15px; margin-top: 0;">Dear <strong>{candidate_name}</strong>,</p>
            <p style="font-size: 14px; color: #475569; line-height: 1.5;">Please note that your upcoming interview schedule has been updated. Please review your new confirmed time slot below:</p>
            
            <div style="background: #fef2f2; border: 1.5px solid #fecaca; border-radius: 10px; padding: 12px; margin: 14px 0; color: #991b1b; font-size: 13px;">
                <span style="font-weight: 700;">Previous Schedule:</span> <span style="text-decoration: line-through;">{old_schedule}</span>
            </div>

            <div style="background: #eff6ff; border: 1.5px solid #bfdbfe; border-radius: 12px; padding: 18px; margin: 16px 0;">
                <div style="font-size: 11px; font-weight: 800; text-transform: uppercase; color: #2563eb; letter-spacing: 0.5px; margin-bottom: 6px;">New Confirmed Schedule</div>
                <div style="font-size: 18px; font-weight: 800; color: #0f172a; margin-bottom: 4px;">📅 {new_date}</div>
                <div style="font-size: 15px; font-weight: 700; color: #2563eb; margin-bottom: 12px;">⏰ {new_start} - {new_end}</div>
                <hr style="border: 0; border-top: 1px solid #bfdbfe; margin: 10px 0;">
                <div style="font-size: 13px; color: #334155; margin-bottom: 4px;"><strong>Interviewer:</strong> {interviewer_name}</div>
                <div style="font-size: 13px; color: #334155;"><strong>Interview Type:</strong> {interview_type}</div>
            </div>

            <div style="margin: 14px 0;">
                <strong style="font-size: 13px; color: #334155;">Reason for Rescheduling:</strong><br>
                <div style="display: inline-block; background: #fffbeb; color: #b45309; padding: 6px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; margin-top: 4px; border: 1px solid #fde68a;">
                    ⚠️ {reason}
                </div>
            </div>

            {meeting_btn_html}
            {notes_html}

            <p style="font-size: 13px; color: #64748b; line-height: 1.5; margin-top: 20px;">
                Please be prepared 5 minutes prior to the scheduled start time. If this new time presents any scheduling conflict, please reach out directly through your candidate portal or contact HR.
            </p>
        </div>
        <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px; text-align: center; font-size: 12px; color: #64748b;">
            Smart Recruitment Automation System &bull; Automated Notification
        </div>
    </div>
</body>
</html>"""

    return subject, body_text, body_html


# ============================================================
# NOTIFICATIONS API ROUTES
# ============================================================

@app.route("/api/notifications", methods=["GET"])
def api_get_notifications():
    """Returns unread notification count and recent notifications list for the logged-in user."""
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        user_role = str(session.get("role") or "").strip().lower()
        user_id = resolve_user_id()
        user_email = session.get("email") or ""

        cand_id = None
        if user_role == "candidate":
            cursor.execute("SELECT id FROM candidates WHERE user_id = %s OR email = %s LIMIT 1", (user_id, user_email))
            c_rec = cursor.fetchone()
            if c_rec:
                cand_id = c_rec["id"]

        # Fetch notifications
        if user_role == "candidate":
            cursor.execute("""
                SELECT id, title, message, link, notification_type, is_read,
                       DATE_FORMAT(created_at, '%b %d, %Y %H:%i') as created_at_formatted
                FROM notifications
                WHERE recipient_role = 'candidate' AND (user_id = %s OR candidate_id = %s OR (user_id IS NULL AND candidate_id IS NULL))
                ORDER BY created_at DESC
                LIMIT 30
            """, (user_id, cand_id))
        elif user_role == "hr":
            auth_hr_id = get_authenticated_hr_id()
            cursor.execute("""
                SELECT id, title, message, link, notification_type, is_read,
                       DATE_FORMAT(created_at, '%b %d, %Y %H:%i') as created_at_formatted
                FROM notifications
                WHERE recipient_role IN ('hr', 'all') AND (user_id = %s OR user_id IS NULL)
                ORDER BY created_at DESC
                LIMIT 30
            """, (auth_hr_id,))
        else:
            cursor.execute("""
                SELECT id, title, message, link, notification_type, is_read,
                       DATE_FORMAT(created_at, '%b %d, %Y %H:%i') as created_at_formatted
                FROM notifications
                ORDER BY created_at DESC
                LIMIT 30
            """)

        notifications = cursor.fetchall() or []
        unread_count = sum(1 for n in notifications if not n["is_read"])

        cursor.close()
        connection.close()

        return jsonify({
            "success": True,
            "unread_count": unread_count,
            "notifications": notifications
        })
    except Exception as e:
        print("Error fetching notifications:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/notifications/mark-read", methods=["POST"])
def api_mark_notifications_read():
    """Marks a single notification or all notifications as read."""
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or request.form
    notification_id = data.get("notification_id")

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor()
        user_role = str(session.get("role") or "").strip().lower()
        user_id = resolve_user_id()

        if notification_id and notification_id != "all":
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = %s", (notification_id,))
        else:
            if user_role == "candidate":
                cursor.execute("UPDATE notifications SET is_read = 1 WHERE recipient_role = 'candidate' AND (user_id = %s OR user_id IS NULL)", (user_id,))
            else:
                auth_hr_id = get_authenticated_hr_id()
                cursor.execute("UPDATE notifications SET is_read = 1 WHERE recipient_role IN ('hr', 'all') AND (user_id = %s OR user_id IS NULL)", (auth_hr_id,))

        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"success": True, "message": "Notifications marked as read."})
    except Exception as e:
        print("Error marking notifications read:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================
# INTERVIEW RESCHEDULING & PREVIEW EMAIL API ROUTES
# ============================================================

@app.route("/api/interviews/preview-email", methods=["POST"])
def api_preview_reschedule_email():
    """Generates preview subject, HTML, and plaintext for reschedule notification email."""
    if "logged_in" not in session or session.get("role", "").lower() != "hr":
        return jsonify({"success": False, "message": "Unauthorized - HR role required"}), 403

    data = request.get_json(silent=True) or request.form
    candidate_name = data.get("candidate_name") or "Candidate"
    interview_type = data.get("interview_type") or "Technical"
    old_schedule = data.get("old_schedule") or "Previous date & time"
    new_date = data.get("new_date") or ""
    new_start = data.get("new_start") or ""
    new_end = data.get("new_end") or ""
    interviewer_name = data.get("interviewer_name") or "HR Interviewer"
    location_link = data.get("location_link") or ""
    reason = data.get("reason") or "Schedule adjustment requested"
    notes = data.get("notes") or ""

    subject, text_body, html_body = generate_reschedule_email_content(
        candidate_name=candidate_name,
        interview_type=interview_type,
        old_schedule=old_schedule,
        new_date=new_date,
        new_start=new_start,
        new_end=new_end,
        interviewer_name=interviewer_name,
        location_link=location_link,
        reason=reason,
        notes=notes
    )

    return jsonify({
        "success": True,
        "subject": subject,
        "html": html_body,
        "text": text_body
    })


@app.route("/api/interviews/reschedule/<int:interview_id>", methods=["POST"])
def api_reschedule_interview(interview_id):
    """Reschedules an interview, validates conflicts, records reasons, sends email, and dispatches in-app notifications."""
    if "logged_in" not in session or session.get("role", "").lower() != "hr":
        return jsonify({"success": False, "message": "Unauthorized - HR role required"}), 403

    data = request.get_json(silent=True) or request.form
    new_date = (data.get("new_date") or "").strip()
    new_start = (data.get("new_start") or "").strip()
    new_end = (data.get("new_end") or "").strip()
    reason = (data.get("reason") or "Scheduling adjustment").strip()
    custom_reason = (data.get("custom_reason") or "").strip()
    send_email = data.get("send_email", True)
    location_link = (data.get("location_link") or "").strip()
    notes = (data.get("notes") or "").strip()

    if reason == "Other" and custom_reason:
        final_reason = f"Other: {custom_reason}"
    else:
        final_reason = reason

    if not new_date or not new_start or not new_end:
        return jsonify({"success": False, "message": "Please specify the new interview date, start time, and end time."}), 400

    if new_start >= new_end:
        return jsonify({"success": False, "message": "Invalid time slot: Start time must be strictly before end time."}), 400

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role", "").lower() == "admin")

        # Fetch existing interview record
        cursor.execute("SELECT * FROM interviews WHERE id = %s", (interview_id,))
        existing = cursor.fetchone()
        if not existing:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Interview record not found."}), 404

        if not verify_interview_ownership(cursor, interview_id, auth_hr_id, is_admin):
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Unauthorized: Cannot modify this interview."}), 403

        # Formulate old schedule string for diffing and email
        old_schedule_str = f"{existing['interview_date']} from {str(existing['start_time'])[:5]} to {str(existing['end_time'])[:5]}"
        interviewer_name = existing["interviewer_name"]
        interviewer_email = existing.get("interviewer_email") or ""
        candidate_name = existing["candidate_name"]
        candidate_email = existing["candidate_email"]
        candidate_id = existing["candidate_id"]
        interview_type = existing["interview_type"] or "Technical"

        # Check conflict on new time slot (excluding current interview id)
        conflict_query = """
            SELECT id, candidate_name, candidate_email, interviewer_name,
                   DATE_FORMAT(interview_date, '%Y-%m-%d') as interview_date,
                   TIME_FORMAT(start_time, '%H:%i') as start_time,
                   TIME_FORMAT(end_time, '%H:%i') as end_time,
                   interview_type, status
            FROM interviews
            WHERE LOWER(interviewer_name) = LOWER(%s)
              AND interview_date = %s
              AND status != 'Cancelled'
              AND id != %s
              AND (start_time < %s AND end_time > %s)
            LIMIT 1
        """
        cursor.execute(conflict_query, (interviewer_name, new_date, interview_id, new_end, new_start))
        conflict = cursor.fetchone()

        if conflict:
            cursor.close()
            connection.close()
            return jsonify({
                "success": False,
                "has_conflict": True,
                "message": f"Conflict Detected: Interviewer '{interviewer_name}' is already booked on {new_date} from {conflict['start_time']} to {conflict['end_time']} with candidate {conflict['candidate_name']}.",
                "conflict": conflict
            }), 409

        # Update location_link if provided, else retain
        final_location = location_link if location_link else (existing.get("location_link") or "")
        final_notes = notes if notes else (existing.get("notes") or "")

        # Execute Reschedule Update in Database
        cursor.execute("""
            UPDATE interviews SET
                interview_date = %s,
                start_time = %s,
                end_time = %s,
                status = 'Rescheduled',
                location_link = %s,
                notes = %s,
                reschedule_reason = %s,
                previous_schedule = %s,
                candidate_reschedule_reason = NULL,
                candidate_preferred_date = NULL,
                candidate_preferred_time = NULL,
                candidate_reschedule_message = NULL,
                reschedule_requested_at = NULL,
                rescheduled_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """, (new_date, new_start, new_end, final_location, final_notes, final_reason, old_schedule_str, interview_id))
        connection.commit()

        # Find linked user_id for candidate if exists
        cursor.execute("SELECT user_id FROM candidates WHERE id = %s", (candidate_id,))
        cand_user_row = cursor.fetchone()
        cand_user_id = cand_user_row["user_id"] if cand_user_row else None

        cursor.close()
        connection.close()

        # Dispatch In-App Notifications
        # 1. Candidate Notification
        cand_msg = f"Your {interview_type} interview has been rescheduled to {new_date} ({new_start} - {new_end}). Reason: {final_reason}."
        create_notification(
            recipient_role="candidate",
            title=f"{interview_type} Interview Rescheduled",
            message=cand_msg,
            link="/candidate/dashboard",
            candidate_id=candidate_id,
            user_id=cand_user_id,
            notification_type="interview_rescheduled"
        )

        # 2. HR Notification
        hr_msg = f"Successfully rescheduled interview for {candidate_name} to {new_date} ({new_start} - {new_end})."
        create_notification(
            recipient_role="hr",
            title="Interview Rescheduled",
            message=hr_msg,
            link="/hr/interviews",
            user_id=auth_hr_id,
            notification_type="interview_rescheduled"
        )

        # Send Email Notification if requested
        email_sent = False
        email_error = None
        if send_email and candidate_email:
            try:
                subject, text_body, html_body = generate_reschedule_email_content(
                    candidate_name=candidate_name,
                    interview_type=interview_type,
                    old_schedule=old_schedule_str,
                    new_date=new_date,
                    new_start=new_start,
                    new_end=new_end,
                    interviewer_name=interviewer_name,
                    location_link=final_location,
                    reason=final_reason,
                    notes=final_notes
                )
                res = send_smtp_email(candidate_email, subject, text_body, html_body)
                email_sent = res.get("success", False)
                if not email_sent:
                    email_error = res.get("message")
            except Exception as mail_err:
                print("Error sending reschedule email:", mail_err)
                email_error = str(mail_err)

        return jsonify({
            "success": True,
            "message": f"Interview for {candidate_name} successfully rescheduled to {new_date} ({new_start} - {new_end})!",
            "email_sent": email_sent,
            "email_error": email_error,
            "rescheduled_data": {
                "id": interview_id,
                "candidate_name": candidate_name,
                "candidate_email": candidate_email,
                "old_schedule": old_schedule_str,
                "new_date": new_date,
                "new_start": new_start,
                "new_end": new_end,
                "reason": final_reason,
                "status": "Rescheduled"
            }
        })
    except Exception as e:
        print("Error in reschedule API:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/candidate/interview/request-reschedule", methods=["POST"])
def api_candidate_request_reschedule():
    """Allows candidates to submit an interview reschedule request with reasons, preferred timing, and message."""
    if "logged_in" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json(silent=True) or request.form
    interview_id = data.get("interview_id")
    reason = (data.get("reason") or "").strip()
    custom_reason = (data.get("custom_reason") or "").strip()
    preferred_date = (data.get("preferred_date") or "").strip()
    preferred_time = (data.get("preferred_time") or "").strip()
    message = (data.get("message") or "").strip()

    if not interview_id:
        return jsonify({"success": False, "message": "Interview ID is required"}), 400

    if not reason:
        return jsonify({"success": False, "message": "Please specify a reason for rescheduling."}), 400

    if reason == "Other" and custom_reason:
        final_reason = f"Other: {custom_reason}"
    else:
        final_reason = reason

    if not preferred_date:
        return jsonify({"success": False, "message": "Please select your preferred new interview date."}), 400

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        user_id = resolve_user_id()
        user_email = session.get("email") or session.get("username") or ""

        interview = verify_candidate_interview_ownership(cursor, interview_id, user_id, user_email)
        if not interview:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Interview not found or unauthorized."}), 403

        if interview["status"] == "Cancelled":
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Cannot reschedule a cancelled interview."}), 400

        # Update interview with reschedule request details
        cursor.execute("""
            UPDATE interviews SET
                status = 'Reschedule Requested',
                candidate_reschedule_reason = %s,
                candidate_preferred_date = %s,
                candidate_preferred_time = %s,
                candidate_reschedule_message = %s,
                reschedule_requested_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """, (final_reason, preferred_date, preferred_time or 'Flexible / Any available slot', message, interview_id))
        connection.commit()

        # Find HR recipient (created_by or candidate's hr_id)
        hr_recipient_id = interview.get("created_by")
        if not hr_recipient_id:
            cursor.execute("SELECT hr_id FROM candidates WHERE id = %s", (interview["candidate_id"],))
            cand_row = cursor.fetchone()
            if cand_row and cand_row.get("hr_id"):
                hr_recipient_id = cand_row["hr_id"]

        cand_name = interview.get("candidate_name") or "Candidate"
        intv_type = interview.get("interview_type") or "Interview"

        cursor.close()
        connection.close()

        # In-App Notification for HR
        hr_notif_msg = f"{cand_name} requested to reschedule {intv_type} interview. Reason: {final_reason}. Preferred: {preferred_date} ({preferred_time or 'Flexible'})."
        create_notification(
            recipient_role="hr",
            title="Candidate Reschedule Request",
            message=hr_notif_msg,
            link="/hr/interviews",
            user_id=hr_recipient_id,
            notification_type="candidate_reschedule_requested"
        )

        # In-App Notification for Candidate
        cand_notif_msg = f"Your reschedule request for {intv_type} interview ({preferred_date}) has been submitted to HR for review."
        create_notification(
            recipient_role="candidate",
            title="Reschedule Request Submitted",
            message=cand_notif_msg,
            link="/candidate/dashboard",
            user_id=user_id,
            candidate_id=interview.get("candidate_id"),
            notification_type="reschedule_request_sent"
        )

        return jsonify({
            "success": True,
            "message": "Your reschedule request has been submitted successfully. HR has been notified.",
            "interview_id": interview_id,
            "status": "Reschedule Requested",
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "reason": final_reason
        })
    except Exception as e:
        print("Error submitting candidate reschedule request:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/hr/interview/decline-reschedule/<int:interview_id>", methods=["POST"])
def api_hr_decline_reschedule(interview_id):
    """Allows HR to decline a candidate's reschedule request with an optional note, resetting status to Scheduled."""
    if "logged_in" not in session or session.get("role", "").lower() != "hr":
        return jsonify({"success": False, "message": "Unauthorized - HR role required"}), 403

    data = request.get_json(silent=True) or request.form
    decline_note = (data.get("decline_note") or data.get("reason") or "Interview schedule remains unchanged.").strip()

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role", "").lower() == "admin")

        existing = verify_interview_ownership(cursor, interview_id, auth_hr_id, is_admin)
        if not existing:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Interview not found or unauthorized."}), 404

        # Reset status back to Scheduled (or previous schedule status)
        cursor.execute("""
            UPDATE interviews SET
                status = IF(previous_schedule IS NOT NULL AND previous_schedule != '', 'Rescheduled', 'Scheduled'),
                candidate_reschedule_reason = NULL,
                candidate_preferred_date = NULL,
                candidate_preferred_time = NULL,
                candidate_reschedule_message = NULL,
                reschedule_requested_at = NULL,
                notes = CONCAT(IFNULL(notes, ''), '\n[HR Note]: Candidate reschedule request was declined: ', %s),
                updated_at = NOW()
            WHERE id = %s
        """, (decline_note, interview_id))
        connection.commit()

        # Find linked user_id for candidate
        cursor.execute("SELECT user_id FROM candidates WHERE id = %s", (existing["candidate_id"],))
        cand_user_row = cursor.fetchone()
        cand_user_id = cand_user_row["user_id"] if cand_user_row else None

        cursor.close()
        connection.close()

        # Send notification to candidate
        intv_type = existing.get("interview_type") or "Interview"
        cand_msg = f"Your reschedule request for {intv_type} interview on {existing['interview_date']} could not be accommodated: {decline_note}. The confirmed schedule remains as planned."
        create_notification(
            recipient_role="candidate",
            title="Reschedule Request Declined",
            message=cand_msg,
            link="/candidate/dashboard",
            candidate_id=existing["candidate_id"],
            user_id=cand_user_id,
            notification_type="reschedule_declined"
        )

        return jsonify({
            "success": True,
            "message": "Candidate reschedule request declined. Candidate has been notified.",
            "status": "Scheduled"
        })
    except Exception as e:
        print("Error declining reschedule request:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/interviews/schedule", methods=["POST"])
def api_schedule_interview():
    """Schedules a new candidate interview after date, time, and interviewer conflict validation."""
    if "logged_in" not in session or session.get("role", "").lower() != "hr":
        return jsonify({"success": False, "message": "Unauthorized - HR role required"}), 403

    data = request.get_json(silent=True) or request.form
    candidate_id = data.get("candidate_id")
    interviewer_name = (data.get("interviewer_name") or "").strip()
    interviewer_email = (data.get("interviewer_email") or "").strip()
    interview_date = (data.get("interview_date") or "").strip()
    start_time = (data.get("start_time") or "").strip()
    end_time = (data.get("end_time") or "").strip()
    interview_type = (data.get("interview_type") or "Technical").strip()
    location_link = (data.get("location_link") or "").strip()
    status = (data.get("status") or "Scheduled").strip()
    notes = (data.get("notes") or "").strip()

    # Validation
    if not candidate_id or not interviewer_name or not interview_date or not start_time or not end_time:
        return jsonify({"success": False, "message": "Please fill in all required fields (Candidate, Interviewer, Date, Start Time, End Time)."}), 400

    if start_time >= end_time:
        return jsonify({"success": False, "message": "Invalid Time: Start time must be strictly before end time."}), 400

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role", "").lower() == "admin")

        # Get candidate details
        cursor.execute("SELECT id, name, email FROM candidates WHERE id = %s", (candidate_id,))
        cand = cursor.fetchone()
        if not cand:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Selected candidate not found."}), 404

        if not is_admin and not verify_candidate_ownership(cursor, cand["id"], auth_hr_id, is_admin):
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Unauthorized: Candidate not accessible."}), 403

        # Conflict check
        conflict_query = """
            SELECT id, candidate_name, candidate_email, interviewer_name,
                   DATE_FORMAT(interview_date, '%Y-%m-%d') as interview_date,
                   TIME_FORMAT(start_time, '%H:%i') as start_time,
                   TIME_FORMAT(end_time, '%H:%i') as end_time,
                   interview_type, status
            FROM interviews
            WHERE LOWER(interviewer_name) = LOWER(%s)
              AND interview_date = %s
              AND status != 'Cancelled'
              AND (start_time < %s AND end_time > %s)
            LIMIT 1
        """
        cursor.execute(conflict_query, (interviewer_name, interview_date, end_time, start_time))
        conflict = cursor.fetchone()

        if conflict:
            cursor.close()
            connection.close()
            return jsonify({
                "success": False,
                "has_conflict": True,
                "message": f"Interview Conflict: The interviewer '{interviewer_name}' already has an interview scheduled with {conflict['candidate_name']} from {conflict['start_time']} to {conflict['end_time']}.",
                "conflict": conflict
            }), 409

        # Insert new interview
        insert_sql = """
            INSERT INTO interviews (
                candidate_id, candidate_name, candidate_email, interviewer_name, interviewer_email,
                interview_date, start_time, end_time, interview_type, location_link, status, notes, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_sql, (
            cand["id"], cand["name"], cand["email"], interviewer_name, interviewer_email,
            interview_date, start_time, end_time, interview_type, location_link, status, notes, auth_hr_id
        ))
        connection.commit()
        new_id = cursor.lastrowid

        cursor.close()
        connection.close()

        # Emit schedule notification
        create_notification(
            recipient_role="candidate",
            title=f"New {interview_type} Interview Scheduled",
            message=f"You have an interview scheduled on {interview_date} from {start_time} to {end_time} with {interviewer_name}.",
            link="/candidate/dashboard",
            candidate_id=cand["id"],
            notification_type="interview_scheduled"
        )

        return jsonify({
            "success": True,
            "message": f"Interview successfully scheduled for {cand['name']} on {interview_date} at {start_time}!",
            "interview_id": new_id
        })
    except Exception as e:
        print("Error scheduling interview:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/interviews/update/<int:interview_id>", methods=["POST"])
def api_update_interview(interview_id):
    """Updates/reschedules an existing interview with conflict re-validation."""
    if "logged_in" not in session or session.get("role", "").lower() != "hr":
        return jsonify({"success": False, "message": "Unauthorized - HR role required"}), 403

    data = request.get_json(silent=True) or request.form
    interviewer_name = (data.get("interviewer_name") or "").strip()
    interviewer_email = (data.get("interviewer_email") or "").strip()
    interview_date = (data.get("interview_date") or "").strip()
    start_time = (data.get("start_time") or "").strip()
    end_time = (data.get("end_time") or "").strip()
    interview_type = (data.get("interview_type") or "Technical").strip()
    location_link = (data.get("location_link") or "").strip()
    status = (data.get("status") or "Rescheduled").strip()
    notes = (data.get("notes") or "").strip()

    if not interviewer_name or not interview_date or not start_time or not end_time:
        return jsonify({"success": False, "message": "Please fill in all required fields."}), 400

    if start_time >= end_time:
        return jsonify({"success": False, "message": "Invalid Time: Start time must be strictly before end time."}), 400

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role", "").lower() == "admin")

        # Verify existing interview
        cursor.execute("SELECT * FROM interviews WHERE id = %s", (interview_id,))
        existing = cursor.fetchone()
        if not existing:
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Interview record not found."}), 404

        if not verify_interview_ownership(cursor, interview_id, auth_hr_id, is_admin):
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Unauthorized access to interview"}), 403

        # Conflict check (exclude self)
        if status != "Cancelled":
            conflict_query = """
                SELECT id, candidate_name, candidate_email, interviewer_name,
                   DATE_FORMAT(interview_date, '%Y-%m-%d') as interview_date,
                   TIME_FORMAT(start_time, '%H:%i') as start_time,
                   TIME_FORMAT(end_time, '%H:%i') as end_time,
                   interview_type, status
            FROM interviews
            WHERE LOWER(interviewer_name) = LOWER(%s)
              AND interview_date = %s
              AND status != 'Cancelled'
              AND id != %s
              AND (start_time < %s AND end_time > %s)
            LIMIT 1
        """
            cursor.execute(conflict_query, (interviewer_name, interview_date, interview_id, end_time, start_time))
            conflict = cursor.fetchone()

            if conflict:
                cursor.close()
                connection.close()
                return jsonify({
                    "success": False,
                    "has_conflict": True,
                    "message": f"Interview Conflict: The interviewer '{interviewer_name}' already has an interview scheduled with {conflict['candidate_name']} from {conflict['start_time']} to {conflict['end_time']}.",
                    "conflict": conflict
                }), 409

        # Execute Update
        update_sql = """
            UPDATE interviews SET
                interviewer_name = %s,
                interviewer_email = %s,
                interview_date = %s,
                start_time = %s,
                end_time = %s,
                interview_type = %s,
                location_link = %s,
                status = %s,
                notes = %s,
                updated_at = NOW()
            WHERE id = %s
        """
        cursor.execute(update_sql, (
            interviewer_name, interviewer_email, interview_date, start_time, end_time,
            interview_type, location_link, status, notes, interview_id
        ))
        connection.commit()

        cursor.close()
        connection.close()

        return jsonify({"success": True, "message": "Interview details updated successfully!"})
    except Exception as e:
        print("Error updating interview:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/interviews/cancel/<int:interview_id>", methods=["POST"])
def api_cancel_interview(interview_id):
    """Cancels an interview schedule."""
    if "logged_in" not in session or session.get("role", "").lower() != "hr":
        return jsonify({"success": False, "message": "Unauthorized - HR role required"}), 403

    connection = get_connection()
    if not connection:
        return jsonify({"success": False, "message": "Database connection failed"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        auth_hr_id = get_authenticated_hr_id()
        is_admin = (session.get("role", "").lower() == "admin")

        if not verify_interview_ownership(cursor, interview_id, auth_hr_id, is_admin):
            cursor.close()
            connection.close()
            return jsonify({"success": False, "message": "Unauthorized access to interview"}), 403

        cursor.execute("UPDATE interviews SET status = 'Cancelled', updated_at = NOW() WHERE id = %s", (interview_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({"success": True, "message": "Interview successfully cancelled."})
    except Exception as e:
        print("Error cancelling interview:", e)
        if connection:
            connection.close()
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True
    )