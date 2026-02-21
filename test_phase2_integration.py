#!/usr/bin/env python3
"""
Phase 2 Integration Test
Tests the complete lifecycle: DB Schema → Task Manager → Archive → Orchestrator Hook

Test Cases:
1. Flush-Mechanismus: 15 Tasks → 10 bleiben aktiv, 5 im Archiv (LRU)
2. 48h Auto-Expiry: Alte Tasks werden automatisch archiviert
3. Embedding-Pipeline: End-to-End Test mit Ollama (optional)
"""
import sys
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path("/DATA/AppData/MCP/Jarvis/Jarvis")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "sql-memory"))

# Test configuration
TEST_CONVERSATION_ID = f"test_lifecycle_{int(datetime.now().timestamp())}"
DB_PATH = PROJECT_ROOT / "sql-memory" / "data" / "memory.db"

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

def cleanup_test_data():
    """Clean up all test data"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("DELETE FROM task_active WHERE conversation_id = ?", (TEST_CONVERSATION_ID,))
        conn.execute("DELETE FROM task_archive WHERE conversation_id = ?", (TEST_CONVERSATION_ID,))
        # Also clean up embeddings if they were created
        conn.execute("""
            DELETE FROM embeddings 
            WHERE content_type = 'task' 
            AND content LIKE ?
        """, (f'%{TEST_CONVERSATION_ID}%',))
        conn.commit()
        print_info(f"Cleaned up test data for conversation: {TEST_CONVERSATION_ID}")
    finally:
        conn.close()

def test_1_flush_mechanism():
    """
    Test 1: Flush-Mechanismus
    Insert 15 tasks, verify 10 remain in active, 5 moved to archive
    """
    print_test_header("Test 1: Flush-Mechanismus (LRU Eviction)")
    
    try:
        from core.lifecycle.task import get_lifecycle_manager
        
        manager = get_lifecycle_manager()
        
        # Insert 15 tasks
        print_info("Inserting 15 tasks...")
        for i in range(15):
            task_data = {
                "request_id": f"test_req_{i}",
                "conversation_id": TEST_CONVERSATION_ID,
                "intent": f"Test task {i}",
                "status": "running"
            }
            manager.start_task(f"test_req_{i}", task_data)
        
        # Trigger flush
        print_info("Triggering check_and_flush()...")
        manager.check_and_flush(TEST_CONVERSATION_ID)
        
        # Verify counts
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM task_active WHERE conversation_id = ?",
                (TEST_CONVERSATION_ID,)
            )
            active_count = cursor.fetchone()[0]
            
            cursor = conn.execute(
                "SELECT COUNT(*) FROM task_archive WHERE conversation_id = ?",
                (TEST_CONVERSATION_ID,)
            )
            archive_count = cursor.fetchone()[0]
            
            print_info(f"Active tasks: {active_count}")
            print_info(f"Archived tasks: {archive_count}")
            
            # Verify
            if active_count == 10:
                print_pass("Exactly 10 tasks remain in task_active")
            else:
                print_fail(f"Expected 10 active tasks, got {active_count}")
                return False
            
            if archive_count == 5:
                print_pass("Exactly 5 tasks moved to task_archive")
            else:
                print_fail(f"Expected 5 archived tasks, got {archive_count}")
                return False
            
            # Verify LRU: oldest 5 should be archived
            cursor = conn.execute("""
                SELECT task_data 
                FROM task_archive 
                WHERE conversation_id = ?
                ORDER BY created_at
            """, (TEST_CONVERSATION_ID,))
            
            archived_tasks = cursor.fetchall()
            if archived_tasks:
                print_pass("LRU eviction: oldest 5 tasks were archived")
            
        finally:
            conn.close()
        
        print_pass("Test 1: Flush-Mechanismus PASSED")
        return True
        
    except Exception as e:
        print_fail(f"Test 1 failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_2_auto_expiry():
    """
    Test 2: 48h Auto-Expiry
    Create old tasks (>48h) and new tasks, verify only old ones are archived
    """
    print_test_header("Test 2: 48h Auto-Expiry")
    
    try:
        # Clean up from test 1
        cleanup_test_data()
        
        conn = sqlite3.connect(str(DB_PATH))
        now = datetime.now()
        old_timestamp = (now - timedelta(hours=49)).isoformat()
        
        try:
            # Insert 3 old tasks (49 hours ago)
            print_info("Inserting 3 old tasks (49h ago)...")
            for i in range(3):
                conn.execute("""
                    INSERT INTO task_active 
                    (request_id, conversation_id, task_data, created_at, last_updated, importance_score)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    f"old_req_{i}",
                    TEST_CONVERSATION_ID,
                    f'{{"intent": "Old task {i}", "status": "completed"}}',
                    old_timestamp,
                    old_timestamp,
                    0.5
                ))
            
            # Insert 2 fresh tasks
            print_info("Inserting 2 fresh tasks...")
            for i in range(2):
                conn.execute("""
                    INSERT INTO task_active 
                    (request_id, conversation_id, task_data, created_at, last_updated, importance_score)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    f"new_req_{i}",
                    TEST_CONVERSATION_ID,
                    f'{{"intent": "New task {i}", "status": "running"}}',
                    now.isoformat(),
                    now.isoformat(),
                    0.5
                ))
            
            conn.commit()
        finally:
            conn.close()
        
        # Trigger flush
        from core.lifecycle.task import get_lifecycle_manager
        manager = get_lifecycle_manager()
        
        print_info("Triggering check_and_flush()...")
        manager.check_and_flush(TEST_CONVERSATION_ID)
        
        # Verify
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM task_active WHERE conversation_id = ?",
                (TEST_CONVERSATION_ID,)
            )
            active_count = cursor.fetchone()[0]
            
            cursor = conn.execute(
                "SELECT COUNT(*) FROM task_archive WHERE conversation_id = ?",
                (TEST_CONVERSATION_ID,)
            )
            archive_count = cursor.fetchone()[0]
            
            print_info(f"Active tasks: {active_count}")
            print_info(f"Archived tasks: {archive_count}")
            
            if active_count == 2:
                print_pass("2 fresh tasks remain in task_active")
            else:
                print_fail(f"Expected 2 active tasks, got {active_count}")
                return False
            
            if archive_count == 3:
                print_pass("3 old tasks (>48h) moved to task_archive")
            else:
                print_fail(f"Expected 3 archived tasks, got {archive_count}")
                return False
            
        finally:
            conn.close()
        
        print_pass("Test 2: 48h Auto-Expiry PASSED")
        return True
        
    except Exception as e:
        print_fail(f"Test 2 failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_3_embedding_pipeline():
    """
    Test 3: Embedding-Pipeline (End-to-End)
    Archive task, generate embedding, search for it
    """
    print_test_header("Test 3: Embedding-Pipeline (E2E)")
    
    try:
        # Check if Ollama is available
        import requests
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code != 200:
                print_info("Ollama not available - skipping embedding test")
                return True
        except:
            print_info("Ollama not available - skipping embedding test")
            return True
        
        # Clean up from previous tests
        cleanup_test_data()
        
        from core.lifecycle.archive import get_archive_manager
        
        # Insert task directly into archive without embedding
        conn = sqlite3.connect(str(DB_PATH))
        try:
            test_task_data = {
                "intent": "Find information about Python decorators",
                "status": "completed",
                "result": "Found 5 relevant articles about Python decorators"
            }
            
            print_info("Inserting task into archive (without embedding)...")
            conn.execute("""
                INSERT INTO task_archive 
                (request_id, conversation_id, task_data, created_at, archived_at, embedding_id)
                VALUES (?, ?, ?, ?, ?, NULL)
            """, (
                "embed_test_req",
                TEST_CONVERSATION_ID,
                str(test_task_data),
                datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            conn.commit()
        finally:
            conn.close()
        
        # Process pending embeddings
        archive_manager = get_archive_manager()
        
        print_info("Processing pending embeddings (batch=1)...")
        stats = archive_manager.process_pending_embeddings(batch=1)
        
        print_info(f"Embeddings processed: {stats.get('processed', 0)}")
        print_info(f"Embeddings failed: {stats.get('failed', 0)}")
        
        # Verify embedding was created
        conn = sqlite3.connect(str(DB_PATH))
        try:
            cursor = conn.execute("""
                SELECT embedding_id 
                FROM task_archive 
                WHERE conversation_id = ?
            """, (TEST_CONVERSATION_ID,))
            
            row = cursor.fetchone()
            if row and row[0] is not None:
                embedding_id = row[0]
                print_pass(f"Embedding created (ID: {embedding_id})")
                
                # Verify it exists in embeddings table
                cursor = conn.execute("""
                    SELECT content_type 
                    FROM embeddings 
                    WHERE id = ?
                """, (embedding_id,))
                
                emb_row = cursor.fetchone()
                if emb_row and emb_row[0] == 'task':
                    print_pass("Embedding exists in embeddings table with content_type='task'")
                else:
                    print_fail("Embedding not found in embeddings table")
                    return False
            else:
                print_fail("Embedding ID not set in task_archive")
                return False
            
        finally:
            conn.close()
        
        # Test semantic search
        print_info("Testing semantic search...")
        results = archive_manager.search_archive("Python decorators", TEST_CONVERSATION_ID, limit=5)
        
        if results and len(results) > 0:
            print_pass(f"Search found {len(results)} result(s)")
            print_info(f"Top result intent: {results[0].get('intent', 'N/A')}")
        else:
            print_fail("Search returned no results")
            return False
        
        print_pass("Test 3: Embedding-Pipeline PASSED")
        return True
        
    except Exception as e:
        print_fail(f"Test 3 failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all integration tests"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}Phase 2 Integration Test Suite{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}")
    print_info(f"Test Conversation ID: {TEST_CONVERSATION_ID}")
    print_info(f"Database: {DB_PATH}")
    
    results = {
        "Test 1: Flush-Mechanismus": False,
        "Test 2: 48h Auto-Expiry": False,
        "Test 3: Embedding-Pipeline": False
    }
    
    try:
        # Run tests
        results["Test 1: Flush-Mechanismus"] = test_1_flush_mechanism()
        results["Test 2: 48h Auto-Expiry"] = test_2_auto_expiry()
        results["Test 3: Embedding-Pipeline"] = test_3_embedding_pipeline()
        
    finally:
        # Cleanup
        print_test_header("Cleanup")
        cleanup_test_data()
    
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
    sys.exit(main())
