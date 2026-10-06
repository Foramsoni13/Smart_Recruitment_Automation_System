*** Settings ***
Documentation     Automated Resume Parsing & Deep AI Text Match Assertion Test Suite
Library           ../../resources/resume_keywords.py
Library           OperatingSystem

*** Variables ***
${SAMPLE_RESUME}         Candidate profile with Python, Flask, Robot Framework, Selenium, Machine Learning, SQL, Automated Testing, and System Architecture expertise.
${JOB_REQUIREMENT}       Looking for Python, Flask, Robot Framework, Selenium, Machine Learning, SQL, and Automated Testing skills.
${TARGET_THRESHOLD}      75.0

*** Test Cases ***
Verify Resume Text Extraction And AI Similarity Score Threshold Assertion
    [Documentation]    Verifies automated PDF text extraction and enforces strict NLP match percentage assertion >= 75%.
    Log    Starting Automated Resume Parsing NLP Match Assertion Test...
    ${match_score}=    Extract And Calculate Match Score    ${SAMPLE_RESUME}    ${JOB_REQUIREMENT}
    Log    Calculated Resume NLP Match Score: ${match_score}%
    Should Be True    ${match_score} >= ${TARGET_THRESHOLD}
    Assert Similarity Threshold    ${match_score}    ${TARGET_THRESHOLD}
    Log    Resume NLP Similarity Threshold Assertion PASSED cleanly!
