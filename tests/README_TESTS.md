# TRION Test Suite

**Status:** ✅ Phase 0 Complete (Skeleton Built by Senior Claude)  
**Next:** Phase 1 - Memory System Tests  
**Golden Ticket:** Memory must be 80% GREEN before moving to other systems!

---

## 📁 Test Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures and config
├── pytest.ini               # Pytest configuration
│
├── unit/
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── test_storage.py      # ✅ Storage tests (10 tests)
│   │   ├── test_retrieval.py    # ✅ Retrieval tests (9 tests)
│   │   └── test_search.py        # ✅ Search tests (11 tests)
│   ├── thinking/
│   ├── mcp/
│   └── cim/
│
├── integration/
│   ├── memory/
│   ├── thinking/
│   ├── mcp/
│   └── cim/
│
└── e2e/
```

---

## 🚀 Quick Start

### **1. Install Dependencies**

```bash
cd /DATA/AppData/MCP/Jarvis/Jarvis

# Install pytest
pip install pytest pytest-asyncio requests --break-system-packages
```

### **2. Run All Memory Tests**

```bash
# Run all memory tests
pytest tests/unit/memory/ -v

# Run with coverage
pytest tests/unit/memory/ -v --cov=memory --cov-report=term
```

### **3. Run Specific Test File**

```bash
# Storage tests only
pytest tests/unit/memory/test_storage.py -v

# Retrieval tests only
pytest tests/unit/memory/test_retrieval.py -v

# Search tests only
pytest tests/unit/memory/test_search.py -v
```

### **4. Run Specific Test**

```bash
# Run single test
pytest tests/unit/memory/test_storage.py::TestMemoryStorage::test_store_simple_memory -v
```

---

## 📊 Current Test Status

### **Memory System Tests**

| Test File | Tests | Status | Coverage |
|-----------|-------|--------|----------|
| test_storage.py | 10 | ✅ Ready | TBD |
| test_retrieval.py | 9 | ✅ Ready | TBD |
| test_search.py | 11 | ✅ Ready | TBD |
| **TOTAL** | **30** | **✅ Ready** | **TBD** |

### **Test Breakdown**

#### **test_storage.py (10 tests)**
- `test_store_simple_memory` - Store text memory
- `test_store_json_memory` - Store JSON structure
- `test_store_large_memory` - Store 100KB memory
- `test_store_memory_with_tags` - Store with tags
- `test_store_memory_without_tags` - Store without tags
- `test_store_memory_invalid_type` - Validation: invalid type
- `test_store_memory_missing_content` - Validation: missing content
- `test_store_memory_empty_content` - Validation: empty content
- `test_store_multiple_memories_sequential` - Sequential storage (SLOW)

#### **test_retrieval.py (9 tests)**
- `test_retrieve_by_id` - Retrieve by ID
- `test_retrieve_nonexistent_memory` - 404 handling
- `test_retrieve_recent_memories` - Recent with limit
- `test_retrieve_recent_with_default_limit` - Recent default
- `test_retrieve_by_id_returns_complete_data` - All fields present
- `test_retrieve_invalid_id_format` - Security: XSS/traversal
- `test_retrieve_preserves_json_structure` - JSON preservation
- `test_retrieve_performance` - Performance test (SLOW)

#### **test_search.py (11 tests)**
- `test_semantic_search_finds_relevant` - Semantic search
- `test_keyword_search_exact_match` - Keyword search
- `test_empty_search_results` - Empty results handling
- `test_search_with_type_filter` - Filter by type
- `test_search_with_tag_filter` - Filter by tag
- `test_search_pagination` - Pagination
- `test_search_returns_relevance_score` - Scoring
- `test_search_results_sorted_by_relevance` - Sorting
- `test_search_handles_special_characters` - Special chars
- `test_search_performance` - Performance test (SLOW)

---

## 🎯 The Golden Ticket Rule

```
┌─────────────────────────────────────────┐
│  🎫 THE GOLDEN TICKET                   │
│                                         │
│  Memory System must reach:              │
│  ✅ 80% test coverage                   │
│  ✅ All tests GREEN (passing)           │
│                                         │
│  BEFORE moving to:                      │
│  - Sequential Thinking tests            │
│  - MCP tests                            │
│  - CIM tests                            │
│  - Any other system!                    │
└─────────────────────────────────────────┘
```

**Why?** Because everything builds on Memory!

---

## 📖 Test Markers

Tests are organized with markers for selective running:

```bash
# Run only memory tests
pytest -m memory -v

# Run all EXCEPT slow tests
pytest -m "not slow" -v

# Run memory tests, skip slow ones
pytest -m "memory and not slow" -v

# Run integration tests
pytest -m integration -v
```

Available markers:
- `@pytest.mark.memory` - Memory system tests
- `@pytest.mark.thinking` - Sequential thinking tests
- `@pytest.mark.mcp` - MCP integration tests
- `@pytest.mark.cim` - CIM module tests
- `@pytest.mark.slow` - Slow tests (skip during development)
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.e2e` - End-to-end tests

