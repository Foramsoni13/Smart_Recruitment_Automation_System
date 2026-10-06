"""
Automated Test Script for Interview Scheduling & Conflict Detection
Verifies DB schema initialization, conflict detection logic, scheduling, updating, and candidate access.
"""

import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection

def run_tests():
    print("=" * 60)
    print("STARTING INTERVIEW SCHEDULING & CONFLICT DETECTION TESTS")
    print("=" * 60)

    connection = get_connection()
    if not connection:
        print("❌ FAILED: Database connection unavailable.")
        sys.exit(1)

    cursor = connection.cursor(dictionary=True)

    # 1. Verify interviews table exists
    try:
        cursor.execute("SHOW TABLES LIKE 'interviews'")
        tbl = cursor.fetchone()
        if not tbl:
            print("❌ FAILED: 'interviews' table does not exist.")
            sys.exit(1)
        print("✅ PASS: 'interviews' database table verified.")
    except Exception as e:
        print("❌ FAILED checking interviews table:", e)
        sys.exit(1)

    # 2. Get or create test candidate
    cursor.execute("SELECT id, name, email FROM candidates LIMIT 1")
    cand = cursor.fetchone()
    if not cand:
        cursor.execute("""
            INSERT INTO candidates (name, email, phone, position, status)
            VALUES ('Test Candidate', 'testcand@example.com', '1234567890', 'Python Developer', 'New')
        """)
        connection.commit()
        cand_id = cursor.lastrowid
        cand_name = 'Test Candidate'
        cand_email = 'testcand@example.com'
    else:
        cand_id = cand['id']
        cand_name = cand['name']
        cand_email = cand['email']

    # Cleanup old test records for clean run
    cursor.execute("DELETE FROM interviews WHERE interviewer_name LIKE 'TestInterviewer%'")
    connection.commit()

    # 3. Test Scheduling First Interview (10:00 to 11:00)
    interviewer_1 = "TestInterviewer Alice"
    test_date = "2026-09-20"
    start_1 = "10:00:00"
    end_1 = "11:00:00"

    cursor.execute("""
        INSERT INTO interviews (candidate_id, candidate_name, candidate_email, interviewer_name, interview_date, start_time, end_time, interview_type, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'Technical', 'Scheduled')
    """, (cand_id, cand_name, cand_email, interviewer_1, test_date, start_1, end_1))
    connection.commit()
    intv1_id = cursor.lastrowid
    print(f"✅ PASS: Scheduled Interview #1 (ID {intv1_id}) for {interviewer_1} from {start_1} to {end_1}.")

    # 4. Test Overlap Conflict Detection (10:30 to 11:30 - Overlaps with Interview #1)
    start_2 = "10:30:00"
    end_2 = "11:30:00"

    conflict_query = """
        SELECT id, candidate_name, interviewer_name, interview_date, start_time, end_time
        FROM interviews
        WHERE LOWER(interviewer_name) = LOWER(%s)
          AND interview_date = %s
          AND status != 'Cancelled'
          AND (start_time < %s AND end_time > %s)
    """
    cursor.execute(conflict_query, (interviewer_1, test_date, end_2, start_2))
    conflict = cursor.fetchone()

    if conflict and conflict['id'] == intv1_id:
        print(f"✅ PASS: Interviewer Conflict correctly detected! Overlapping booking ID #{conflict['id']} from {conflict['start_time']} to {conflict['end_time']}.")
    else:
        print("❌ FAILED: Expected conflict not detected for overlapping time slot.")
        sys.exit(1)

    # 5. Test Non-Overlapping Slot (11:00 to 12:00 - Adjacent, No Conflict)
    start_3 = "11:00:00"
    end_3 = "12:00:00"
    cursor.execute(conflict_query, (interviewer_1, test_date, end_3, start_3))
    conflict_3 = cursor.fetchone()

    if not conflict_3:
        print("✅ PASS: Non-overlapping adjacent slot (11:00 - 12:00) verified as conflict-free.")
    else:
        print("❌ FAILED: False conflict reported for non-overlapping adjacent slot.")
        sys.exit(1)

    # 6. Test Cancelled Interview Conflict Exemption
    cursor.execute("UPDATE interviews SET status = 'Cancelled' WHERE id = %s", (intv1_id,))
    connection.commit()

    cursor.execute(conflict_query, (interviewer_1, test_date, end_2, start_2))
    conflict_after_cancel = cursor.fetchone()

    if not conflict_after_cancel:
        print("✅ PASS: Cancelled interviews correctly ignored during conflict checks.")
    else:
        print("❌ FAILED: Cancelled interview still triggering conflicts.")
        sys.exit(1)

    # Clean up test rows
    cursor.execute("DELETE FROM interviews WHERE interviewer_name LIKE 'TestInterviewer%'")
    connection.commit()

    cursor.close()
    connection.close()

    print("=" * 60)
    print("ALL INTERVIEW SCHEDULING & CONFLICT TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == '__main__':
    run_tests()
