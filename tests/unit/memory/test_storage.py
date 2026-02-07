"""
Memory Storage Tests

Tests for storing memories in TRION's memory system
"""
import pytest


@pytest.mark.memory
class TestMemoryStorage:
    """Test suite for memory storage operations"""
    
    def test_store_simple_memory(self, test_client, sample_memory_data):
        """
        Test storing a simple text memory
        
        GIVEN: A simple memory with text content
        WHEN: We store it via /api/memory/store
        THEN: We get a 200 response with memory ID
        """
        response = test_client.post("/api/memory/store", json=sample_memory_data)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "id" in data, "Response should contain memory ID"
        assert data["content"] == sample_memory_data["content"]
        assert data["type"] == sample_memory_data["type"]
        assert set(data["tags"]) == set(sample_memory_data["tags"])
    
    def test_store_json_memory(self, test_client, sample_json_memory):
        """
        Test storing JSON-structured memory
        
        GIVEN: A memory with nested JSON content
        WHEN: We store it
        THEN: The structure is preserved
        """
        response = test_client.post("/api/memory/store", json=sample_json_memory)
        
        assert response.status_code == 200
        
        data = response.json()
        assert "id" in data
        assert data["content"]["key"] == "value"
        assert data["content"]["nested"]["data"] == 123
        assert data["content"]["nested"]["list"] == [1, 2, 3]
    
    def test_store_large_memory(self, test_client, large_memory_data):
        """
        Test storing large memory (100KB)
        
        GIVEN: A large memory payload
        WHEN: We store it
        THEN: The system handles it without errors
        """
        response = test_client.post("/api/memory/store", json=large_memory_data)
        
        assert response.status_code == 200
        
        data = response.json()
        assert "id" in data
        assert len(data["content"]) == len(large_memory_data["content"])
    
    def test_store_memory_with_tags(self, test_client):
        """
        Test storing memory with multiple tags
        
        GIVEN: A memory with custom tags
        WHEN: We store it
        THEN: Tags are preserved
        """
        memory_data = {
            "content": "Tagged memory for testing",
            "type": "long_term",
            "tags": ["important", "project-x", "milestone"]
        }
        
        response = test_client.post("/api/memory/store", json=memory_data)
        
        assert response.status_code == 200
        
        data = response.json()
        assert "important" in data["tags"]
        assert "project-x" in data["tags"]
        assert "milestone" in data["tags"]
    
    def test_store_memory_without_tags(self, test_client):
        """
        Test storing memory without tags (optional field)
        
        GIVEN: A memory without tags
        WHEN: We store it
        THEN: It stores successfully with empty tags
        """
        memory_data = {
            "content": "Memory without tags",
            "type": "short_term"
        }
        
        response = test_client.post("/api/memory/store", json=memory_data)
        
        assert response.status_code == 200
        
        data = response.json()
        assert "id" in data
        assert data.get("tags", []) == [] or data.get("tags") is None
    
    def test_store_memory_invalid_type(self, test_client):
        """
        Test storing memory with invalid type
        
        GIVEN: A memory with invalid type (not 'short_term' or 'long_term')
        WHEN: We try to store it
        THEN: We get a 400 error
        """
        invalid_data = {
            "content": "Test content",
            "type": "invalid_type",
            "tags": ["test"]
        }
        
        response = test_client.post("/api/memory/store", json=invalid_data)
        
        # Should return 400 or 422 (validation error)
        assert response.status_code in [400, 422], f"Expected 400/422, got {response.status_code}"
    
    def test_store_memory_missing_content(self, test_client):
        """
        Test storing memory without content (required field)
        
        GIVEN: A memory request missing content
        WHEN: We try to store it
        THEN: We get a 400/422 validation error
        """
        invalid_data = {
            "type": "short_term",
            "tags": ["test"]
        }
        
        response = test_client.post("/api/memory/store", json=invalid_data)
        
        assert response.status_code in [400, 422]
    
    def test_store_memory_empty_content(self, test_client):
        """
        Test storing memory with empty content
        
        GIVEN: A memory with empty string as content
        WHEN: We try to store it
        THEN: We get a 400/422 validation error
        """
        invalid_data = {
            "content": "",
            "type": "short_term"
        }
        
        response = test_client.post("/api/memory/store", json=invalid_data)
        
        # Should reject empty content
        assert response.status_code in [400, 422]
    
    @pytest.mark.slow
    def test_store_multiple_memories_sequential(self, test_client):
        """
        Test storing multiple memories sequentially
        
        GIVEN: Multiple memory payloads
        WHEN: We store them one after another
        THEN: All get unique IDs
        """
        ids = []
        
        for i in range(10):
            memory_data = {
                "content": f"Sequential memory {i}",
                "type": "short_term",
                "tags": [f"seq-{i}"]
            }
            
            response = test_client.post("/api/memory/store", json=memory_data)
            assert response.status_code == 200
            
            data = response.json()
            ids.append(data["id"])
        
        # All IDs should be unique
        assert len(ids) == len(set(ids)), "All memory IDs should be unique"
