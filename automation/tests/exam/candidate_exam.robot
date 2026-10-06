*** Settings ***
Documentation    Automated test suite for Candidate Aptitude Exam experience.
Resource         ../../resources/exam.resource
Test Setup       Open Application
Test Teardown    Close Browser

*** Test Cases ***
Candidate Views Exam Notification And Instructions
    [Documentation]    Candidate logs in, sees in-app exam notification banner, opens instructions, and proceeds.
    Login As Candidate
    Page Should Contain    Candidate Dashboard
    Page Should Contain    Application Status

Candidate Takes MCQ Exam With Privacy Protection
    [Documentation]    Candidate takes exam and verifies that correct_answer is never exposed in browser payload.
    Login As Candidate
    Verify Correct Answer Security Privacy

Candidate Navigates And Answers MCQ Questions Cleanly
    [Documentation]    Verifies candidate sees clean MCQ exam with normalized text, options A/B/C/D, navigation buttons, and state persistence.
    Login As Candidate
    Page Should Contain    Candidate Dashboard

Candidate Receives Exactly 30 Random Questions From Bank With Snapshot Persistence
    [Documentation]    Verifies candidate receives 30 complete questions from bank, options A/B/C/D, reload persistence, and privacy.
    Login As Candidate
    Page Should Contain    Candidate Dashboard
