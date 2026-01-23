"""
Test Sequential Engine with Memory Integration
"""

import sys
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

from modules.sequential_thinking.engine import SequentialThinkingEngine
from modules.sequential_thinking.types import create_step, create_task

print("\n" + "="*70)
print("TESTING ENGINE WITH MEMORY")
print("="*70)

# === TEST 1: ENGINE WITH MEMORY ===
print("\nTEST 1: Engine has Memory Manager")
print("-" * 70)

engine = SequentialThinkingEngine()
print(f"Engine: {engine}")

assert engine.memory is not None
print(f"Memory: {engine.memory}")
print("✅ TEST 1 PASSED!")

# === TEST 2: MEMORY SHARED ACROSS STEPS ===
print("\nTEST 2: Memory Shared Across Steps")
print("-" * 70)

# Create task where steps depend on each other
task = create_task(
    task_id="test_memory_sharing",
    description="Test memory sharing between steps",
    steps=[
        create_step("load", "Load data (stores in memory)"),
        create_step("process", "Process data (uses from memory)", dependencies=["load"]),
        create_step("analyze", "Analyze results (uses from memory)", dependencies=["process"])
    ]
)

# Execute task
result = engine.execute_task(task)

# Verify memory was used
memory_keys = engine.memory.list_keys()
print(f"\nMemory after execution: {len(memory_keys)} variables")
for key in memory_keys:
    print(f"  - {key}")

assert len(memory_keys) >= 3  # At least 3 step outputs stored
print("✅ TEST 2 PASSED!")

# === TEST 3: MEMORY CLEARED BETWEEN TASKS ===
print("\nTEST 3: Memory Cleared Between Tasks")
print("-" * 70)

# Check memory is not empty
assert len(engine.memory.list_keys()) > 0
print(f"Memory before new task: {len(engine.memory.list_keys())} variables")

# Execute new task
task2 = create_task(
    task_id="test_memory_clear",
    description="Test memory clearing",
    steps=[create_step("s1", "Step 1")]
)

result2 = engine.execute_task(task2)

# Should only have 1 variable (from current task)
memory_keys2 = engine.memory.list_keys()
print(f"Memory after new task: {len(memory_keys2)} variables")

# Old task variables should be gone
assert "step_load_output" not in memory_keys2
print("✅ TEST 3 PASSED!")

# === TEST 4: CONTEXT BUILDING ===
print("\nTEST 4: Context Building for Steps")
print("-" * 70)

# Create task with steps that need context
task3 = create_task(
    task_id="test_context",
    description="Test context building",
    steps=[
        create_step("step1", "First step"),
        create_step("step2", "Second step (should have step1 context)", dependencies=["step1"])
    ]
)

result3 = engine.execute_task(task3)

# Check that steps got context
step2 = result3.steps[1]
print(f"Step 2 context: {list(step2.context.keys())}")

# Should have step1's output in context
assert any("step1" in key for key in step2.context.keys())
print("✅ TEST 4 PASSED!")

# === TEST 5: MEMORY STATS ===
print("\nTEST 5: Memory Statistics")
print("-" * 70)

stats = engine.memory.get_stats()
print(f"Total variables: {stats['total_variables']}")
print(f"Memory size: {stats['size_mb']:.3f} MB")
print(f"Most accessed: {stats['most_accessed'][:3]}")

assert stats['total_variables'] > 0
print("✅ TEST 5 PASSED!")

# === SUMMARY ===
print("\n" + "="*70)
print("🎉 ALL ENGINE + MEMORY TESTS PASSED!")
print("="*70)
print("\nIntegration Working:")
print("  ✅ Engine has MemoryManager")
print("  ✅ Memory shared across steps")
print("  ✅ Memory cleared between tasks")
print("  ✅ Context building from memory")
print("  ✅ Memory statistics available")
print("\n✅ MEMORY INTEGRATION COMPLETE!")
print("="*70)
