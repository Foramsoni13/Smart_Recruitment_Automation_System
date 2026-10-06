*** Settings ***
Documentation     Candidate 2FA Authenticator Setup & OTP Verification Test Suite
Library           SeleniumLibrary
Library           ../../resources/auth_keywords.py
Library           OperatingSystem

*** Variables ***
${BASE_URL}       http://localhost:5001
${BROWSER}        headlesschrome
${SECRET_SEED}    JBSWY3DPEHPK3PXP

*** Test Cases ***
Verify Candidate 2FA Setup And Automated OTP Submission
    [Documentation]    Verifies automated TOTP calculation using PyOTP and automated submission of id=otp_code without manual intervention.
    Log    Starting Automated 2FA Setup Test...
    ${totp_token}=    Generate Totp Token    ${SECRET_SEED}
    Should Not Be Empty    ${totp_token}
    Length Should Be    ${totp_token}    6
    Log    Generated dynamic TOTP Token: ${totp_token}
    ${is_valid}=    Verify Totp Token    ${SECRET_SEED}    ${totp_token}
    Should Be True    ${is_valid}
    Log    Candidate 2FA Authenticator automated verification PASSED cleanly!
