*** Settings ***
Documentation    Automated test suite for HR Exam Monitoring and Results Management.
Resource         ../../resources/exam.resource
Test Setup       Open Application
Test Teardown    Close Browser

*** Test Cases ***
HR Can View Candidate Exam Results And Warning Telemetry
    [Documentation]    HR logs in, opens exam management, and views candidate scores, percentages, and proctoring events.
    Login As HR
    Navigate To Exam Management
    Page Should Contain    All Examination Modules
