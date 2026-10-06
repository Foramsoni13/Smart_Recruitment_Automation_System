*** Settings ***
Documentation    Smart Recruitment Automation System - Candidate Processing Pipeline
...              Autonomous recruitment pipeline: parses candidate records from Excel/CSV,
...              registers candidates, matches and uploads resumes, and confirms records in MySQL.

Library          OperatingSystem
Library          Process
Library          BuiltIn

*** Variables ***
${DEFAULT_BASE_URL}          http://127.0.0.1:5001
${DEFAULT_BROWSER_MODE}      headless
${INPUT_FILE}                ${EMPTY}
${JOB_ID}                    ${EMPTY}
${UPLOAD_ID}                 ${EMPTY}
${RESUME_FOLDER}             ${EMPTY}

*** Test Cases ***
Execute Robotic Candidate Recruitment Pipeline
    [Documentation]    Executes autonomous recruitment batch processing for candidate Excel/CSV files and resumes.
    Log To Console    AUTOMATION ACTIVE: Initializing Robot Framework & Selenium...
    Log To Console    STAGE: Initializing
    Log To Console    LAST_STEP: Initializing Robot Framework & Selenium

    ${BASE_URL}=    Get Environment Variable    SMART_RECRUITMENT_BASE_URL    ${DEFAULT_BASE_URL}
    ${ENV_EXCEL}=    Get Environment Variable    SMART_RECRUITMENT_EXCEL_FILE    ${EMPTY}
    ${EXCEL_FILE}=    Set Variable If    '${INPUT_FILE}' != '${EMPTY}'    ${INPUT_FILE}    ${ENV_EXCEL}
    ${RES_DIR}=    Get Environment Variable    SMART_RECRUITMENT_RESUME_FOLDER    ${RESUME_FOLDER}
    ${JOB}=    Get Environment Variable    SMART_RECRUITMENT_JOB_ID    ${JOB_ID}
    ${UPLOAD}=    Get Environment Variable    SMART_RECRUITMENT_UPLOAD_ID    ${UPLOAD_ID}
    ${BROWSER_MODE}=    Get Environment Variable    SMART_RECRUITMENT_BROWSER_MODE    ${DEFAULT_BROWSER_MODE}

    Log To Console    STAGE: Read Excel
    Log To Console    JOB ID: ${JOB}
    Log To Console    UPLOAD ID: ${UPLOAD}
    Log To Console    Input file: ${EXCEL_FILE}
    Log To Console    LAST_STEP: Reading candidate Excel records

    ${WORKER_CMD}=    Set Variable    from services.automation_worker import process_candidate_batch; process_candidate_batch()
    ${result}=    Run Process    python3    -c    ${WORKER_CMD}
    ...           env:SMART_RECRUITMENT_BASE_URL=${BASE_URL}
    ...           env:SMART_RECRUITMENT_EXCEL_FILE=${EXCEL_FILE}
    ...           env:SMART_RECRUITMENT_RESUME_FOLDER=${RES_DIR}
    ...           env:SMART_RECRUITMENT_JOB_ID=${JOB}
    ...           env:SMART_RECRUITMENT_UPLOAD_ID=${UPLOAD}
    ...           env:SMART_RECRUITMENT_BROWSER_MODE=${BROWSER_MODE}
    ...           cwd=${CURDIR}/..

    Log To Console    ${result.stdout}
    Should Be Equal As Integers    ${result.rc}    0    msg=Robotic automation batch worker failed with error: ${result.stderr}

    Log To Console    STAGE: Complete
    Log To Console    LAST_STEP: Recruitment automation completed successfully

