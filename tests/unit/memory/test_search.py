"""
Memory Search Tests

Tests for searching memories in TRION's memory system
"""
import pytest


@pytest.mark.memory
class TestMemorySearch:
    """Test suite for memory search operations"""
    
    def test_semantic_search_finds_relevant(self, test_client, multiple_stored_memories):
        """
        Test semantic search finds relevant memories
        
        GIVEN: Multiple memories with different topics
        WHEN: We search for programming-related content
        THEN: We get programming memories, not cooking ones
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        response = test_client.get("/api/memory/search?query=coding")
        
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", [])
        
        assert len(results) > 0, "Should find at least one result"
        
        # Results should be programming-related, not cooking
        for result in results[:3]:  # Check top 3
            content_lower = result["content"].lower()
            is_programming = any(word in content_lower for word in ["python", "javascript", "programming"])
            is_cooking = "cooking" in content_lower or "pasta" in content_lower
            
            # Should prefer programming over cooking for "coding" query
            if is_programming or is_cooking:
                assert is_programming, "Should find programming content for 'coding' query"
    
    def test_keyword_search_exact_match(self, test_client, multiple_stored_memories):
        """
        Test keyword search with exact matching
        
        GIVEN: Memories containing specific keywords
        WHEN: We search for exact keyword
        THEN: We get memories containing that keyword
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        response = test_client.get("/api/memory/search?query=John&exact=true")
        
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", [])
        
        if len(results) > 0:
            # At least one result should contain "John"
            assert any("John" in result["content"] for result in results)
    
    def test_empty_search_results(self, test_client):
        """
        Test search with no matching results
        
        GIVEN: A search query that matches nothing
        WHEN: We search for it
        THEN: We get empty results (not an error)
        """
        response = test_client.get("/api/memory/search?query=nonexistent-keyword-xyz-12345")
        
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", [])
        
        assert len(results) == 0, "Should return empty results for non-matching query"
    
    def test_search_with_type_filter(self, test_client, multiple_stored_memories):
        """
        Test search with memory type filter
        
        GIVEN: Memories of different types (short_term, long_term)
        WHEN: We search with type filter
        THEN: We only get memories of that type
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        response = test_client.get("/api/memory/search?query=memory&type=long_term")
        
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", [])
        
        if len(results) > 0:
            # All results should be long_term
            assert all(r["type"] == "long_term" for r in results), "Should only return long_term memories"
    
    def test_search_with_tag_filter(self, test_client, multiple_stored_memories):
        """
        Test search with tag filter
        
        GIVEN: Memories with different tags
        WHEN: We search with tag filter
        THEN: We only get memories with that tag
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        response = test_client.get("/api/memory/search?query=&tag=programming")
        
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", [])
        
        if len(results) > 0:
            # All results should have "programming" tag
            assert all("programming" in r.get("tags", []) for r in results)
    
    def test_search_pagination(self, test_client, multiple_stored_memories):
        """
        Test search result pagination
        
        GIVEN: Multiple matching memories
        WHEN: We search with limit and offset
        THEN: We get paginated results
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        # First page
        response1 = test_client.get("/api/memory/search?query=memory&limit=2&offset=0")
        assert response1.status_code == 200
        
        page1 = response1.json().get("results", [])
        
        # Second page
        response2 = test_client.get("/api/memory/search?query=memory&limit=2&offset=2")
        assert response2.status_code == 200
        
        page2 = response2.json().get("results", [])
        
        # Pages should be different (if we have enough results)
        if len(page1) > 0 and len(page2) > 0:
            page1_ids = [r["id"] for r in page1]
            page2_ids = [r["id"] for r in page2]
            
            # No overlap between pages
            assert set(page1_ids).isdisjoint(set(page2_ids)), "Pages should not overlap"
    
    def test_search_returns_relevance_score(self, test_client, multiple_stored_memories):
        """
        Test that search returns relevance scores
        
        GIVEN: A search query
        WHEN: We perform the search
        THEN: Results include relevance/similarity scores
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        response = test_client.get("/api/memory/search?query=programming")
        
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", [])
        
        if len(results) > 0:
            # Results should have score/relevance field
            assert any(key in results[0] for key in ["score", "relevance", "similarity"])
    
    def test_search_results_sorted_by_relevance(self, test_client, multiple_stored_memories):
        """
        Test that search results are sorted by relevance
        
        GIVEN: A search query
        WHEN: We get results
        THEN: They are sorted by relevance (best first)
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        response = test_client.get("/api/memory/search?query=programming")
        
        assert response.status_code == 200
        
        data = response.json()
        results = data.get("results", [])
        
        if len(results) >= 2:
            # Results should have scores
            scores = [r.get("score", r.get("relevance", r.get("similarity", 0))) for r in results]
            
            # Scores should be in descending order (best first)
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1], "Results should be sorted by relevance descending"
    
    def test_search_handles_special_characters(self, test_client):
        """
        Test search with special characters in query
        
        GIVEN: A search query with special characters
        WHEN: We search for it
        THEN: No error occurs (even if no results)
        """
        special_queries = [
            "test & memory",
            "python's features",
            "query with \"quotes\"",
            "path/to/file",
            "email@example.com"
        ]
        
        for query in special_queries:
            response = test_client.get(f"/api/memory/search?query={query}")
            
            # Should not error
            assert response.status_code in [200, 400], f"Query '{query}' caused unexpected status"
    
    @pytest.mark.slow
    def test_search_performance(self, test_client, multiple_stored_memories):
        """
        Test search performance (should be fast)
        
        GIVEN: Multiple stored memories
        WHEN: We perform searches
        THEN: Each search completes quickly (< 200ms)
        """
        if not multiple_stored_memories:
            pytest.skip("Could not create test memories")
        
        import time
        
        queries = ["programming", "meeting", "cooking", "project"]
        times = []
        
        for query in queries:
            start = time.time()
            response = test_client.get(f"/api/memory/search?query={query}")
            end = time.time()
            
            assert response.status_code == 200
            times.append(end - start)
        
        avg_time = sum(times) / len(times)
        assert avg_time < 0.2, f"Average search time {avg_time:.3f}s exceeds 200ms threshold"
