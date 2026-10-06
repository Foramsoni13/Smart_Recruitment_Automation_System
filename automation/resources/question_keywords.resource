*** Settings ***
Documentation    Modular Robot Framework Keywords for MCQ Question Bank & Unique PDF Generation Automation.
Library          SeleniumLibrary
Library          String
Library          Collections

*** Variables ***
${BASE_URL}             http://127.0.0.1:5000
${BROWSER}              chrome
${HR_USERNAME}          admin
${HR_PASSWORD}          admin_secret_pass
${QUESTION_BANK_URL}    ${BASE_URL}/hr/questions

*** Keywords ***
Open Question Bank
    [Documentation]    Opens browser, logs into SmartRecruitment as HR, and navigates to the MCQ Question Bank page.
    Open Browser    ${BASE_URL}/login    ${BROWSER}
    Maximize Browser Window
    Set Selenium Implicit Wait    10s
    Input Text    name=username    ${HR_USERNAME}
    Input Text    name=password    ${HR_PASSWORD}
    Click Button    xpath=//button[@type='submit']
    Wait Until Page Contains    HR Dashboard
    Go To    ${QUESTION_BANK_URL}
    Wait Until Element Is Visible    id=questionsContainer    15s
    Page Should Contain    MCQ Questions for App

Normalize Question
    [Arguments]    ${question_text}
    [Documentation]    Normalizes question text by trimming leading/trailing whitespace, replacing line breaks with spaces, collapsing multiple spaces to a single space, and lowercasing. Does not alter original question text displayed in UI/PDF.
    ${lower}=    Convert To Lower Case    ${question_text}
    ${no_newlines}=    Replace String    ${lower}    \n    ${SPACE}
    ${no_carriage}=    Replace String    ${no_newlines}    \r    ${SPACE}
    ${trimmed}=    Strip String    ${no_carriage}
    ${normalized}=    Replace String Using Regexp    ${trimmed}    \\s+    ${SPACE}
    [Return]    ${normalized}

Get Existing Questions
    [Documentation]    Retrieves all question texts currently present in the Question Bank DOM and returns a normalized dictionary.
    Wait Until Element Is Visible    id=questionsContainer    10s
    ${elements}=    Get WebElements    css=.question-row-element
    ${existing_dict}=    Create Dictionary

    FOR    ${element}    IN    @{elements}
        ${raw_text}=    Get Element Attribute    ${element}    data-question-text
        IF    "${raw_text}" == "None" or "${raw_text}" == ""
            ${raw_text}=    Get Text    ${element}
        END
        ${norm}=    Normalize Question    ${raw_text}
        Set To Dictionary    ${existing_dict}    ${norm}    True
    END

    [Return]    ${existing_dict}

Validate Question Is Unique
    [Arguments]    ${question_text}    ${existing_questions_dict}
    [Documentation]    Checks if a normalized question text exists in the existing questions dictionary. Returns True if unique, False if duplicate.
    ${norm}=    Normalize Question    ${question_text}
    ${is_duplicate}=    Run Keyword And Return Status    Dictionary Should Contain Key    ${existing_questions_dict}    ${norm}
    ${is_unique}=    Evaluate    not ${is_duplicate}
    [Return]    ${is_unique}

Remove Duplicate Questions
    [Arguments]    ${new_questions_list}    ${existing_questions_dict}=${EMPTY}
    [Documentation]    Filters a list of new candidate questions, removing duplicates within the list AND against existing questions, keeping only the first unique occurrence of each question based ONLY on normalized question text.
    ${unique_list}=    Create List
    ${seen_local}=    Create Dictionary

    IF    "${existing_questions_dict}" != "${EMPTY}"
        ${seen_local}=    Copy Dictionary    ${existing_questions_dict}
    END

    FOR    ${q_text}    IN    @{new_questions_list}
        ${norm}=    Normalize Question    ${q_text}
        ${already_seen}=    Run Keyword And Return Status    Dictionary Should Contain Key    ${seen_local}    ${norm}
        IF    not ${already_seen}
            Set To Dictionary    ${seen_local}    ${norm}    True
            Append To List    ${unique_list}    ${q_text}
        ELSE
            Log    [DUPLICATE DETECTED & REMOVED] Skipped duplicate question: "${q_text}"
        END
    END

    [Return]    ${unique_list}

