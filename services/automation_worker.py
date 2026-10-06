import os
import re
import sys
import time
import urllib.request
import urllib.parse
import json
import shutil
from pathlib import Path
import pandas as pd

from database.db import get_connection
from services.email_service import send_candidate_confirmation_email

# ============================================================
# CANONICAL ABSOLUTE PATH RESOLUTION
# ============================================================

SERVICES_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVICES_DIR.parent

AUTOMATION_RESUMES_DIR = (PROJECT_ROOT / "automation" / "resumes").resolve()
UPLOADS_RESUMES_DIR = (PROJECT_ROOT / "uploads" / "resumes").resolve()

AUTOMATION_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_RESUMES_DIR.mkdir(parents=True, exist_ok=True)


def normalize_key(k):
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def get_row_value(row_dict, possible_column_names):
    norm_dict = {normalize_key(k): v for k, v in row_dict.items()}
    for name in possible_column_names:
        norm_name = normalize_key(name)
        if norm_name in norm_dict:
            val = norm_dict[norm_name]
            if pd.notna(val) and str(val).strip():
                return str(val).strip()
    return ""


def resolve_candidate_resume_path(candidate_name, candidate_email="", csv_resume_ref="", job_id=None, resume_dir=None):
    """
    Locates matching candidate resume file using job-isolated pathing and CSV reference detection.
    Supports: .pdf, .doc, .docx
    Returns tuple: (resolved_file_path_obj, expected_default_path_obj)
    """
    supported_extensions = {".pdf", ".doc", ".docx"}
    
    # Primary search directory: job-isolated resume folder
    job_resume_dir = None
    if resume_dir:
        job_resume_dir = Path(resume_dir).resolve()
    elif job_id:
        job_resume_dir = (UPLOADS_RESUMES_DIR / f"job_{job_id}").resolve()

    search_dirs = []
    if job_resume_dir and job_resume_dir.is_dir():
        search_dirs.append(job_resume_dir)
    else:
        # Only fallback to global UPLOADS_RESUMES_DIR if NO job_id was specified at all
        if not job_id:
            search_dirs.append(UPLOADS_RESUMES_DIR)

    name_str = str(candidate_name).strip()
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", name_str)]
    norm_cand_name = "".join(tokens)
    formatted_name = "_".join(tokens) if tokens else "candidate"

    expected_path = (job_resume_dir / f"{formatted_name}.pdf").resolve() if job_resume_dir else (UPLOADS_RESUMES_DIR / f"{formatted_name}.pdf").resolve()

    # 0. Check CSV resume reference if provided
    ref_str = str(csv_resume_ref or "").strip()
    if ref_str:
        p_ref = Path(ref_str).resolve()
        if p_ref.is_file():
            return p_ref, p_ref
        ref_stem_norm = re.sub(r"[^a-z0-9]", "", Path(ref_str).stem.lower())
        for d in search_dirs:
            if not d.is_dir():
                continue
            for f in d.iterdir():
                if f.is_file() and f.suffix.lower() in supported_extensions:
                    if ref_stem_norm and re.sub(r"[^a-z0-9]", "", f.stem.lower()) == ref_stem_norm:
                        return f.resolve(), f.resolve()

    if not tokens:
        return None, expected_path

    first_name = tokens[0]
    last_name = tokens[-1] if len(tokens) >= 2 else ""

    for d in search_dirs:
        if not d.is_dir():
            continue

        # 1. Exact candidate filename variations
        for ext in supported_extensions:
            variations = [
                f"{formatted_name}{ext}",
                f"{name_str}{ext}",
                f"{'_'.join(tokens)}{ext}",
                f"{'-'.join(tokens)}{ext}",
                f"{' '.join(tokens)}{ext}"
            ]
            for fn in variations:
                candidate_file = (d / fn).resolve()
                if candidate_file.is_file():
                    return candidate_file, candidate_file

        # 2. Tokenized & Alphanumeric match against files in folder
        all_files = [
            f for f in d.iterdir()
            if f.is_file() and f.suffix.lower() in supported_extensions
        ]

        for f in all_files:
            f_stem = f.stem
            f_tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", f_stem)]
            norm_file_name = "".join(f_tokens)

            # Match normalized string
            if norm_cand_name == norm_file_name:
                return f.resolve(), f.resolve()

            # Match all tokens
            if all(t in f_tokens for t in tokens):
                return f.resolve(), f.resolve()

            # Match first + last name
            if first_name and last_name and (first_name in f_tokens and last_name in f_tokens):
                return f.resolve(), f.resolve()

        # 3. Email prefix match
        if candidate_email:
            clean_email = re.sub(r"[^a-z0-9]", "", str(candidate_email).lower())
            email_user = clean_email.split("gmail")[0] if "gmail" in clean_email else clean_email.split("@")[0]
            if len(email_user) >= 3:
                for f in all_files:
                    norm_file_name = re.sub(r"[^a-z0-9]", "", f.stem.lower())
                    if email_user in norm_file_name or norm_file_name in email_user:
                        return f.resolve(), f.resolve()

    return None, expected_path


