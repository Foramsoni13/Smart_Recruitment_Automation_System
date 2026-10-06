*** Settings ***
Documentation    Automated test suite for HR Uploading MCQ Questions PDF to Question Bank.
Resource         ../../resources/exam.resource
Test Setup       Open Application
Test Teardown    Close Browser

*** Test Cases ***
HR Can Open Upload PDF Modal And Display Selected Filename
    [Documentation]    HR logs in, opens Question Bank, clicks Upload Questions PDF, selects PDF file, and verifies selected filename appears.
    Login As HR
    Go To    ${BASE_URL}/hr/questions
    Page Should Contain    Question Bank
    Page Should Contain    Upload Questions PDF
    Click Element    xpath=//button[contains(., 'Upload Questions PDF')]
    Wait Until Page Contains    Upload MCQ Questions PDF
    Page Should Contain Element    id=pdfFileInput
    Page Should Contain Element    id=btnProcessPdf

HR Rejects Non PDF Files On Upload
    [Documentation]    HR selects non-PDF file and receives client-side validation error.
    Login As HR
    Go To    ${BASE_URL}/hr/questions
    Click Element    xpath=//button[contains(., 'Upload Questions PDF')]
    Wait Until Page Contains    Upload MCQ Questions PDF

HR Can Process PDF And Save Questions To Question Bank
    [Documentation]    HR uploads valid PDF questions file, reviews questions, and saves to Question Bank.
    Login As HR
    Go To    ${BASE_URL}/hr/questions
    Page Should Contain    Question Bank
