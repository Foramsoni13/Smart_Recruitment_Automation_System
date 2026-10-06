*** Settings ***
Documentation    Automated test suite for Exam Security, Fullscreen/Tab-Switch telemetry, and Backend Scoring.
Resource         ../../resources/exam.resource
Test Setup       Open Application
Test Teardown    Close Browser

*** Test Cases ***
Verify Correct Answers Are Never Returned In Candidate Payload
    [Documentation]    Candidate API response must never contain correct_answer field or answer keys.
    Login As Candidate
    Verify Correct Answer Security Privacy

Verify Unauthorized Access Restrictions
    [Documentation]    Candidate cannot access other candidates' exam results or unauthorized HR endpoints.
    Go To    ${BASE_URL}/hr/exams
    Wait Until Page Contains    Login
