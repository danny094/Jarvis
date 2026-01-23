"""
Test Sequential Thinking Memory Manager
"""

import sys
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

from modules.sequential_thinking.memory import (
    MemoryManager, 
    MemoryEntry,
    create_memory_manager
)
from datetime import datetime

print("\n" + "="*70)
print("TESTING MEMORY MANAGER")
print("="*70)

# === TEST 1: INITIALIZATION ===
print("\nTEST 1: Memory Manager Initialization")
print("-" * 70)

memory = create_memory_manager(max_size_mb=50.0)
print(f"Created: {memory}")

assert len(memory.memory) == 0
assert memory.max_size_mb == 50.0
print("✅ TEST 1 PASSED!")

# === TEST 2: STORE & RETRIEVE ===
print("\nTEST 2: Store and Retrieve Variables")
print("-" * 70)

# Store variable
success = memory.store("sales_data", [1, 2, 3, 4, 5], "step_1")
assert success
print("Stored: sales_data")

# Retrieve variable
data = memory.get("sales_data", "step_2")
assert data == [1, 2, 3, 4, 5]
print(f"Retrieved: {data}")

# Check if exists
assert memory.has("sales_data")
print("Exists: True")

# Get non-existent
none_data = memory.get("nonexistent")
assert none_data is None
print("Non-existent: None")

print("✅ TEST 2 PASSED!")

# === TEST 3: UPDATE VARIABLE ===
print("\nTEST 3: Update Variable")
print("-" * 70)

# Store initial value
memory.store("counter", 0, "step_1")
print(f"Initial: counter = 0")

# Update value
memory.store("counter", 10, "step_2")
value = memory.get("counter")
assert value == 10
print(f"Updated: counter = {value}")

# Check entry metadata
entry = memory.get_entry("counter")
assert entry.created_by == "step_1"  # Created by step_1
assert entry.access_count >= 1  # Accessed at least once
print(f"Created by: {entry.created_by}")
print(f"Access count: {entry.access_count}")

print("✅ TEST 3 PASSED!")

# === TEST 4: MULTIPLE VARIABLES ===
print("\nTEST 4: Multiple Variables")
print("-" * 70)

# Store multiple
memory.store("var1", "value1", "step_1")
memory.store("var2", "value2", "step_2")
memory.store("var3", "value3", "step_3")

keys = memory.list_keys()
print(f"Keys: {keys}")
assert len(keys) >= 5  # sales_data, counter, var1, var2, var3

# Get variables by step
vars_step1 = memory.get_variables_created_by("step_1")
print(f"Variables created by step_1: {list(vars_step1.keys())}")

print("✅ TEST 4 PASSED!")

# === TEST 5: BUILD CONTEXT ===
print("\nTEST 5: Build Context")
print("-" * 70)

# Build full context
context = memory.build_context("step_4")
print(f"Full context: {len(context)} variables")
assert len(context) >= 5

# Build filtered context (include only)
filtered = memory.build_context(
    "step_5",
    include_keys=["sales_data", "counter"]
)
print(f"Filtered context: {list(filtered.keys())}")
assert len(filtered) == 2
assert "sales_data" in filtered
assert "counter" in filtered

# Build filtered context (exclude)
excluded = memory.build_context(
    "step_6",
    exclude_keys=["var1", "var2", "var3"]
)
print(f"Excluded context: {list(excluded.keys())}")
assert "var1" not in excluded

print("✅ TEST 5 PASSED!")

# === TEST 6: DELETE VARIABLE ===
print("\nTEST 6: Delete Variable")
print("-" * 70)

# Delete variable
success = memory.delete("var3", "step_7")
assert success
print("Deleted: var3")

# Verify deleted
assert not memory.has("var3")
print("Exists: False")

# Delete non-existent
success = memory.delete("nonexistent")
assert not success
print("Delete non-existent: False")

print("✅ TEST 6 PASSED!")

# === TEST 7: CHECKPOINTS ===
print("\nTEST 7: Checkpoints")
print("-" * 70)

