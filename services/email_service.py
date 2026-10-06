import os
import re
import smtplib
import socket
import logging
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

logger = logging.getLogger(__name__)

def load_env_file():
    """
    Safely loads key-value pairs from .env into os.environ if not already present.
    """
    try:
        base_dir = Path(__file__).resolve().parent.parent
        env_path = base_dir / ".env"
        if env_path.is_file():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
    except Exception as e:
        logger.warning("Notice loading .env file: %s", e)

def get_smtp_config():
    """
    Reads SMTP configuration strictly from server environment / .env file.
    Supports SMTP_HOST, SMTP_PORT, SMTP_USERNAME / SMTP_USER, 
    SMTP_EMAIL / SMTP_FROM, SMTP_PASSWORD / SMTP_PASS, SMTP_SECURITY.
    NEVER stores or logs sensitive credentials.
    """
    load_env_file()
    host = os.getenv("SMTP_HOST", "").strip() or os.getenv("MAIL_SERVER", "").strip()
    port_val = os.getenv("SMTP_PORT", "").strip() or os.getenv("MAIL_PORT", "").strip()
    try:
        port = int(port_val) if port_val else 587
    except ValueError:
        port = 587

    username = os.getenv("SMTP_USERNAME", "").strip() or os.getenv("SMTP_USER", "").strip() or os.getenv("MAIL_USERNAME", "").strip()
    from_email = os.getenv("SMTP_EMAIL", "").strip() or os.getenv("SMTP_FROM", "").strip() or os.getenv("MAIL_DEFAULT_SENDER", "").strip() or username
    password = os.getenv("SMTP_PASSWORD", "") or os.getenv("SMTP_PASS", "") or os.getenv("MAIL_PASSWORD", "")
    security = (os.getenv("SMTP_SECURITY", "").strip() or os.getenv("MAIL_USE_TLS", "") or "tls").strip().lower()

    return {
        "host": host,
        "port": port,
        "username": username,
        "from_email": from_email,
        "password": password,
        "security": security
    }

def validate_email_address(email):
    """
    Validates recipient email address syntax according to RFC 5322 specifications.
    """
    if not email or not isinstance(email, str):
        return False
    email_clean = email.strip()
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email_clean))

def mask_secret(text, secret):
    """
    Utility to scrub passwords and secrets from log strings.
    """
    if not text or not secret:
        return str(text)
    return str(text).replace(str(secret), "******")

