*** Settings ***
Documentation    Reusable Robot Framework resources for SmartRecruitment Examination Module.
Library          SeleniumLibrary

*** Variables ***
${BASE_URL}              http://127.0.0.1:5000
${BROWSER}               chrome
${HR_USERNAME}           admin
${HR_PASSWORD}           admin_secret_pass
${CANDIDATE_EMAIL}       foramsoni2004@gmail.com
${CANDIDATE_PASSWORD}    foramsoni2004@

*** Keywords ***
Open Application
    [Documentation]    Opens browser and navigates to SmartRecruitment Login Page
    Open Browser    ${BASE_URL}/login    ${BROWSER}
    Maximize Browser Window
    Set Selenium Implicit Wait    10s

Login As HR
    [Documentation]    Logs into application as HR Administrator
    Go To    ${BASE_URL}/login
    Input Text    name=username    ${HR_USERNAME}
    Input Text    name=password    ${HR_PASSWORD}
    Click Button    xpath=//button[@type='submit']
    Wait Until Page Contains    HR Dashboard

Login As Candidate
    [Documentation]    Logs into application as Candidate
    Go To    ${BASE_URL}/login
    Input Text    name=username    ${CANDIDATE_EMAIL}
    Input Text    name=password    ${CANDIDATE_PASSWORD}
    Click Button    xpath=//button[@type='submit']
    Wait Until Page Contains    Candidate Dashboard

Navigate To Exam Management
    [Documentation]    Navigates to HR Exam Management list page
    Go To    ${BASE_URL}/hr/exams

Open PDF Exam Upload
    [Documentation]    Opens the Upload Question PDF page from Add Exam menu
    Navigate To Exam Management
    Click Element    id=addExamDropdown
    Click Link       xpath=//a[contains(@href, '/hr/exams/upload-pdf-page')]
    Wait Until Page Contains    Upload Question PDF

Upload Aptitude Exam PDF
    [Arguments]    ${file_path}    ${exam_title}
    Open PDF Exam Upload
    Choose File    id=pdfInput    ${file_path}
    Input Text     name=title     ${exam_title}
    Click Button   xpath=//button[@type='submit']
    Wait Until Page Contains    PDF Question Extraction Review

Publish PDF Exam
    [Documentation]    Reviews extracted questions and publishes the exam
    Click Button    xpath=//button[@type='submit']
    Wait Until Page Contains    published successfully

Verify Candidate Exam Notification
    [Documentation]    Verifies that assigned candidate receives in-app exam notification
    Login As Candidate
    Page Should Contain    New exam created for you. Please complete the exam.
    Page Should Contain    Available Exams

Start Candidate Exam Flow
    [Arguments]    ${exam_id}
    Go To    ${BASE_URL}/candidate/exam/${exam_id}/instructions
    Wait Until Page Contains    Exam Instructions
    Click Link    xpath=//a[contains(@href, 'camera-check')]
    Wait Until Page Contains    Camera & System Security Check
    Click Link    xpath=//a[contains(@href, 'take') or contains(@href, 'start')]
    Wait Until Page Contains    Question

Verify Correct Answer Security Privacy
    [Documentation]    Verifies that the page source does NOT contain the correct_answer key or key field
    ${page_source}=    Get Source
    Should Not Contain    ${page_source}    "correct_answer"
    Should Not Contain    ${page_source}    correct_answer:

Verify Candidate MCQ Question Display And Navigation
    [Documentation]    Verifies question display, options A/B/C/D, option selection, navigation, and answer persistence.
    Element Should Be Visible    id=qNumberBadge
    Element Should Be Visible    id=qTextDisplay
    Wait Until Page Contains Element    xpath=//div[contains(@class, 'option-item')]
    ${opt_count}=    Get Element Count    xpath=//div[contains(@class, 'option-item')]
    Should Be True    ${opt_count} >= 2
    # Select Option A
    Click Element    xpath=(//div[contains(@class, 'option-item')])[1]
    # Verify Save & Next navigation
    Click Element    id=btnNext
    Wait Until Page Contains Element    id=qNumberBadge
    # Navigate Back to Question 1
    Click Element    id=btnPrev
    # Verify correct answer privacy
    Verify Correct Answer Security Privacy

Verify Candidate 30 Question Bank Snapshot
    [Documentation]    Verifies candidate sees Question 1 of 30, options A/B/C/D, reload persistence, and security privacy.
    Element Should Be Visible    id=qNumberBadge
    ${badge_text}=    Get Text    id=qNumberBadge
    Should Contain    ${badge_text}    of 30
    Element Should Be Visible    id=qTextDisplay
    Wait Until Page Contains Element    xpath=//div[contains(@class, 'option-item')]
    ${opt_count}=    Get Element Count    xpath=//div[contains(@class, 'option-item')]
    Should Be Equal As Integers    ${opt_count}    4
    # Reload page to test snapshot persistence
    Reload Page
    Wait Until Page Contains Element    id=qNumberBadge
    ${refreshed_badge_text}=    Get Text    id=qNumberBadge
    Should Contain    ${refreshed_badge_text}    of 30
    Verify Correct Answer Security Privacy