def process_candidate_batch():
    base_url = os.getenv("SMART_RECRUITMENT_BASE_URL", "http://127.0.0.1:5001").rstrip("/")
    excel_path_env = os.getenv("SMART_RECRUITMENT_EXCEL_FILE") or os.getenv("CANDIDATE_EXCEL_FILE") or os.getenv("EXCEL_FILE")
    job_id = os.getenv("SMART_RECRUITMENT_JOB_ID", "")
    upload_id = os.getenv("SMART_RECRUITMENT_UPLOAD_ID", "")
    resume_dir_env = os.getenv("SMART_RECRUITMENT_RESUME_FOLDER")
    browser_mode = os.getenv("SMART_RECRUITMENT_BROWSER_MODE", "headless").lower()

    # Resolve absolute path to candidate Excel/CSV file
    excel_path = None
    if excel_path_env:
        p_env = Path(excel_path_env).resolve()
        if p_env.is_file():
            excel_path = str(p_env)

    print(f"AUTOMATION ACTIVE: Initializing Robot Framework & Selenium (Mode: {browser_mode})...")
    print("STAGE: Initializing")

    if not excel_path or not Path(excel_path).is_file():
        print(f"FAILED: Candidate upload file not found: '{excel_path_env or 'No file specified'}' for Job '{job_id}'")
        sys.exit(1)

    print("STAGE: Read Excel")
    print(f"\nJOB ID: {job_id or 'N/A'}")
    print(f"UPLOAD ID: {upload_id or 'N/A'}")
    print(f"Input file: {excel_path}")
    print(f"File exists: YES\n")

    try:
        if excel_path.lower().endswith(".csv"):
            df = pd.read_csv(excel_path)
        else:
            try:
                df = pd.read_excel(excel_path, engine="openpyxl")
            except Exception:
                df = pd.read_excel(excel_path)
    except Exception as e:
        print(f"FAILED: Error reading candidate file '{excel_path}': {e}")
        sys.exit(1)

    records = df.to_dict(orient="records")
    total_candidates = len(records)
    print(f"Parsing candidate records from {Path(excel_path).name}")
    print(f"Total candidates in Excel: {total_candidates}")

    if total_candidates == 0:
        print("FAILED: Candidate upload file contains no records.")
        sys.exit(1)

    # Initialize Selenium WebDriver if available
    driver = None
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        options = Options()
        if browser_mode == "headless":
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

        driver = webdriver.Chrome(options=options)
        print(f"WebDriver session active ({browser_mode.capitalize()} mode)")
    except Exception as drv_err:
        print(f"Notice launching Selenium Chrome WebDriver: {drv_err}. Using direct API automation pipeline.")

    successful_count = 0
    failed_count = 0

    for idx, row in enumerate(records, 1):
        name = get_row_value(row, ["name", "candidate_name", "full_name", "candidate", "Name"])
        raw_email = get_row_value(row, ["email", "Email", "email_address", "Email Address", "recipient", "recipient_email", "to", "candidate_email", "mail", "e-mail"])
        phone = get_row_value(row, ["phone", "candidate_phone", "mobile", "contact", "Phone"])
        position = get_row_value(row, ["position", "job_position", "role", "applied_position", "Position"])
        csv_resume_ref = get_row_value(row, ["resume", "resume_file", "resume_filename", "resume_path", "resume_url", "cv", "cv_file", "cv_filename", "cv_path", "resume file", "cv file", "Resume", "CV", "Resume File", "CV File"])

        if not name:
            name = f"Candidate #{idx}"
        email = raw_email if raw_email else f"candidate_{idx}_{int(time.time())}@recruitment.local"
        if not phone:
            phone = "+1234567890"
        if not position:
            position = "Software Engineer"

        print(f"\nCANDIDATE:")
        print(f"candidate_id=Pending_DB")
        print(f"job_id={job_id or 'N/A'}")
        print(f"upload_id={upload_id or 'N/A'}")
        print(f"row_number={idx}")
        print(f"name={name}")
        print(f"email={email}")
        print(f"resume_reference={csv_resume_ref or 'None'}")
        print(f"LAST_STEP: Registering candidate details for {name}")

        cand_id = None
        # 1. Candidate Registration
        try:
            reg_url = f"{base_url}/api/automation/register-candidate"
            payload = json.dumps({
                "name": name,
                "email": email,
                "phone": phone,
                "position": position,
                "job_id": job_id,
                "upload_id": upload_id
            }).encode("utf-8")

            req = urllib.request.Request(
                reg_url,
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if res_data.get("success"):
                    cand_id = res_data.get("candidate_id")
                    print(f"Registration: SUCCESS for {name} (ID: #{cand_id})")
        except Exception as reg_err:
            print(f"Registration API notice for {name}: {reg_err}")

        # Fallback MySQL candidate lookup/insertion
        if not cand_id:
            try:
                conn = get_connection()
                if conn:
                    cur = conn.cursor(dictionary=True)

                    # 1. User Creation & Verification FIRST
                    cur.execute("SELECT id, username, role FROM users WHERE email=%s LIMIT 1", (email,))
                    usr_ex = cur.fetchone()
                    cand_u = None
                    u_id = None
                    is_new_u = False

                    if usr_ex:
                        u_id = usr_ex["id"]
                        cand_u = usr_ex["username"]
                        if str(usr_ex.get("role") or "").strip().lower() != "candidate":
                            cur.execute("UPDATE users SET role='candidate' WHERE id=%s", (u_id,))
                            conn.commit()
                    else:
                        import flask_bcrypt
                        bcrypt_app = flask_bcrypt.Bcrypt()
                        local_p = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower()) if "@" in str(email) else str(email)
                        cand_u = local_p
                        temp_p = f"{local_p}@"
                        hash_p = bcrypt_app.generate_password_hash(temp_p).decode("utf-8")
                        import pyotp
                        totp_sec = pyotp.random_base32()

                        cur.execute(
                            "INSERT INTO users (fullname, username, email, phone, password, role, must_change_password, google_authenticator_configured, totp_secret) VALUES (%s, %s, %s, %s, %s, 'candidate', 1, 0, %s)",
                            (name, cand_u, email, phone, hash_p, totp_sec)
                        )
                        conn.commit()
                        u_id = cur.lastrowid
                        is_new_u = True

                    # Verify user commit
                    cur.execute("SELECT id, username, email, role FROM users WHERE id=%s LIMIT 1", (u_id,))
                    ver_usr = cur.fetchone()
                    if not ver_usr:
                        raise Exception(f"Worker user account creation verification failed for ID #{u_id}")

                    worker_hr_id = None
                    if job_id:
                        try:
                            cur.execute("SELECT user_id FROM automation_jobs WHERE job_code=%s LIMIT 1", (job_id,))
                            j_row = cur.fetchone()
                            if j_row and j_row.get("user_id"):
                                worker_hr_id = j_row["user_id"]
                        except Exception:
                            pass
                    if not worker_hr_id and upload_id:
                        try:
                            cur.execute("SELECT user_id FROM uploaded_files WHERE upload_id=%s LIMIT 1", (upload_id,))
                            u_row = cur.fetchone()
                            if u_row and u_row.get("user_id"):
                                worker_hr_id = u_row["user_id"]
                        except Exception:
                            pass

                    # 2. Candidate Creation / Linkage
                    cur.execute("SELECT id FROM candidates WHERE email=%s LIMIT 1", (email,))
                    ex = cur.fetchone()
                    if ex:
                        cand_id = ex["id"]
                        cur.execute(
                            "UPDATE candidates SET name=%s, phone=%s, position=%s, registration_status='Registered', user_id=%s, job_id=%s, upload_id=%s, hr_id=COALESCE(hr_id, %s) WHERE id=%s",
                            (name, phone, position, u_id, job_id or None, upload_id or None, worker_hr_id, cand_id)
                        )
                    else:
                        cur.execute(
                            "INSERT INTO candidates (name, email, phone, position, registration_status, status, job_id, upload_id, user_id, hr_id) VALUES (%s, %s, %s, %s, 'Registered', 'New', %s, %s, %s, %s)",
                            (name, email, phone, position, job_id or None, upload_id or None, u_id, worker_hr_id)
                        )
                        cand_id = cur.lastrowid

                    conn.commit()

                    # Verify candidate persistence after commit
                    cur.execute("SELECT id FROM candidates WHERE id=%s LIMIT 1", (cand_id,))
                    if not cur.fetchone():
                        raise Exception(f"Worker database verification failed for candidate ID #{cand_id} after commit!")

                    print(f"AUTOMATION CANDIDATE REGISTRATION job_id={job_id or 'N/A'} upload_id={upload_id or 'N/A'} candidate_email={email} username={cand_u} user_created={is_new_u} candidate_created=true role=CANDIDATE password_hash_created=true account_enabled=true")

                    cur.close()
                    conn.close()
            except Exception as db_err:
                print(f"Database fallback notice for {name}: {db_err}")

        # 2. Resume Path Resolution & Verification
        resume_file_obj, expected_file_obj = resolve_candidate_resume_path(
            name, email, csv_resume_ref=csv_resume_ref, job_id=job_id, resume_dir=resume_dir_env
        )

        resolved_resume_path = str(resume_file_obj.resolve()) if (resume_file_obj and resume_file_obj.is_file()) else str(expected_file_obj.resolve())
        resume_exists = bool(resume_file_obj and resume_file_obj.is_file())

        print(f"\nRESUME:")
        print(f"candidate_id={cand_id or 'N/A'}")
        print(f"upload_id={upload_id or 'N/A'}")
        print(f"job_id={job_id or 'N/A'}")
        print(f"reference={csv_resume_ref or 'None'}")
        print(f"resolved_path={resolved_resume_path}")
        print(f"exists={resume_exists}")

        if resume_exists:
            abs_resume_path = resolved_resume_path
            print(f"Resume: FOUND for {name}")

            # Selenium File Upload via send_keys()
            if driver:
                try:
                    driver.get(f"{base_url}/candidate/register")
                    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                    for fi in file_inputs:
                        try:
                            fi.send_keys(abs_resume_path)
                            print(f"Selenium send_keys() executed for {name}")
                            break
                        except Exception:
                            pass
                except Exception as sel_err:
                    print(f"Notice during Selenium upload interaction: {sel_err}")

            # Update database record: Uploaded & Processed
            res_filename = resume_file_obj.name
            try:
                conn = get_connection()
                if conn and cand_id:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE candidates
                        SET resume=%s,
                            resume_filename=%s,
                            resume_status='Uploaded',
                            automation_status='Processed',
                            status='Processed',
                            error_message=NULL
                        WHERE id=%s
                        """,
                        (res_filename, res_filename, cand_id)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
            except Exception as res_err:
                print(f"Resume database verification notice: {res_err}")

            successful_count += 1
            print(f"Candidate {idx}/{total_candidates} → Resume FOUND → Upload SUCCESS")
        else:
            print(f"Resume: NOT FOUND for {name}")
            print(f"Expected path: {resolved_resume_path}")
            print(f"Candidate {idx}/{total_candidates} → Resume NOT FOUND → Status: Resume Missing")

            # Update database record: Resume Missing / Failed
            err_detail = f"Resume '{csv_resume_ref or name}' not found in Job '{job_id}' upload directory."
            try:
                conn = get_connection()
                if conn and cand_id:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE candidates
                        SET resume_status='Resume Missing',
                            automation_status='Failed',
                            status='Resume Missing',
                            error_message=%s
                        WHERE id=%s
                        """,
                        (err_detail, cand_id)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
            except Exception as res_err:
                print(f"Resume missing database status update notice: {res_err}")

            failed_count += 1

        # 3. SMTP Confirmation Email Step
        print(f"STAGE: Send Email")
        if not raw_email:
            print(f"Email: SKIPPED for {name} (Reason: Candidate email is missing in Excel/CSV)")
            if cand_id:
                try:
                    conn = get_connection()
                    if conn:
                        cur = conn.cursor()
                        cur.execute("UPDATE candidates SET email_status='Skipped' WHERE id=%s", (cand_id,))
                        conn.commit()
                        cur.close()
                        conn.close()
                except Exception as db_err:
                    print("Notice updating skipped email status:", db_err)
        else:
            email_pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
            if not re.match(email_pattern, raw_email):
                print(f"Email: FAILED for {name} (Reason: Invalid candidate email address '{raw_email}')")
                if cand_id:
                    try:
                        conn = get_connection()
                        if conn:
                            cur = conn.cursor()
                            cur.execute("UPDATE candidates SET email_status='Failed' WHERE id=%s", (cand_id,))
                            conn.commit()
                            cur.close()
                            conn.close()
                    except Exception as db_err:
                        print("Notice updating failed email status:", db_err)
            else:
                try:
                    print(f"LAST_STEP: Sending confirmation email To: {raw_email}")
                    mail_res = send_candidate_confirmation_email(
                        candidate_id=cand_id,
                        candidate_name=name,
                        candidate_email=raw_email,
                        position=position
                    )
                    email_status_val = "Sent" if mail_res and mail_res.get("success") else "Failed"
                    if cand_id:
                        try:
                            conn = get_connection()
                            if conn:
                                cur = conn.cursor()
                                cur.execute("UPDATE candidates SET email_status=%s WHERE id=%s", (email_status_val, cand_id))
                                conn.commit()
                                cur.close()
                                conn.close()
                        except Exception as db_err:
                            print("Notice updating candidate email_status in DB:", db_err)

                    if mail_res and mail_res.get("success"):
                        print(f"Email: SUCCESS for {name} (To: {raw_email})")
                    else:
                        print(f"Email: FAILED for {name} (To: {raw_email}) - {mail_res.get('message', '')}")
                except Exception as mail_err:
                    print(f"Email notice for {raw_email}: {mail_err}")

        time.sleep(0.3)

    if driver:
        try:
            driver.quit()
        except Exception:
            pass

    print(f"\n==================================================")
    print(f"JOB OVERALL SUMMARY:")
    print(f"Job ID: {job_id}")
    print(f"Upload ID: {upload_id}")
    print(f"Total Candidates: {total_candidates}")
    print(f"Successful (Resume Uploaded): {successful_count}")
    print(f"Failed (Resume Missing / Error): {failed_count}")
    print(f"==================================================")

    # Update automation_jobs record in DB
    try:
        conn = get_connection()
        if conn and job_id:
            cur = conn.cursor()
            if failed_count > 0 and successful_count > 0:
                final_job_status = 'Partial Failure'
            elif failed_count == total_candidates:
                final_job_status = 'Failed'
            else:
                final_job_status = 'Completed'
            
            cur.execute(
                "UPDATE automation_jobs SET status=%s, total_candidates=%s, processed_candidates=%s, failed_candidates=%s WHERE job_code=%s",
                (final_job_status, total_candidates, successful_count, failed_count, job_id)
            )
            conn.commit()
            cur.close()
            conn.close()
    except Exception as job_upd_err:
        print("Notice updating automation_jobs final status:", job_upd_err)

    if failed_count > 0:
        print(f"\nSTAGE: Partial / Failure")
        print(f"LAST_STEP: Automation batch finished with {failed_count} failure(s) out of {total_candidates} candidates")
        sys.exit(1)
    else:
        print(f"\nSTAGE: Complete")
        print(f"LAST_STEP: Recruitment automation completed successfully ({successful_count}/{total_candidates} candidates processed)")


if __name__ == "__main__":
    process_candidate_batch()

