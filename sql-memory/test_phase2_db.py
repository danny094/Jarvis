#!/usr/bin/env python3
"""
Phase 2 Integration Test - DB-Level Testing
Tests DB schema directly without Python modules

Test Cases:
1. Schema Verification: Check if task_active and task_archive tables exist
2. Basic Operations: Insert, update, delete tasks
3. Index Performance: Verify indexes are created
"""
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "/app/data/memory.db"
TEST_CONV_ID = f"test_{int(datetime.now().timestamp())}"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def print_test_header(test_name):
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}TEST: {test_name}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")

def print_pass(message):
    print(f"{Colors.GREEN}✅ PASS:{Colors.RESET} {message}")

def print_fail(message):
    print(f"{Colors.RED}❌ FAIL:{Colors.RESET} {message}")

def print_info(message):
    print(f"{Colors.YELLOW}ℹ️  INFO:{Colors.RESET} {message}")

def cleanup():
    """Clean up test data"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM task_active WHERE conversation_id = ?", (TEST_CONV_ID,))
        conn.execute("DELETE FROM task_archive WHERE conversation_id = ?", (TEST_CONV_ID,))
        conn.commit()
        conn.close()
        print_info(f"Cleaned up test data for: {TEST_CONV_ID}")
    except Exception as e:
        print_fail(f"Cleanup failed: {e}")

def test_1_schema_verification():
    """Test 1: Verify Phase 2 schema exists"""
    print_test_header("Test 1: Schema Verification")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check task_active table
        cursor.execute("""
            SELECT sql FROM sqlite_master 
            WHERE type='table' AND name='task_active'
        """)
        task_active_schema = cursor.fetchone()
        
        if task_active_schema:
            schema_str = task_active_schema[0]
            print_pass("task_active table exists")
            
            # Verify required columns
            required_cols = ['task_id', 'conversation_id', 'content', 'created_at', 
                           'last_updated', 'importance_score']
            for col in required_cols:
                if col in schema_str:
                    print_pass(f"  - Column '{col}' exists")
                else:
                    print_fail(f"  - Column '{col}' missing")
                    return False
        else:
            print_fail("task_active table not found")
            return False
        
        # Check task_archive table
        cursor.execute("""
            SELECT sql FROM sqlite_master 
            WHERE type='table' AND name='task_archive'
        """)
        task_archive_schema = cursor.fetchone()
        
        if task_archive_schema:
            schema_str = task_archive_schema[0]
            print_pass("task_archive table exists")
            
            # Verify required columns
            required_cols = ['task_id', 'conversation_id', 'content', 'archived_at', 
                           'embedding_id']
            for col in required_cols:
                if col in schema_str:
                    print_pass(f"  - Column '{col}' exists")
                else:
                    print_fail(f"  - Column '{col}' missing")
                    return False
        else:
            print_fail("task_archive table not found")
            return False
        
        # Check index
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='index' AND name='idx_task_active_conv'
        """)
        index_exists = cursor.fetchone()
        
        if index_exists:
            print_pass("Index idx_task_active_conv exists")
        else:
            print_fail("Index idx_task_active_conv missing")
            return False
        
        conn.close()
        print_pass("Test 1: Schema Verification PASSED")
        return True
        
    except Exception as e:
        print_fail(f"Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_2_basic_operations():
    """Test 2: Basic CRUD operations"""
    print_test_header("Test 2: Basic CRUD Operations")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        
        # INSERT 15 tasks
        print_info("Inserting 15 tasks into task_active...")
        for i in range(15):
            conn.execute("""
                INSERT INTO task_active 
                (task_id, conversation_id, content, importance_score)
                VALUES (?, ?, ?, ?)
            """, (f"test_task_{i}", TEST_CONV_ID, f'{{"intent":"Task {i}"}}', 0.5))
        conn.commit()
        
        # Verify count
        cursor = conn.execute(
            "SELECT COUNT(*) FROM task_active WHERE conversation_id = ?", 
            (TEST_CONV_ID,)
        )
        count = cursor.fetchone()[0]
        
        if count == 15:
            print_pass(f"Successfully inserted 15 tasks (count: {count})")
        else:
            print_fail(f"Expected 15 tasks, got {count}")
            conn.close()
            return False
        
        # MOVE 5 oldest to archive (simulating flush)
        print_info("Moving 5 oldest tasks to archive...")
        
        # Get 5 oldest task IDs
        cursor = conn.execute("""
            SELECT task_id, content 
            FROM task_active 
            WHERE conversation_id = ?
            ORDER BY last_updated ASC
            LIMIT 5
        """, (TEST_CONV_ID,))
        oldest_tasks = cursor.fetchall()
        
        # Move to archive
        for task_id, content in oldest_tasks:
            # Insert into archive
            conn.execute("""
                INSERT INTO task_archive 
                (task_id, conversation_id, content, embedding_id)
                VALUES (?, ?, ?, NULL)
            """, (task_id, TEST_CONV_ID, content))
            
            # Delete from active
            conn.execute(
                "DELETE FROM task_active WHERE task_id = ?", 
                (task_id,)
            )
        
        conn.commit()
        
        # Verify counts after move
        cursor = conn.execute(
            "SELECT COUNT(*) FROM task_active WHERE conversation_id = ?", 
            (TEST_CONV_ID,)
        )
        active_count = cursor.fetchone()[0]
        
        cursor = conn.execute(
            "SELECT COUNT(*) FROM task_archive WHERE conversation_id = ?", 
            (TEST_CONV_ID,)
        )
        archive_count = cursor.fetchone()[0]
        
        print_info(f"Active tasks: {active_count}")
        print_info(f"Archived tasks: {archive_count}")
        
        if active_count == 10:
            print_pass("10 tasks remain in task_active")
        else:
            print_fail(f"Expected 10 active tasks, got {active_count}")
            conn.close()
            return False
        
        if archive_count == 5:
            print_pass("5 tasks moved to task_archive")
        else:
            print_fail(f"Expected 5 archived tasks, got {archive_count}")
            conn.close()
            return False
        
        conn.close()
        print_pass("Test 2: Basic CRUD Operations PASSED")
        return True
        
    except Exception as e:
        print_fail(f"Test 2 failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_3_expiry_simulation():
    """Test 3: Simulate 48h auto-expiry"""
    print_test_header("Test 3: 48h Auto-Expiry Simulation")
    
    try:
        cleanup()  # Start fresh
        
        conn = sqlite3.connect(DB_PATH)
        now = datetime.now()
        old_time = (now - timedelta(hours=49)).isoformat()
        
        # Insert 3 old tasks
        print_info("Inserting 3 old tasks (49h ago)...")
        for i in range(3):
            conn.execute("""
                INSERT INTO task_active 
                (task_id, conversation_id, content, created_at, last_updated, importance_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                f"old_task_{i}", 
                TEST_CONV_ID, 
                f'{{"intent":"Old task {i}"}}',
                old_time,
                old_time,
                0.5
            ))
        
        # Insert 2 fresh tasks
        print_info("Inserting 2 fresh tasks...")
        for i in range(2):
            conn.execute("""
                INSERT INTO task_active 
                (task_id, conversation_id, content, importance_score)
                VALUES (?, ?, ?, ?)
            """, (f"new_task_{i}", TEST_CONV_ID, f'{{"intent":"New task {i}"}}', 0.5))
        
        conn.commit()
        
        # Simulate expiry: move tasks older than 48h to archive
        print_info("Simulating expiry check...")
        expiry_cutoff = (now - timedelta(hours=48)).isoformat()
        
        cursor = conn.execute("""
            SELECT task_id, content 
            FROM task_active 
            WHERE conversation_id = ? AND created_at < ?
        """, (TEST_CONV_ID, expiry_cutoff))
        expired_tasks = cursor.fetchall()
        
        for task_id, content in expired_tasks:
            conn.execute("""
                INSERT INTO task_archive 
                (task_id, conversation_id, content, embedding_id)
                VALUES (?, ?, ?, NULL)
            """, (task_id, TEST_CONV_ID, content))
            
            conn.execute(
                "DELETE FROM task_active WHERE task_id = ?", 
                (task_id,)
            )
        
        conn.commit()
        
        # Verify
        cursor = conn.execute(
            "SELECT COUNT(*) FROM task_active WHERE conversation_id = ?", 
            (TEST_CONV_ID,)
        )
        active_count = cursor.fetchone()[0]
        
        cursor = conn.execute(
            "SELECT COUNT(*) FROM task_archive WHERE conversation_id = ?", 
            (TEST_CONV_ID,)
        )
        archive_count = cursor.fetchone()[0]
        
        print_info(f"Active tasks: {active_count}")
        print_info(f"Archived tasks: {archive_count}")
        
        if active_count == 2:
            print_pass("2 fresh tasks remain active")
        else:
            print_fail(f"Expected 2 active tasks, got {active_count}")
            conn.close()
            return False
        
        if archive_count == 3:
            print_pass("3 old tasks moved to archive")
        else:
            print_fail(f"Expected 3 archived tasks, got {archive_count}")
            conn.close()
            return False
        
        conn.close()
        print_pass("Test 3: 48h Auto-Expiry PASSED")
        return True
        
    except Exception as e:
        print_fail(f"Test 3 failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}Phase 2 DB-Level Integration Test{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    print_info(f"Database: {DB_PATH}")
    print_info(f"Test Conversation ID: {TEST_CONV_ID}")
    
    results = {
        "Schema Verification": False,
        "Basic CRUD Operations": False,
        "48h Auto-Expiry": False
    }
    
    try:
        results["Schema Verification"] = test_1_schema_verification()
        results["Basic CRUD Operations"] = test_2_basic_operations()
        results["48h Auto-Expiry"] = test_3_expiry_simulation()
    finally:
        print_test_header("Cleanup")
        cleanup()
    
    # Summary
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}Test Summary{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    
    for test_name, passed in results.items():
        status = f"{Colors.GREEN}PASS{Colors.RESET}" if passed else f"{Colors.RED}FAIL{Colors.RESET}"
        print(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print(f"\n{Colors.GREEN}{'='*60}{Colors.RESET}")
        print(f"{Colors.GREEN}✅ ALL TESTS PASSED{Colors.RESET}")
        print(f"{Colors.GREEN}{'='*60}{Colors.RESET}\n")
        return 0
    else:
        print(f"\n{Colors.RED}{'='*60}{Colors.RESET}")
        print(f"{Colors.RED}❌ SOME TESTS FAILED{Colors.RESET}")
        print(f"{Colors.RED}{'='*60}{Colors.RESET}\n")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
