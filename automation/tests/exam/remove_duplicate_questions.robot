*** Settings ***
Documentation    Robot Framework Test Suite for Identifying & Safely Removing Duplicate MCQ Questions.
Resource         ../../resources/question_keywords.resource
Test Setup       Open Question Bank
Test Teardown    Close Browser

*** Test Cases ***
Verify MCQ Question Bank Displays Properly
    [Documentation]    Ensures Question Bank page loads with valid container, header, search toolbar, and action controls.
    Page Should Contain Element    id=questionsContainer
    Page Should Contain Element    id=questionSearchInput
    Page Should Contain Element    id=btnRemoveDuplicates
    Page Should Contain Element    id=difficultyFilter
    Page Should Contain Element    id=categoryFilter

Scan And Remove Duplicate Questions Automated Test
    [Documentation]    Scans all questions in the bank, normalizes text, identifies duplicates, removes only duplicate records, and verifies summary stats.
    ${originals}    ${duplicates}=    Find Duplicate Questions
    ${total_elements}=    Get Element Count    css=.question-row-element
    ${dup_count}=    Get Length    ${duplicates}

    Log    Total Scanned: ${total_elements}
    Log    Duplicates Identified: ${dup_count}

    IF    ${dup_count} > 0
        FOR    ${dup_id}    IN    @{duplicates}
            Remove Duplicate Question    ${dup_id}
        END
    END

    ${remaining_elements}=    Get Element Count    css=.question-row-element
    ${expected_remaining}=    Evaluate    ${total_elements} - ${dup_count}
    Should Be Equal As Integers    ${remaining_elements}    ${expected_remaining}

    Generate Duplicate Removal Summary    ${total_elements}    ${dup_count}    ${dup_count}    ${remaining_elements}

Verify Idempotent Execution On Clean Question Bank
    [Documentation]    Running duplicate removal on a cleaned bank should result in 0 duplicates found and zero deletions.
    ${originals}    ${duplicates}=    Find Duplicate Questions
    ${dup_count}=    Get Length    ${duplicates}
    Should Be Equal As Integers    ${dup_count}    0
