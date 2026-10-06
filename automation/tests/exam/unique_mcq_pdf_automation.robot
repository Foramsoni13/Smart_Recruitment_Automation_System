*** Settings ***
Documentation    Robot Framework Automated Test Suite for Duplicate MCQ Question Detection & PDF Generation Rules.
...              Ensures duplicate MCQ questions are never added to the PDF or Question Bank.
Resource         ../../resources/question_keywords.resource
Test Setup       Open Question Bank
Test Teardown    Close Browser

*** Test Cases ***
Scenario 1: New Unique Question Is Added Successfully
    [Documentation]    Verifies that a genuinely new, unique MCQ question is added successfully.
    ${unique_q}=    Set Variable    What is the primary function of Python GIL in CPython?
    ${candidate_list}=    Create List    ${unique_q}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    Should Contain    ${added_list}    ${unique_q}
    Verify Question Is Added    ${unique_q}

Scenario 2: Exact Duplicate Question Is Not Added
    [Documentation]    Verifies that an exact duplicate question is detected and rejected.
    ${original_q}=    Set Variable    What is the capital city of France?
    ${duplicate_q}=   Set Variable    What is the capital city of France?
    ${candidate_list}=    Create List    ${original_q}    ${duplicate_q}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    Verify Question Is Not Added    ${original_q}

Scenario 3: Duplicate With Different Capitalization Is Not Added
    [Documentation]    Verifies case-insensitive duplicate detection (e.g. 'WHAT IS HYPERTEXT' vs 'what is hypertext').
    ${q1}=    Set Variable    What Is The Time Complexity Of Binary Search?
    ${q2}=    Set Variable    what is the time complexity of binary search?
    ${candidate_list}=    Create List    ${q1}    ${q2}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    Verify Question Is Not Added    ${q1}

Scenario 4: Duplicate With Extra Spaces Is Not Added
    [Documentation]    Verifies that extra inner and outer whitespace is normalized before duplicate comparison.
    ${q1}=    Set Variable    Which data structure uses LIFO order?
    ${q2}=    Set Variable    Which   data   structure    uses   LIFO   order?   
    ${candidate_list}=    Create List    ${q1}    ${q2}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    Verify Question Is Not Added    ${q1}

Scenario 5: Duplicate With Line Breaks And Formatting Differences Is Not Added
    [Documentation]    Verifies that questions with line breaks and formatting differences are recognized as duplicates.
    ${q1}=    Set Variable    Explain the ACID properties in SQL databases.
    ${q2}=    Set Variable    Explain the ACID\nproperties in SQL\r\ndatabases.
    ${candidate_list}=    Create List    ${q1}    ${q2}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    Verify Question Is Not Added    ${q1}

Scenario 6: Multiple Duplicates In The Same Input Retains Only One Occurrence
    [Documentation]    Verifies that when input contains 3 identical questions, only 1 unique question is retained and added.
    ${q_text}=    Set Variable    What does HTML stand for in Web Development?
    ${candidate_list}=    Create List    ${q_text}    ${q_text}    ${q_text}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    ${length}=    Get Length    ${added_list}
    Should Be Equal As Integers    ${length}    1
    Verify Question Is Not Added    ${q_text}

Scenario 7: New Question Matching An Existing PDF Question Is Not Added
    [Documentation]    Verifies that a new question matching an existing question record in the bank/PDF is rejected.
    ${existing_q}=    Set Variable    What is the default port number for HTTP protocol?
    # Ensure existing question is present
    Add Question Item To Bank    ${existing_q}
    # Attempt adding matching question again
    ${candidate_list}=    Create List    ${existing_q}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    ${added_count}=   Get Length    ${added_list}
    Should Be Equal As Integers    ${added_count}    0
    Verify Question Is Not Added    ${existing_q}

Scenario 8: All Duplicate Input Leaves Question Bank And PDF Unchanged
    [Documentation]    Verifies that when all input questions are duplicates, 0 questions are added and the bank remains unchanged.
    ${dup1}=    Set Variable    What is 5 + 5?
    ${dup2}=    Set Variable    what   is   5   +   5?
    Add Question Item To Bank    ${dup1}
    ${candidate_list}=    Create List    ${dup1}    ${dup2}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    ${added_count}=   Get Length    ${added_list}
    Should Be Equal As Integers    ${added_count}    0

Scenario 9: Mixed Input Containing New And Duplicate Questions Adds Only New Questions
    [Documentation]    Verifies that in a batch containing 2 new questions and 2 duplicates, only the 2 new questions are added.
    ${new1}=    Set Variable    Which HTTP method is idempotent for resource updates?
    ${new2}=    Set Variable    What is the time complexity of Quick Sort in average case?
    ${dup1}=    Set Variable    Which HTTP method is idempotent for resource updates?
    ${dup2}=    Set Variable    what is the time complexity of quick sort in average case?
    ${candidate_list}=    Create List    ${new1}    ${new2}    ${dup1}    ${dup2}
    ${added_list}=    Add Unique Questions    ${candidate_list}
    ${added_count}=   Get Length    ${added_list}
    Should Be Equal As Integers    ${added_count}    2
    Verify Question Is Not Added    ${new1}
    Verify Question Is Not Added    ${new2}