def send_smtp_email(to_email, subject, body_text, body_html=None):
    """
    Sends an email using configured SMTP environment settings.
    Guarantees robust deliverability (Date, Message-ID, Reply-To, From/User alignment).
    Inspects SMTP server return codes for recipient rejections.
    Returns dict: {"status": "success"/"failed", "success": True/False, "message": "..."}
    """
    if not to_email or not str(to_email).strip():
        logger.error("SMTP Delivery Aborted: Missing recipient email address.")
        return {
            "status": "failed",
            "success": False,
            "message": "Recipient email address is missing or empty."
        }

    recipient_clean = to_email.strip()
    if not validate_email_address(recipient_clean):
        logger.error("SMTP Delivery Aborted: Invalid recipient email syntax: %s", recipient_clean)
        return {
            "status": "failed",
            "success": False,
            "message": f"Invalid recipient email address format: '{recipient_clean}'."
        }

    config = get_smtp_config()
    host = config["host"]
    port = config["port"]
    username = config["username"]
    from_email = config["from_email"]
    password = config["password"]
    security = config["security"]

    if not host:
        err_msg = "SMTP_HOST is not configured in backend environment variables (.env)."
        logger.error("⚠️ %s", err_msg)
        return {
            "status": "failed",
            "success": False,
            "message": err_msg
        }

    # Format From header with friendly display name & ensure alignment with authenticated user
    sender_addr = from_email or username or "no-reply@recruitment.com"
    if "@" in sender_addr:
        domain = sender_addr.split("@")[1].lower()
    else:
        domain = "localhost"

    # Construct MIMEMultipart message with required RFC deliverability headers
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject or "Application Update"
    msg["From"] = f"Smart Recruitment <{sender_addr}>"
    msg["To"] = recipient_clean
    msg["Reply-To"] = sender_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["X-Mailer"] = "Smart-Recruitment-Automation/1.0"

    # Attach Plain Text & HTML bodies
    msg.attach(MIMEText(body_text or "", "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    server = None
    try:
        print(f"📧 Connecting to SMTP Server {host}:{port} (Security: {security.upper()}) for {recipient_clean}...")
        logger.info("Connecting to SMTP Server %s:%s (Security: %s)", host, port, security.upper())

        # Establish connection with timeout handling
        if security == "ssl" or port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            server.ehlo()
            if security in ["tls", "starttls"] or port == 587:
                server.starttls()
                server.ehlo()

        # SMTP Authentication
        if username and password:
            clean_pass = password.replace(" ", "")
            try:
                server.login(username, clean_pass)
            except smtplib.SMTPAuthenticationError:
                if clean_pass != password:
                    server.login(username, password)
                else:
                    raise

        # Transmit email & inspect response for partial/recipient rejections
        refused_dict = server.send_message(msg)

        if refused_dict:
            refused_info = []
            for rcpt, (code, err_bytes) in refused_dict.items():
                err_str = err_bytes.decode("utf-8", errors="replace") if isinstance(err_bytes, bytes) else str(err_bytes)
                refused_info.append(f"{rcpt}: [{code}] {err_str}")
            
            full_refused_str = "; ".join(refused_info)
            print(f"❌ SMTP Message Rejected by server for recipient: {full_refused_str}")
            logger.error("SMTP Message Rejected by server for recipient: %s", full_refused_str)
            return {
                "status": "failed",
                "success": False,
                "message": f"SMTP server rejected delivery to recipient: {full_refused_str}"
            }

        print(f"✅ SMTP email successfully delivered to {recipient_clean} via {host}.")
        logger.info("SMTP email successfully delivered to %s via %s.", recipient_clean, host)
        return {
            "status": "success",
            "success": True,
            "message": "Email sent successfully."
        }

    except smtplib.SMTPAuthenticationError as auth_err:
        safe_msg = mask_secret(str(auth_err), password)
        print(f"❌ SMTP Authentication Failure (535 Bad Credentials): {safe_msg}")
        logger.error("SMTP Authentication Failure for user %s: %s", username, safe_msg)
        return {
            "status": "failed",
            "success": False,
            "message": "SMTP authentication failed: Invalid username or password / App Password required."
        }
    except smtplib.SMTPConnectError as conn_err:
        print(f"❌ SMTP Connection Failure: Could not connect to server {host}:{port}.")
        logger.error("SMTP Connection Failure to %s:%s - %s", host, port, conn_err)
        return {
            "status": "failed",
            "success": False,
            "message": f"Could not connect to SMTP server at {host}:{port}."
        }
    except socket.timeout:
        print(f"❌ SMTP Connection Timeout: Connection to {host}:{port} timed out after 15 seconds.")
        logger.error("SMTP Connection Timeout to %s:%s", host, port)
        return {
            "status": "failed",
            "success": False,
            "message": f"SMTP server connection timed out ({host}:{port}). Please check firewall/network rules."
        }
    except smtplib.SMTPException as smtp_err:
        safe_err = mask_secret(str(smtp_err), password)
        print(f"❌ SMTP Protocol Error: {safe_err}")
        logger.error("SMTP Protocol Error: %s", safe_err)
        return {
            "status": "failed",
            "success": False,
            "message": f"SMTP server rejected command: {safe_err}"
        }
    except Exception as e:
        safe_error = mask_secret(str(e), password)
        print(f"❌ Unexpected SMTP Error: {safe_error}")
        logger.error("Unexpected SMTP Error: %s", safe_error)
        return {
            "status": "failed",
            "success": False,
            "message": f"SMTP email delivery failed: {safe_error}"
        }
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass

def send_candidate_confirmation_email(candidate_data=None, candidate_id=None, candidate_name=None, candidate_email=None, position=None, subject=None, message=None, username=None, temp_password=None, base_url="http://127.0.0.1:5000"):
    """
    Sends SmartRecruitment Account Created email for newly created candidate accounts.
    Contains ONLY:
    - SmartRecruitment Account heading
    - Your SmartRecruitment account has been created successfully.
    - Username, Email, Temporary Password, Login URL
    - Login prompt & signature
    Does NOT contain candidate name, position, application status, resume status, or recruitment details.
    """
    if isinstance(candidate_data, dict):
        email = candidate_data.get("email") or candidate_data.get("candidate_email") or ""
        assigned_username = candidate_data.get("username") or extract_username_from_email(email)
        tp = candidate_data.get("temp_password") or candidate_data.get("temporary_password") or temp_password or generate_candidate_temp_password(email)
    else:
        email = candidate_email or ""
        assigned_username = username or extract_username_from_email(email)
        tp = temp_password or generate_candidate_temp_password(email)

    mail_subject = subject or "SmartRecruitment Account Created"
    login_url = f"{base_url.rstrip('/')}/login"

    if message:
        body_text = message
        body_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{mail_subject}</title></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #4f46e5; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
        <h2 style="color: #ffffff; margin: 0;">SmartRecruitment Account</h2>
    </div>
    <div style="background-color: #ffffff; padding: 30px; border: 1px solid #e5e7eb; border-radius: 0 0 8px 8px;">
        <p>{message.replace('\n', '<br>')}</p>
        <br>
        <p style="margin-bottom: 0;">Best regards,</p>
        <p style="margin-top: 5px;"><strong>Smart Recruitment Team</strong></p>
    </div>
</body>
</html>
"""
    else:
        body_text = f"""SmartRecruitment Account

Your SmartRecruitment account has been created successfully.

Username: {assigned_username}
Email: {email}
Temporary Password: {tp}
Login URL: {login_url}

Please log in using the above credentials and change your password after your first login.

Best regards,
Smart Recruitment Team
"""

        body_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{mail_subject}</title></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #4f46e5; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
        <h2 style="color: #ffffff; margin: 0;">SmartRecruitment Account</h2>
    </div>
    <div style="background-color: #ffffff; padding: 30px; border: 1px solid #e5e7eb; border-radius: 0 0 8px 8px;">
        <p style="margin-top: 0;">Your SmartRecruitment account has been created successfully.</p>
        <p style="margin: 5px 0;"><strong>Username:</strong> {assigned_username}</p>
        <p style="margin: 5px 0;"><strong>Email:</strong> {email}</p>
        <p style="margin: 5px 0;"><strong>Temporary Password:</strong> {tp}</p>
        <p style="margin: 5px 0;"><strong>Login URL:</strong> <a href="{login_url}" style="color: #4f46e5;">{login_url}</a></p>
        <br>
        <p>Please log in using the above credentials and change your password after your first login.</p>
        <br>
        <p style="margin-bottom: 0;">Best regards,</p>
        <p style="margin-top: 5px;"><strong>Smart Recruitment Team</strong></p>
    </div>
</body>
</html>
"""

    return send_smtp_email(
        to_email=email,
        subject=mail_subject,
        body_text=body_text,
        body_html=body_html
    )

SUPPORTED_EMAIL_COLUMNS = [
    "email",
    "email_address",
    "emailaddress",
    "recipient",
    "recipient_email",
    "recipientemail",
    "to",
    "candidate_email",
    "candidateemail",
    "mail",
    "e-mail",
    "email address",
    "recipient email"
]

def detect_email_column(df, filename="file"):
    """
    Detects recipient email column in a pandas DataFrame.
    Returns tuple: (column_name, None) if found, OR (None, clear_error_message) if not found.
    """
    if df is None or df.empty:
        return None, f"File '{filename}' contains no data rows."

    # 1. Header Name Matching against supported column list
    for col in df.columns:
        norm_col = re.sub(r"[^a-z0-9]", "", str(col).lower())
        if norm_col in [re.sub(r"[^a-z0-9]", "", c.lower()) for c in SUPPORTED_EMAIL_COLUMNS]:
            return col, None

    # 2. Cell Pattern Inspection Fallback
    for col in df.columns:
        non_null_vals = df[col].dropna().astype(str).str.strip()
        valid_matches = [v for v in non_null_vals if validate_email_address(v)]
        if len(valid_matches) > 0:
            return col, None

    # 3. Return explicit clear error message detailing missing column
    err_msg = (
        f"Missing recipient email column in file '{filename}'. "
        f"Could not automatically detect a column matching: email, Email, email_address, Email Address, recipient, recipient_email, to."
    )
    return None, err_msg


SUPPORTED_RESUME_COLUMNS = [
    "resume",
    "resume_file",
    "resume_filename",
    "resume_path",
    "resume_url",
    "cv",
    "cv_file",
    "cv_filename",
    "cv_path",
    "resume file",
    "cv file",
    "resume filename",
    "resume reference",
    "resumefile",
    "resumefilename",
    "resumepath",
    "resumeurl"
]

def detect_resume_column(df):
    """
    Detects candidate resume column in a pandas DataFrame case-insensitively.
    Returns column_name string if found, or None if not found.
    """
    if df is None or df.empty:
        return None

    supported_norm = [re.sub(r"[^a-z0-9]", "", c.lower()) for c in SUPPORTED_RESUME_COLUMNS]
    for col in df.columns:
        norm_col = re.sub(r"[^a-z0-9]", "", str(col).lower())
        if norm_col in supported_norm:
            return col
    return None


def resolve_candidate_resume_for_job(cand_name, cand_email, csv_resume_ref, job_id, upload_id=None):
    """
    Resolves candidate physical resume file strictly scoped to current job_id.
    - Priority 1: Check job-isolated directory `uploads/resumes/job_{job_id}/` for exact match against `csv_resume_ref`
                  (supports case-insensitive stem & extensions: .pdf, .PDF, .doc, .DOC, .docx, .DOCX).
    - Priority 2: Check candidate name token matching in `uploads/resumes/job_{job_id}/`.
    - Priority 3: Check candidate email prefix match in `uploads/resumes/job_{job_id}/`.
    - Priority 4: Check if `csv_resume_ref` is a valid absolute path or URL.
    - Returns tuple: (resolved_path_str_or_None, status_str) where status_str is 'Uploaded' or 'Resume Missing'.
    """
    from pathlib import Path
    import re
    supported_extensions = {".pdf", ".doc", ".docx"}
    
    project_root = Path(__file__).resolve().parent.parent

    # Priority 4 Check: Direct URL or absolute path in csv_resume_ref
    ref_str = str(csv_resume_ref or "").strip()
    if ref_str:
        if ref_str.startswith("http://") or ref_str.startswith("https://"):
            return ref_str, "Uploaded"
        p_ref = Path(ref_str).resolve()
        if p_ref.is_file():
            return str(p_ref), "Uploaded"

    # Resolve job-specific resume folder
    job_dir = (project_root / "uploads" / "resumes" / f"job_{job_id}").resolve() if job_id else None

    if not job_dir or not job_dir.is_dir():
        # Also check fallback global directory if created during this exact upload
        job_dir = (project_root / "uploads" / "resumes").resolve()

    if not job_dir.is_dir():
        return None, "Resume Missing"

    all_job_files = [f for f in job_dir.iterdir() if f.is_file() and f.suffix.lower() in supported_extensions]

    # Priority 1: Exact / Case-Insensitive filename check against csv_resume_ref
    if ref_str:
        ref_path = Path(ref_str)
        ref_stem_norm = re.sub(r"[^a-z0-9]", "", ref_path.stem.lower())
        for f in all_job_files:
            f_stem_norm = re.sub(r"[^a-z0-9]", "", f.stem.lower())
            if ref_stem_norm and f_stem_norm == ref_stem_norm:
                return str(f.resolve()), "Uploaded"

    # Priority 2: Candidate Name Tokenized Match in job_dir
    name_str = str(cand_name or "").strip()
    name_tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", name_str)]
    norm_cand_name = "".join(name_tokens)

    if norm_cand_name:
        for f in all_job_files:
            f_tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", f.stem)]
            norm_f = "".join(f_tokens)
            if norm_cand_name == norm_f or all(t in f_tokens for t in name_tokens):
                return str(f.resolve()), "Uploaded"

    # Priority 3: Email Prefix Match in job_dir
    if cand_email:
        clean_email = str(cand_email).strip().lower()
        local_part = re.sub(r"[^a-z0-9]", "", clean_email.split("@")[0])
        if len(local_part) >= 3:
            for f in all_job_files:
                norm_f = re.sub(r"[^a-z0-9]", "", f.stem.lower())
                if local_part in norm_f or norm_f in local_part:
                    return str(f.resolve()), "Uploaded"

    return None, "Resume Missing"


def process_excel_email_sending(excel_file_source, subject="Recruitment Notification", body_text="Hello, thank you for your application.", body_html=None):
    """
    Reads recipient email addresses from an Excel (.xlsx, .xls) or CSV file source,
    extracts the email column, validates and cleans each recipient email address,
    and sends individual SMTP email messages to each valid recipient.
    """
    return process_multi_file_email_batch(
        file_sources=[excel_file_source],
        subject=subject,
        body_text=body_text,
        body_html=body_html
    )


import secrets
import string
from database.db import get_connection

def extract_username_from_email(email):
    """
    Extracts the local part before '@' from an email address.
    e.g. 'foramsoni2004@gmail.com' -> 'foramsoni2004'
    e.g. 'rahul123@yahoo.com' -> 'rahul123'
    e.g. 'john.doe@outlook.com' -> 'john.doe'
    """
    email_clean = str(email or "").strip().lower()
    if "@" in email_clean:
        local_part = email_clean.split("@", 1)[0].strip()
    else:
        local_part = email_clean.strip()
    return local_part if local_part else "candidate"


def generate_candidate_temp_password(email):
    """
    Generates temporary password from candidate email local-part by taking everything BEFORE '@' and appending '@'.
    Examples:
    - foramsoni2004@gmail.com -> foramsoni2004@
    - rahul123@yahoo.com -> rahul123@
    - john.doe@outlook.com -> john.doe@
    """
    email_clean = str(email or "").strip().lower()
    if "@" in email_clean:
        local_part = email_clean.split("@", 1)[0].strip()
    else:
        local_part = email_clean.strip()
    return f"{local_part}@"


def generate_unique_username(email, cursor):
    """
    Generates a unique username in the users table without @domain.
    Appends numeric suffix if base username exists.
    """
    base_username = extract_username_from_email(email)
    candidate_username = base_username
    counter = 1
    while True:
        cursor.execute("SELECT id FROM users WHERE username = %s LIMIT 1", (candidate_username,))
        if not cursor.fetchone():
            return candidate_username
        candidate_username = f"{base_username}{counter}"
        counter += 1


def generate_secure_temp_password(length=12):
    """
    Generates a cryptographically secure temporary password.
    Contains uppercase, lowercase, digit, and special character.
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)
                and any(c in "!@#$%^&*" for c in password)):
            return password


def process_multi_file_email_batch(file_sources, subject=None, body_text=None, body_html=None, job_id=None, user_id=None, base_url="http://127.0.0.1:5000", retry_failed=False, upload_id=None, hr_id=None):
    """
    Processes multiple Excel (.xlsx, .xls) and CSV (.csv) files:
    - Reads ALL rows across ALL files.
    - Validates email addresses and deduplicates cross-file recipients.
    - Automatically creates Candidate accounts in database (`users` table) with:
      * Domain-free username (`email.split('@')[0]`)
      * Cryptographically secure temporary password
      * Bcrypt hashed password in DB
      * `role = 'candidate'` and `must_change_password = 1`
    - Dispatches SMTP registration/confirmation email to EACH candidate with login credentials & URL.
    - Tracks per-candidate status (Registered, Registration Failed, Email Sent, Email Failed).
    - Resume-safe: skips sending duplicate emails if candidate was already processed.
    - Never stops early on row failures.
    - Returns full summary metrics.
    """
    import io
    import pandas as pd
    from datetime import datetime
    import flask_bcrypt

    bcrypt_app = flask_bcrypt.Bcrypt()

    file_results = []
    global_recipients = {}  # {clean_email_lower: candidate_data_dict}
    
    total_rows = 0
    valid_emails_count = 0
    duplicate_emails_count = 0
    total_processed_files = 0
    total_failed_files = 0

    if not isinstance(file_sources, list):
        file_sources = [file_sources]

    # 1. Process files and extract clean recipients with cross-file deduplication
    for src in file_sources:
        filename = getattr(src, "filename", "") or (Path(src).name if isinstance(src, (str, Path)) else "uploaded_file")
        file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "xlsx"

        try:
            # Read DataFrame
            if isinstance(src, (str, Path)):
                p = Path(src)
                if not p.is_file():
                    total_failed_files += 1
                    file_results.append({"filename": filename, "status": "Failed", "error_message": f"File not found: {filename}"})
                    continue
                if p.suffix.lower() == ".csv":
                    df = pd.read_csv(p)
                else:
                    try:
                        df = pd.read_excel(p, engine="openpyxl")
                    except Exception:
                        df = pd.read_excel(p)
            else:
                file_bytes = src.read() if hasattr(src, "read") else src
                if hasattr(src, "seek"):
                    src.seek(0)
                bytes_io = io.BytesIO(file_bytes) if isinstance(file_bytes, bytes) else file_bytes
                if file_ext == "csv":
                    df = pd.read_csv(bytes_io)
                else:
                    try:
                        df = pd.read_excel(bytes_io, engine="openpyxl")
                    except Exception:
                        bytes_io.seek(0)
                        df = pd.read_excel(bytes_io)

            if df is None or df.empty:
                total_failed_files += 1
                file_results.append({"filename": filename, "status": "Failed", "error_message": "File contains no data rows."})
                continue

            total_rows += len(df)

            # Detect Email and Resume Columns
            email_col, col_err = detect_email_column(df, filename=filename)
            if col_err or not email_col:
                total_failed_files += 1
                file_results.append({"filename": filename, "status": "Failed", "error_message": col_err})
                continue

            resume_col = detect_resume_column(df)

            # Extract Rows
            header_names_lower = set([str(c).strip().lower() for c in df.columns] + SUPPORTED_EMAIL_COLUMNS)
            file_valid_count = 0

            for idx, row in df.iterrows():
                val = row[email_col]
                if pd.isna(val) or not str(val).strip():
                    continue

                raw_email = str(val).strip()
                if raw_email.lower() in header_names_lower or not validate_email_address(raw_email):
                    continue

                valid_emails_count += 1
                clean_key = raw_email.lower()

                # Cross-file deduplication (first file origin preserved)
                if clean_key in global_recipients:
                    duplicate_emails_count += 1
                    continue

                file_valid_count += 1
                cand_name = str(row.get("name") or row.get("Candidate Name") or row.get("Full Name") or "").strip() or f"Candidate {idx+1}"
                cand_phone = str(row.get("phone") or row.get("Phone") or row.get("Mobile") or "").strip() or "+1234567890"
                cand_pos = str(row.get("position") or row.get("Position") or row.get("Job Position") or row.get("Role") or "").strip() or "Software Engineer"
                cand_resume_ref = str(row.get(resume_col)).strip() if resume_col and pd.notna(row.get(resume_col)) else ""
                
                global_recipients[clean_key] = {
                    "email": raw_email,
                    "source_file": filename,
                    "name": cand_name,
                    "phone": cand_phone,
                    "position": cand_pos,
                    "resume_ref": cand_resume_ref,
                    "row_idx": idx + 1
                }

            total_processed_files += 1
            file_results.append({
                "filename": filename,
                "file_type": file_ext,
                "status": "Completed",
                "total_rows": len(df),
                "valid_recipients": file_valid_count,
                "error_message": None
            })

        except Exception as file_err:
            total_failed_files += 1
            file_results.append({"filename": filename, "status": "Failed", "error_message": str(file_err)})

    # 2. Candidate Auto-Registration & SMTP Email Dispatch for ALL Deduplicated Recipients
    recipient_results = []
    successfully_registered = 0
    already_registered_count = 0
    registration_failures = 0
    emails_sent = 0
    email_failures = 0

    login_url = f"{base_url.rstrip('/')}/login"

    for clean_key, rec in global_recipients.items():
        raw_email = rec["email"]
        src_file = rec["source_file"]
        name = rec["name"]
        phone = rec["phone"]
        position = rec["position"]
        cand_resume_ref = rec.get("resume_ref") or ""

        # Resolve candidate physical resume scoped strictly to job_id
        resolved_resume_path, resume_status_val = resolve_candidate_resume_for_job(
            cand_name=name,
            cand_email=raw_email,
            csv_resume_ref=cand_resume_ref,
            job_id=job_id
        )

        logger.info(
            "[JOB %s | ROW %s] Candidate '%s' (%s) | CSV Resume Ref: '%s' | Resolved: '%s' | Resume Status: %s",
            job_id, rec.get("row_idx", 0), name, raw_email, cand_resume_ref, resolved_resume_path or "None", resume_status_val
        )

        temp_password = None
        assigned_username = None
        cand_user_id = None
        cand_id = None
        previous_email_status = None
        reg_status = "Registered"
        reg_error = None
        is_new_account = False

        # Auto-Register Candidate in Database
        try:
            conn = get_connection()
            if conn:
                cur = conn.cursor(dictionary=True)

                logger.info("AUTOMATION REGISTRATION START email=%s", raw_email)

                # Check if account already exists in users table by email or username
                cur.execute(
                    "SELECT id, username, email, role, password FROM users WHERE email = %s OR username = %s OR LOWER(email) = LOWER(%s) OR LOWER(username) = LOWER(%s) LIMIT 1",
                    (raw_email, extract_username_from_email(raw_email), raw_email, extract_username_from_email(raw_email))
                )
                existing_user = cur.fetchone()

                if existing_user:
                    cand_user_id = existing_user["id"]
                    assigned_username = existing_user["username"]
                    already_registered_count += 1
                    is_new_account = False
                    if str(existing_user.get("role") or "").strip().lower() != "candidate":
                        cur.execute("UPDATE users SET role='candidate' WHERE id=%s", (cand_user_id,))
                        conn.commit()
                    logger.info("USER CREATED user_id=%s username=%s role=CANDIDATE active=true", cand_user_id, assigned_username)
                else:
                    # Generate domain-free username and candidate temp password (local-part + "@")
                    assigned_username = generate_unique_username(raw_email, cur)
                    temp_password = generate_candidate_temp_password(raw_email)
                    hashed_pw = bcrypt_app.generate_password_hash(temp_password).decode("utf-8")

                    import pyotp
                    totp_sec = pyotp.random_base32()
                    cur.execute(
                        """
                        INSERT INTO users (fullname, username, email, phone, password, role, must_change_password, google_authenticator_configured, totp_secret)
                        VALUES (%s, %s, %s, %s, %s, 'candidate', 1, 0, %s)
                        """,
                        (name, assigned_username, raw_email, phone, hashed_pw, totp_sec)
                    )
                    cand_user_id = cur.lastrowid
                    conn.commit()
                    successfully_registered += 1
                    is_new_account = True
                    logger.info("USER CREATED user_id=%s username=%s role=CANDIDATE active=true", cand_user_id, assigned_username)

                # 1b. User Persistence & Auth Verification
                cur.execute("SELECT id, username, email, role, password FROM users WHERE id=%s LIMIT 1", (cand_user_id,))
                ver_usr = cur.fetchone()
                if not ver_usr:
                    raise Exception(f"User account creation failed or transaction not committed for user_id #{cand_user_id}")

                logger.info("AUTOMATION ACCOUNT username=%s email=%s role=CANDIDATE user_created=%s user_verified=true", assigned_username, raw_email, is_new_account)
                logger.info("USER COMMIT VERIFIED user_exists=true")

                # Test auth lookup simulating login
                cur.execute(
                    "SELECT id, username, email, role, password FROM users WHERE username=%s OR email=%s OR LOWER(username)=LOWER(%s) OR LOWER(email)=LOWER(%s) LIMIT 1",
                    (assigned_username, raw_email, assigned_username, raw_email)
                )
                auth_test_u = cur.fetchone()
                if not auth_test_u:
                    raise Exception(f"Auth lookup test failed for candidate user {assigned_username} / {raw_email}")

                logger.info("LOGIN LOOKUP user_found=true role=CANDIDATE")

                if is_new_account and temp_password:
                    pw_match_test = bcrypt_app.check_password_hash(auth_test_u["password"], temp_password)
                    if not pw_match_test:
                        raise Exception("Password verification failed for newly created candidate account!")
                    logger.info("PASSWORD CHECK password_match=true")

                # Sync into candidates table (Strict per-job isolation & resume tracking)
                if job_id:
                    cur.execute("SELECT id, email_status FROM candidates WHERE email = %s AND job_id = %s LIMIT 1", (raw_email, job_id))
                else:
                    cur.execute("SELECT id, email_status FROM candidates WHERE email = %s AND user_id = %s LIMIT 1", (raw_email, cand_user_id))
                
                auto_st = "Completed" if resume_status_val == "Uploaded" else "Resume Missing"
                err_msg = None if resume_status_val == "Uploaded" else f"Resume '{cand_resume_ref}' not found in Job {job_id} upload directory."

                effective_hr_id = hr_id or user_id
                if not effective_hr_id and job_id:
                    try:
                        cur.execute("SELECT user_id FROM automation_jobs WHERE job_code = %s LIMIT 1", (job_id,))
                        j_hr = cur.fetchone()
                        if j_hr and j_hr.get("user_id"):
                            effective_hr_id = j_hr["user_id"]
                    except Exception:
                        pass

                existing_cand = cur.fetchone()
                if existing_cand:
                    cand_id = existing_cand["id"]
                    previous_email_status = existing_cand.get("email_status")
                    cur.execute(
                        """
                        UPDATE candidates
                        SET name=%s, phone=%s, position=%s, registration_status='Registered', user_id=%s,
                            resume_filename=%s, resume=%s, resume_status=%s, automation_status=%s, error_message=%s, job_id=%s, upload_id=COALESCE(%s, upload_id),
                            hr_id=COALESCE(hr_id, %s)
                        WHERE id=%s
                        """,
                        (name, phone, position, cand_user_id, cand_resume_ref, resolved_resume_path, resume_status_val, auto_st, err_msg, job_id, upload_id, effective_hr_id, cand_id)
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO candidates (name, email, phone, position, registration_status, status, resume_filename, resume, resume_status, automation_status, error_message, created_at, user_id, job_id, upload_id, hr_id)
                        VALUES (%s, %s, %s, %s, 'Registered', 'New', %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s)
                        """,
                        (name, raw_email, phone, position, cand_resume_ref, resolved_resume_path, resume_status_val, auto_st, err_msg, cand_user_id, job_id, upload_id, effective_hr_id)
                    )
                    cand_id = cur.lastrowid

                conn.commit()

                # Verify DB persistence immediately after commit
                cur.execute("SELECT id, email, user_id, job_id, upload_id FROM candidates WHERE id=%s LIMIT 1", (cand_id,))
                v_cand = cur.fetchone()
                if not v_cand:
                    raise Exception(f"Database candidate record verification failed for candidate ID #{cand_id} after commit!")

                logger.info("CANDIDATE CREATED candidate_id=%s user_id=%s", cand_id, cand_user_id)
                logger.info("AUTOMATION REGISTRATION COMPLETE email=%s", raw_email)

                cur.close()
                conn.close()

        except Exception as reg_err:
            registration_failures += 1
            reg_status = "Registration Failed"
            reg_error = str(reg_err)
            logger.error("Auto-registration failed for %s: %s", raw_email, reg_err)

            # If user creation or candidate linking failed, ensure candidates table reflects registration failure
            try:
                conn_fail = get_connection()
                if conn_fail:
                    cur_fail = conn_fail.cursor()
                    cur_fail.execute("UPDATE candidates SET registration_status = 'Registration Failed', error_message = %s WHERE email = %s", (str(reg_err), raw_email))
                    conn_fail.commit()
                    cur_fail.close()
                    conn_fail.close()
            except Exception as update_fail_err:
                logger.warning("Could not update candidates registration_status to Registration Failed: %s", update_fail_err)

        # 3. Construct and Dispatch Registration SMTP Email (Duplicate & Existing Account Safe Check)
        email_status = "Failed"
        email_error = None

        if previous_email_status in ["Sent", "Email Sent", "Already Sent", "Already Exists"]:
            email_status = "Already Sent"
            recipient_results.append({
                "name": name,
                "email": raw_email,
                "username": assigned_username,
                "source_file": src_file,
                "registration_status": reg_status,
                "email_status": email_status,
                "registration_error": reg_error,
                "email_error": None
            })
            continue

        if not is_new_account:
            email_status = "Already Exists"
            if cand_id:
                try:
                    conn_e = get_connection()
                    if conn_e:
                        cur_e = conn_e.cursor()
                        cur_e.execute("UPDATE candidates SET email_status = 'Already Exists' WHERE id = %s", (cand_id,))
                        conn_e.commit()
                        cur_e.close()
                        conn_e.close()
                except Exception as e_up_ex:
                    logger.warning("Notice updating email_status for existing user: %s", e_up_ex)
            recipient_results.append({
                "name": name,
                "email": raw_email,
                "username": assigned_username,
                "source_file": src_file,
                "registration_status": reg_status,
                "email_status": email_status,
                "registration_error": reg_error,
                "email_error": None
            })
            continue

        mail_subject = "SmartRecruitment Account Created"

        mail_body_text = f"""SmartRecruitment Account

Your SmartRecruitment account has been created successfully.

Username: {assigned_username}
Email: {raw_email}
Temporary Password: {temp_password}
Login URL: {login_url}

Please log in using the above credentials and change your password after your first login.

Best regards,
Smart Recruitment Team
"""

        mail_body_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{mail_subject}</title></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #4f46e5; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
        <h2 style="color: #ffffff; margin: 0;">SmartRecruitment Account</h2>
    </div>
    <div style="background-color: #ffffff; padding: 30px; border: 1px solid #e5e7eb; border-radius: 0 0 8px 8px;">
        <p style="margin-top: 0;">Your SmartRecruitment account has been created successfully.</p>
        <p style="margin: 5px 0;"><strong>Username:</strong> {assigned_username}</p>
        <p style="margin: 5px 0;"><strong>Email:</strong> {raw_email}</p>
        <p style="margin: 5px 0;"><strong>Temporary Password:</strong> {temp_password}</p>
        <p style="margin: 5px 0;"><strong>Login URL:</strong> <a href="{login_url}" style="color: #4f46e5;">{login_url}</a></p>
        <br>
        <p>Please log in using the above credentials and change your password after your first login.</p>
        <br>
        <p style="margin-bottom: 0;">Best regards,</p>
        <p style="margin-top: 5px;"><strong>Smart Recruitment Team</strong></p>
    </div>
</body>
</html>
"""

        # Dispatch SMTP Email
        send_res = send_smtp_email(
            to_email=raw_email,
            subject=mail_subject,
            body_text=mail_body_text,
            body_html=mail_body_html
        )

        if send_res.get("success"):
            emails_sent += 1
            email_status = "Email Sent"
        else:
            email_failures += 1
            email_status = "Email Failed"
            email_error = send_res.get("message", "SMTP delivery failed")

        # Update email_status in candidates table
        if cand_id:
            try:
                conn = get_connection()
                if conn:
                    cur = conn.cursor()
                    st_val = "Sent" if email_status == "Email Sent" else "Failed"
                    cur.execute("UPDATE candidates SET email_status=%s WHERE id=%s", (st_val, cand_id))
                    conn.commit()
                    cur.close()
                    conn.close()
            except Exception as e_up:
                logger.warning("Notice updating email_status: %s", e_up)

        recipient_results.append({
            "name": name,
            "email": raw_email,
            "username": assigned_username,
            "source_file": src_file,
            "registration_status": reg_status,
            "email_status": email_status,
            "registration_error": reg_error,
            "email_error": email_error
        })

    overall_success = emails_sent > 0 or (email_failures == 0 and len(global_recipients) > 0)
    final_job_status = "Completed" if overall_success else "Failed"

    if job_id:
        try:
            conn_j = get_connection()
            if conn_j:
                cur_j = conn_j.cursor()
                job_id_str = str(job_id)
                job_id_int = int(job_id) if job_id_str.isdigit() else -1
                cur_j.execute(
                    """
                    UPDATE automation_jobs
                    SET status=%s, total_files=%s, total_candidates=%s, processed_candidates=%s, failed_candidates=%s, updated_at=NOW()
                    WHERE job_code=%s OR id=%s
                    """,
                    (final_job_status, len(file_sources), len(global_recipients), emails_sent, email_failures + registration_failures, job_id_str, job_id_int)
                )
                conn_j.commit()
                cur_j.close()
                conn_j.close()
        except Exception as j_up_err:
            logger.warning("Notice updating automation_jobs status: %s", j_up_err)

    return {
        "status": "success" if overall_success else "failed",
        "success": overall_success,
        "job_id": job_id,
        "total_files": len(file_sources),
        "processed_files_count": total_processed_files,
        "failed_files_count": total_failed_files,
        "total_rows": total_rows,
        "valid_emails": valid_emails_count,
        "duplicate_emails": duplicate_emails_count,
        "successfully_registered": successfully_registered,
        "already_registered": already_registered_count,
        "emails_sent": emails_sent,
        "registration_failures": registration_failures,
        "email_failures": email_failures,
        "files": file_results,
        "results": recipient_results
    }



