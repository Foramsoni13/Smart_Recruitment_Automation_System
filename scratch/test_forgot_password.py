import os
import sys
import pyotp
import flask_bcrypt
from database.db import get_connection

def test_forgot_password_flow():
    conn = get_connection()
    if not conn:
        print("ERROR: Database connection failed!")
        sys.exit(1)

    cur = conn.cursor(dictionary=True)

    # 1. Reset user 'foramsoni2004' in DB
    bcrypt_app = flask_bcrypt.Bcrypt()
    initial_pw = "foramsoni2004@"
    hashed_pw = bcrypt_app.generate_password_hash(initial_pw).decode("utf-8")
    cand_secret = pyotp.random_base32()

    cur.execute("SELECT id FROM users WHERE username = %s LIMIT 1", ("foramsoni2004",))
    u_row = cur.fetchone()
    if u_row:
        user_id = u_row["id"]
        cur.execute(
            """
            UPDATE users
            SET password = %s,
                role = 'candidate',
                must_change_password = 1,
                google_authenticator_configured = 0,
                totp_secret = %s
            WHERE id = %s
            """,
            (hashed_pw, cand_secret, user_id)
        )
        conn.commit()

    print(f"Step 1: User foramsoni2004 reset in DB with totp_secret={cand_secret}")

    from app import app as flask_app
    client = flask_app.test_client()

    # 2. GET /forgot-password
    res_fp_get = client.get("/forgot-password")
    assert res_fp_get.status_code == 200
    print("✅ Step 2 PASS: GET /forgot-password returns 200 OK")

    # 3. POST /verify-authenticator with case-insensitive username 'FORAMSONI2004' and valid OTP
    valid_otp = pyotp.TOTP(cand_secret).now()
    res_verify = client.post("/verify-authenticator", data={
        "username": "FORAMSONI2004",
        "otp_code": valid_otp
    }, follow_redirects=False)

    print(f"Step 3: Verify OTP status={res_verify.status_code}, location={res_verify.headers.get('Location')}")
    assert res_verify.status_code == 302
    assert "/reset-password" in res_verify.headers.get("Location")
    print("✅ Step 3 PASS: Case-insensitive username + valid OTP verified, redirected to /reset-password")

    # 4. GET /reset-password
    res_reset_get = client.get("/reset-password")
    assert res_reset_get.status_code == 200
    print("✅ Step 4 PASS: GET /reset-password returns 200 OK")

    # 5. POST /update-password
    new_pass = "ForamRecoveredPass123!"
    res_update = client.post("/update-password", data={
        "new_password": new_pass,
        "confirm_password": new_pass
    }, follow_redirects=False)

    print(f"Step 5: Update password status={res_update.status_code}, location={res_update.headers.get('Location')}")
    assert res_update.status_code == 302
    assert "/login" in res_update.headers.get("Location")
    print("✅ Step 5 PASS: Password updated successfully, redirected to /login")

    # 6. Verify DB state
    cur.execute("SELECT must_change_password, google_authenticator_configured FROM users WHERE id = %s", (user_id,))
    db_state = cur.fetchone()
    assert db_state["must_change_password"] == 0
    assert db_state["google_authenticator_configured"] == 1
    print("✅ Step 6 PASS: DB state updated: must_change_password=0, google_authenticator_configured=1")

    # 7. Test login with recovered password
    res_login = client.post("/login-user", data={
        "username": "foramsoni2004",
        "password": new_pass
    }, follow_redirects=False)
    assert res_login.status_code == 302
    assert res_login.headers.get("Location") in ["/candidate", "/candidate/dashboard"]
    print("✅ Step 7 PASS: Logged in with recovered password directly into Candidate Dashboard")

    cur.close()
    conn.close()
    print("\n🎉 FORGOT PASSWORD & RESET PASSWORD TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_forgot_password_flow()