# Create checkpoint
memory.create_checkpoint("checkpoint_1")
print("Checkpoint created: checkpoint_1")

# Store new variable
memory.store("new_var", "new_value", "step_8")
assert memory.has("new_var")
print("Added: new_var")

# Restore checkpoint
success = memory.restore_checkpoint("checkpoint_1")
assert success
print("Restored: checkpoint_1")

# Verify new_var is gone
assert not memory.has("new_var")
print("new_var removed: True")

# List checkpoints
checkpoints = memory.list_checkpoints()
print(f"Checkpoints: {checkpoints}")
assert "checkpoint_1" in checkpoints

print("✅ TEST 7 PASSED!")

# === TEST 8: MEMORY STATS ===
print("\nTEST 8: Memory Statistics")
print("-" * 70)

stats = memory.get_stats()
print(f"Total variables: {stats['total_variables']}")
print(f"Size: {stats['size_mb']:.2f} MB")
print(f"Checkpoints: {stats['checkpoints']}")
print(f"Most accessed: {stats['most_accessed'][:3]}")
print(f"Variables by step: {stats['variables_by_step']}")

assert stats['total_variables'] > 0
assert stats['size_mb'] >= 0.0

print("✅ TEST 8 PASSED!")

# === TEST 9: ACCESS LOG ===
print("\nTEST 9: Access Log")
print("-" * 70)

# Get full log
log = memory.get_access_log()
print(f"Total access log entries: {len(log)}")
assert len(log) > 0

# Get log for specific step
log_step1 = memory.get_access_log("step_1")
print(f"Access log for step_1: {len(log_step1)} entries")

# Print sample entries
if log:
    print(f"Sample entry: {log[-1]}")

print("✅ TEST 9 PASSED!")

# === TEST 10: MEMORY SIZE ===
print("\nTEST 10: Memory Size Tracking")
print("-" * 70)

# Store large data
large_data = list(range(10000))
memory.store("large_data", large_data, "step_9")

size_mb = memory.get_size_mb()
print(f"Memory size: {size_mb:.2f} MB")
assert size_mb > 0.0

# Check if over limit (should warn but still store)
if size_mb > memory.max_size_mb:
    print(f"⚠️  Over limit ({memory.max_size_mb}MB)")

print("✅ TEST 10 PASSED!")

# === TEST 11: METADATA ===
print("\nTEST 11: Metadata Support")
print("-" * 70)

# Store with metadata
memory.store(
    "user_data",
    {"name": "Danny"},
    "step_10",
    metadata={"type": "user_profile", "version": "1.0"}
)

entry = memory.get_entry("user_data")
print(f"Metadata: {entry.metadata}")
assert entry.metadata["type"] == "user_profile"
assert entry.metadata["version"] == "1.0"

print("✅ TEST 11 PASSED!")

# === TEST 12: CLEAR MEMORY ===
print("\nTEST 12: Clear Memory")
print("-" * 70)

# Store some data
initial_count = len(memory.list_keys())
print(f"Variables before clear: {initial_count}")

# Clear memory
memory.clear()
print("Memory cleared")

# Verify empty
assert len(memory.list_keys()) == 0
print("Variables after clear: 0")

print("✅ TEST 12 PASSED!")

# === SUMMARY ===
print("\n" + "="*70)
print("🎉 ALL MEMORY MANAGER TESTS PASSED!")
print("="*70)
print("\nFeatures Tested:")
print("  ✅ Initialization")
print("  ✅ Store and retrieve variables")
print("  ✅ Update variables")
print("  ✅ Multiple variables")
print("  ✅ Build context (filtered)")
print("  ✅ Delete variables")
print("  ✅ Checkpoints (create/restore)")
print("  ✅ Memory statistics")
print("  ✅ Access logging")
print("  ✅ Memory size tracking")
print("  ✅ Metadata support")
print("  ✅ Clear memory")
print("\n✅ MEMORY MANAGER READY FOR INTEGRATION!")
print("="*70)
