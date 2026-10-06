*** Settings ***
Documentation     Automated Email Notification Receipt Delivery Assertion Test Suite
Library           ../../resources/notification_keywords.py
Library           OperatingSystem

*** Variables ***
${RECIPIENT_EMAIL}    candidate@example.com
${EMAIL_SUBJECT}      Candidate Exam Invitation - Smart Recruitment System
@{BODY_KEYWORDS}     Exam Link    Aptitude Test    Duration 45 Mins

*** Test Cases ***
Verify Email Handshake And Candidate Delivery Receipt
    [Documentation]    Verifies automated SMTP email dispatch, subject validation, and IMAP receipt verification.
    Log    Starting Automated Email Delivery Receipt Test...
    ${receipt}=    Verify Email Dispatch    ${RECIPIENT_EMAIL}    ${EMAIL_SUBJECT}    ${BODY_KEYWORDS}
    Log    Email Dispatch Receipt: ${receipt}
    Assert Email Delivery Status    ${receipt}
    Should Be Equal As Strings    ${receipt['status']}    DELIVERED
    Log    Email Notification Delivery Verification PASSED cleanly!
