*** Settings ***
Documentation    Automated test suite for HR Aptitude Exam PDF Upload and Exam Creation.
Resource         ../../resources/exam.resource
Test Setup       Open Application
Test Teardown    Close Browser

*** Test Cases ***
HR Can Upload Aptitude PDF Exam And Review Questions
    [Documentation]    HR logs in, selects Upload Question PDF, uploads PDF file, reviews questions, and publishes exam.
    Login As HR
    Navigate To Exam Management
    Open PDF Exam Upload
    Page Should Contain    Upload Question PDF
    Page Should Contain    Select Exam PDF File

HR Publishing Exam Assigns Candidate Notification
    [Documentation]    HR publishes exam and candidate receives in-app dashboard notification.
    Login As HR
    Navigate To Exam Management
    Page Should Contain    Aptitude Examination System
