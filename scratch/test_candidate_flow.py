import os
import sys
import pyotp
import flask_bcrypt
from database.db import get_connection

def test_flow():
    conn = get_connection()
    if not conn:
        print("ERROR: Database connection failed!")
        sys.exit(1)

    cur = conn.cursor(dictionary=True)

    # 1. Reset user 'foramsoni2004' to fresh automation-created candidate state
    bcrypt_app = flask_bcrypt.Bcrypt()
    temp_pw = "foramsoni2004@"
    hashed_pw = bcrypt_app.generate_password_hash(temp_pw).decode("utf-8")
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
    else:
        cur.execute(
            """
            INSERT INTO users (fullname, username, email, phone, password, role, must_change_password, google_authenticator_configured, totp_secret)
            VALUES (%s, %s, %s, %s, %s, 'candidate', 1, 0, %s)
            """,
            ("Foram Soni", "foramsoni2004", "foramsoni2004@gmail.com", "9876543210", hashed_pw, cand_secret)
        )
        user_id = cur.lastrowid

    conn.commit()
    print(f"Step 1: Set candidate account foramsoni2004 (id={user_id}) to initial automation state (role=candidate, must_change_password=1, google_authenticator_configured=0).")

    # Import Flask app and test using Flask test_client
    from app import app as flask_app
    client = flask_app.test_client()

    # 2. Candidate Login with temporary credentials
    res = client.post("/login-user", data={"username": "foramsoni2004", "password": temp_pw}, follow_redirects=False)
    print(f"Step 2: Candidate Login status={res.status_code}, location={res.headers.get('Location')}")
    assert res.status_code == 302
    assert "/candidate/setup-2fa" in res.headers.get("Location")
    print("✅ Step 2 PASS: Candidate logged in with temp credentials and redirected to /candidate/setup-2fa")

    # 3. Test accessing /change-password directly before OTP verification
    res_cp = client.get("/change-password", follow_redirects=False)
    print(f"Step 3: Direct access to /change-password status={res_cp.status_code}, location={res_cp.headers.get('Location')}")
    assert res_cp.status_code == 302
    assert "/candidate/setup-2fa" in res_cp.headers.get("Location")
    print("✅ Step 3 PASS: Access to /change-password blocked without OTP verification")

    # 4. Test submitting invalid OTP
    res_bad_otp = client.post("/candidate/verify-otp", data={"otp_code": "000000"}, follow_redirects=False)
    print(f"Step 4: Invalid OTP status={res_bad_otp.status_code}, location={res_bad_otp.headers.get('Location')}")
    assert res_bad_otp.status_code == 302
    assert "/candidate/setup-2fa" in res_bad_otp.headers.get("Location")
    print("✅ Step 4 PASS: Invalid OTP rejected")

    # 5. Test submitting valid OTP
    valid_otp = pyotp.TOTP(cand_secret).now()
    res_good_otp = client.post("/candidate/verify-otp", data={"otp_code": valid_otp}, follow_redirects=False)
    print(f"Step 5: Valid OTP status={res_good_otp.status_code}, location={res_good_otp.headers.get('Location')}")
    assert res_good_otp.status_code == 302
    assert "/change-password" in res_good_otp.headers.get("Location")
    print("✅ Step 5 PASS: Valid OTP accepted and redirected to /change-password")

    # 6. Test change password GET (should render change_password.html)
    res_cp_page = client.get("/change-password")
    assert res_cp_page.status_code == 200
    print("✅ Step 6 PASS: Accessing /change-password after OTP succeeds")

    # 7. Change password with valid credentials
    new_pw = "ForamNewPass123!"
    res_cp_post = client.post("/change-password", data={
        "current_password": temp_pw,
        "new_password": new_pw,
        "confirm_password": new_pw
    }, follow_redirects=False)
    print(f"Step 7: Change Password status={res_cp_post.status_code}, location={res_cp_post.headers.get('Location')}")
    assert res_cp_post.status_code == 302
    assert res_cp_post.headers.get("Location") in ["/candidate", "/candidate/dashboard"]
    print("✅ Step 7 PASS: Password changed successfully and redirected to candidate dashboard")

    # Verify DB state after password change
    cur.execute("SELECT must_change_password, google_authenticator_configured FROM users WHERE id = %s", (user_id,))
    after_db = cur.fetchone()
    print(f"Step 8: DB state after password change: {after_db}")
    assert after_db["must_change_password"] == 0
    assert after_db["google_authenticator_configured"] == 1
    print("✅ Step 8 PASS: must_change_password=0 and google_authenticator_configured=1 in DB")

    # 9. Test candidate logout
    client.get("/logout")

    # 10. Test login with old temporary password (should fail)
    res_old_pw = client.post("/login-user", data={"username": "foramsoni2004", "password": temp_pw}, follow_redirects=False)
    assert res_old_pw.status_code == 302
    assert "/login" in res_old_pw.headers.get("Location")
    print("✅ Step 10 PASS: Old temporary password no longer works")

    # 11. Test login with new password (should succeed to dashboard)
    res_new_pw = client.post("/login-user", data={"username": "foramsoni2004", "password": new_pw}, follow_redirects=False)
    assert res_new_pw.status_code == 302
    assert res_new_pw.headers.get("Location") in ["/candidate", "/candidate/dashboard"]
    print("✅ Step 11 PASS: Login with new password succeeds and goes directly to candidate dashboard")

    # 12. Test HR side intact
    client.get("/logout")
    res_hr = client.post("/login-user", data={"username": "admin@company.com", "password": "admin_secret_pass"}, follow_redirects=False)
    assert res_hr.status_code == 302
    print(f"Step 12: HR/Admin Login status={res_hr.status_code}, location={res_hr.headers.get('Location')}")
    print("✅ Step 12 PASS: HR/Admin Login still functions properly")

    cur.close()
    conn.close()
    print("\n🎉 ALL CANDIDATE FIRST-LOGIN 2FA & PASSWORD CHANGE TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_flow()
