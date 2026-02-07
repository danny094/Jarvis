"""
Memory Retrieval Tests

Tests for retrieving memories from TRION's memory system
"""
import pytest


@pytest.mark.memory
class TestMemoryRetrieval:
    """Test suite for memory retrieval operations"""
    
    def test_retrieve_by_id(self, test_client, stored_memory):
        """
        Test retrieving a memory by its ID
        
        GIVEN: A stored memory with known ID
        WHEN: We retrieve it by ID
        THEN: We get the correct memory back
        """
        if not stored_memory:
            pytest.skip("Could not create test memory")
        
        memory_id = stored_memory["id"]
        response = test_client.get(f"/api/memory/retrieve/{memory_id}")
        
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == memory_id
        assert data["content"] == stored_memory["content"]
        assert data["type"] == stored_memory["type"]
    
    def test_retrieve_nonexistent_memory(self, test_client):
        """
        Test retrieving a non-existent memory
        
        GIVEN: A non-existent memory ID
        WHEN: We try to retrieve it
        THEN: We get a 404 error
        """
        response = test_client.get("/api/memory/retrieve/nonexistent-id-12345")
        
        assert response.status_code == 404
        
        error = response.json()
        assert "not found" in error.get("detail", "").lower() or "not found" in error.get("error", "").lower()
    
    def test_retrieve_recent_memories(self, test_client, multiple_stored_memories):
        """
        Test retrieving N most recent memories
        
        GIVEN: Multiple stored memories
        WHEN: We request recent memories with limit
        THEN: We get the most recent ones
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        response = test_client.get("/api/memory/recent?limit=3")
        
        assert response.status_code == 200
        
        data = response.json()
        memories = data.get("memories", [])
        
        assert len(memories) <= 3, "Should not return more than limit"
        assert len(memories) > 0, "Should return at least one memory"
    
    def test_retrieve_recent_with_default_limit(self, test_client, multiple_stored_memories):
        """
        Test retrieving recent memories without limit (uses default)
        
        GIVEN: Multiple stored memories
        WHEN: We request recent memories without limit
        THEN: We get default number of memories
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        response = test_client.get("/api/memory/recent")
        
        assert response.status_code == 200
        
        data = response.json()
        memories = data.get("memories", [])
        
        assert len(memories) > 0, "Should return memories"
    
    def test_retrieve_by_id_returns_complete_data(self, test_client):
        """
        Test that retrieval returns all memory fields
        
        GIVEN: A stored memory with all fields
        WHEN: We retrieve it
        THEN: All fields are present in response
        """
        # Store memory with all fields
        memory_data = {
            "content": "Complete memory test",
            "type": "long_term",
            "tags": ["complete", "test"]
        }
        
        store_response = test_client.post("/api/memory/store", json=memory_data)
        assert store_response.status_code == 200
        
        memory_id = store_response.json()["id"]
        
        # Retrieve it
        response = test_client.get(f"/api/memory/retrieve/{memory_id}")
        
        assert response.status_code == 200
        
        data = response.json()
        assert "id" in data
        assert "content" in data
        assert "type" in data
        assert "tags" in data
        assert "created_at" in data or "timestamp" in data  # Timestamp field
    
    def test_retrieve_invalid_id_format(self, test_client):
        """
        Test retrieving with invalid ID format
        
        GIVEN: An invalid ID format (e.g., special characters)
        WHEN: We try to retrieve it
        THEN: We get a 400 or 404 error
        """
        invalid_ids = [
            "/api/memory/retrieve/",  # Empty ID
            "/api/memory/retrieve/<script>alert('xss')</script>",  # XSS attempt
            "/api/memory/retrieve/../admin",  # Path traversal attempt
        ]
        
        for invalid_id in invalid_ids:
            response = test_client.get(invalid_id)
            # Should return 400 (bad request) or 404 (not found)
            assert response.status_code in [400, 404, 422]
    
    def test_retrieve_preserves_json_structure(self, test_client, sample_json_memory):
        """
        Test that JSON structure is preserved through store and retrieve
        
        GIVEN: A memory with complex JSON structure
        WHEN: We store and then retrieve it
        THEN: The structure is identical
        """
        # Store
        store_response = test_client.post("/api/memory/store", json=sample_json_memory)
        assert store_response.status_code == 200
        
        memory_id = store_response.json()["id"]
        
        # Retrieve
        response = test_client.get(f"/api/memory/retrieve/{memory_id}")
        
        assert response.status_code == 200
        
        data = response.json()
        assert data["content"]["key"] == sample_json_memory["content"]["key"]
        assert data["content"]["nested"]["data"] == sample_json_memory["content"]["nested"]["data"]
        assert data["content"]["nested"]["list"] == sample_json_memory["content"]["nested"]["list"]
    
    @pytest.mark.slow
    def test_retrieve_performance(self, test_client, stored_memory):
        """
        Test retrieval performance (should be fast)
        
        GIVEN: A stored memory
        WHEN: We retrieve it multiple times
        THEN: Each retrieval is fast (< 100ms)
        """
        if not stored_memory:
            pytest.skip("Could not create test memory")
        
        import time
        
        memory_id = stored_memory["id"]
        times = []
        
        for _ in range(10):
            start = time.time()
            response = test_client.get(f"/api/memory/retrieve/{memory_id}")
            end = time.time()
            
            assert response.status_code == 200
            times.append(end - start)
        
        avg_time = sum(times) / len(times)
        assert avg_time < 0.1, f"Average retrieval time {avg_time:.3f}s exceeds 100ms threshold"