Add Question Item To Bank
    [Arguments]    ${question_text}    ${opt_a}=Option A    ${opt_b}=Option B    ${opt_c}=Option C    ${opt_d}=Option D    ${ans}=A
    [Documentation]    Fills and submits the Add MCQ Question form in the UI.
    Click Element    id=btnOpenAddQuestionModal
    Wait Until Element Is Visible    name=question_text    10s
    Input Text    name=question_text    ${question_text}
    Input Text    name=option_a    ${opt_a}
    Input Text    name=option_b    ${opt_b}
    Input Text    name=option_c    ${opt_c}
    Input Text    name=option_d    ${opt_d}
    Select From List By Value    name=correct_answer    ${ans}
    Click Button    xpath=//button[@type='submit' and contains(., 'Save Question')]
    Wait Until Page Contains    MCQ Questions for App

Add Unique Questions
    [Arguments]    ${candidate_questions_list}
    [Documentation]    Collects existing questions, filters candidate questions to remove duplicates, and adds ONLY unique questions to the Question Bank.
    ${existing_dict}=    Get Existing Questions
    ${filtered_unique_list}=    Remove Duplicate Questions    ${candidate_questions_list}    ${existing_dict}

    FOR    ${q_text}    IN    @{filtered_unique_list}
        Add Question Item To Bank    ${q_text}
    END

    [Return]    ${filtered_unique_list}

Generate PDF With Unique Questions Only
    [Arguments]    ${candidate_questions_list}
    [Documentation]    Validates candidate questions BEFORE clicking the Generate/Process PDF button, filters duplicates against existing questions and within input list, and proceeds only with unique questions.
    ${existing_dict}=    Get Existing Questions
    ${unique_questions}=    Remove Duplicate Questions    ${candidate_questions_list}    ${existing_dict}
    ${unique_count}=    Get Length    ${unique_questions}

    IF    ${unique_count} > 0
        FOR    ${q_text}    IN    @{unique_questions}
            Add Question Item To Bank    ${q_text}
        END
    ELSE
        Log    [INFO] All candidate questions were duplicates. PDF/Bank remains unchanged.
    END

Verify Question Is Added
    [Arguments]    ${question_text}
    [Documentation]    Verifies that a question containing the given text is present in the Question Bank.
    Wait Until Page Contains    ${question_text}    10s

Verify Question Is Not Added
    [Arguments]    ${question_text}
    [Documentation]    Verifies that duplicate questions are NOT added to the Question Bank/PDF (expecting exactly 1 unique instance).
    Wait Until Element Is Visible    id=questionsContainer    10s
    ${elements}=    Get WebElements    css=.question-row-element
    ${match_count}=    Set Variable    0

    FOR    ${element}    IN    @{elements}
        ${raw_text}=    Get Element Attribute    ${element}    data-question-text
        ${norm}=    Normalize Question    ${raw_text}
        ${target_norm}=    Normalize Question    ${question_text}
        IF    "${norm}" == "${target_norm}"
            ${match_count}=    Evaluate    ${match_count} + 1
        END
    END

    Should Be Equal As Integers    ${match_count}    1    msg=Expected exactly 1 unique instance of question: "${question_text}", but found ${match_count} instances.

Generate Duplicate Removal Summary
    [Arguments]    ${total_scanned}    ${duplicates_found}    ${duplicates_removed}    ${remaining_count}
    [Documentation]    Logs clean execution summary.
    Log    === DUPLICATE REMOVAL AUTOMATION SUMMARY ===
    Log    Total Questions Scanned: ${total_scanned}
    Log    Duplicates Identified: ${duplicates_found}
    Log    Duplicates Removed: ${duplicates_removed}
    Log    Remaining Questions: ${remaining_count}