---

## 🔧 Fixtures Available

### **Test Client**
```python
def test_example(test_client):
    response = test_client.post("/api/memory/store", json={...})
    assert response.status_code == 200
```

### **Sample Data**
```python
def test_example(sample_memory_data):
    # sample_memory_data = {"content": "...", "type": "short_term", "tags": [...]}
    pass

def test_example(sample_json_memory):
    # Nested JSON structure
    pass

def test_example(large_memory_data):
    # 100KB memory for stress testing
    pass
```

### **Pre-stored Memories**
```python
def test_example(stored_memory):
    # Single pre-stored memory with ID
    memory_id = stored_memory["id"]
    pass

def test_example(multiple_stored_memories):
    # List of 5 pre-stored memories
    # Includes: programming, cooking, meeting topics
    pass
```

---

## 🐛 Debugging Tests

### **Verbose Output**
```bash
# Show test names and results
pytest -v

# Show print statements
pytest -s

# Show local variables on failure
pytest -l

# All together
pytest -vsl
```

### **Run Only Failed Tests**
```bash
# Re-run only failed tests from last run
pytest --lf

# Run failed tests first, then others
pytest --ff
```

### **Stop on First Failure**
```bash
# Stop after first failure
pytest -x

# Stop after 3 failures
pytest --maxfail=3
```

---

## 📈 Coverage Reports

### **Terminal Report**
```bash
pytest tests/unit/memory/ --cov=memory --cov-report=term
```

### **HTML Report**
```bash
pip install pytest-cov --break-system-packages
pytest tests/unit/memory/ --cov=memory --cov-report=html
# Open htmlcov/index.html in browser
```

### **Missing Lines Report**
```bash
pytest tests/unit/memory/ --cov=memory --cov-report=term-missing
```

---

## ✅ Before Moving to Phase 2

**Checklist:**

```bash
# 1. Run all memory tests
pytest tests/unit/memory/ -v

# 2. Check coverage
pytest tests/unit/memory/ --cov=memory --cov-report=term

# 3. Verify results
# ✅ All tests PASS (GREEN)
# ✅ Coverage > 80%
# ✅ No skipped tests (unless intentional)
# ✅ Performance tests pass

# 4. Only THEN can you move to:
# - tests/unit/thinking/
# - tests/unit/mcp/
# - tests/unit/cim/
```

---

## 🎓 Writing New Tests

### **Test Template**
```python
import pytest

@pytest.mark.memory
class TestMemoryFeature:
    """Test suite for specific feature"""
    
    def test_feature_works(self, test_client):
        """
        Test that feature works as expected
        
        GIVEN: Initial conditions
        WHEN: Action is performed  
        THEN: Expected result occurs
        """
        # Arrange
        data = {"key": "value"}
        
        # Act
        response = test_client.post("/api/endpoint", json=data)
        
        # Assert
        assert response.status_code == 200
        assert response.json()["key"] == "value"
```

### **Best Practices**
1. ✅ One test = One concept
2. ✅ Use GIVEN-WHEN-THEN structure
3. ✅ Descriptive test names
4. ✅ Clear assertion messages
5. ✅ Use fixtures for setup
6. ✅ Clean up after tests (if needed)

---

## 🚨 Common Issues

### **"Connection refused" errors**
```bash
# Make sure TRION API is running
curl http://localhost:8200/health

# Check Docker containers
docker ps | grep jarvis
```

### **"Module not found" errors**
```bash
# Check Python path
export PYTHONPATH=/DATA/AppData/MCP/Jarvis/Jarvis:$PYTHONPATH

# Or run from project root
cd /DATA/AppData/MCP/Jarvis/Jarvis
pytest tests/
```

### **Tests pass locally but fail in CI**
- Check environment variables
- Check database state
- Check file permissions
- Check Docker network

---

## 📚 Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Fixtures](https://docs.pytest.org/en/stable/fixture.html)
- [Pytest Markers](https://docs.pytest.org/en/stable/mark.html)
- [Pytest Coverage](https://pytest-cov.readthedocs.io/)

---

## 🎉 Phase 0 Complete!

**What Senior Claude Built:**
- ✅ Directory structure
- ✅ conftest.py with fixtures
- ✅ pytest.ini configuration
- ✅ 30 Memory System tests
- ✅ This README

**Next Steps for Antigravity:**
1. Install pytest dependencies
2. Make sure TRION API is running
3. Run the tests: `pytest tests/unit/memory/ -v`
4. Fix any failures until all GREEN
5. Achieve 80% coverage
6. Then (and only then!) move to Phase 2

**Good luck! 🚀**

---

**Built by:** Senior Claude  
**For:** Antigravity  
**Date:** 2026-01-30  
**Status:** Ready to Test! 🧪
