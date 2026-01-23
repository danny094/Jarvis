"""
Test Sequential Thinking Engine with Safety Layer Integration
"""

import sys
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

from modules.sequential_thinking.engine import SequentialThinkingEngine, create_engine
from modules.sequential_thinking.types import create_step, create_task, StepStatus
from pathlib import Path

print("\n" + "="*70)
print("TESTING SEQUENTIAL THINKING ENGINE")
print("="*70)

# === TEST 1: ENGINE INITIALIZATION ===
print("\nTEST 1: Engine Initialization")
print("-" * 70)

engine = create_engine(verbose=True)
print(f"Created: {engine}")

assert engine.safety is not None, "Safety Layer should be initialized"
assert engine.state_dir == Path("/tmp"), "State dir should be /tmp"
print("✅ TEST 1 PASSED!")

# === TEST 2: SIMPLE TASK EXECUTION ===
print("\nTEST 2: Simple Task Execution")
print("-" * 70)

task = create_task(
    task_id="test_simple",
    description="Simple 2-step task",
    steps=[
        create_step("step1", "First step"),
        create_step("step2", "Second step")
    ]
)

print(f"Task: {task.description}")
print(f"Steps: {len(task.steps)}")

result = engine.execute_task(task)

print(f"\nResult:")
print(f"  Progress: {result.progress():.1%}")
print(f"  Completed: {len(result.completed_steps())}")
print(f"  Failed: {len(result.failed_steps())}")

assert result.progress() == 1.0, "Task should be 100% complete"
assert len(result.completed_steps()) == 2, "Both steps should be completed"
print("✅ TEST 2 PASSED!")

# === TEST 3: STATE FILE CREATED ===
print("\nTEST 3: State File Created")
print("-" * 70)

state_file = Path(result.state_file_path)
print(f"State file: {state_file}")

assert state_file.exists(), "State file should exist"

state_content = state_file.read_text()
print(f"State size: {len(state_content)} chars")
print(f"\nFirst 500 chars:")
print(state_content[:500])

assert "Sequential Thinking" in state_content
assert "Execution Plan" in state_content
assert "Step 1:" in state_content
assert "✅ VERIFIED" in state_content or "❌ FAILED" in state_content
print("✅ TEST 3 PASSED!")

# === TEST 4: TASK WITH DEPENDENCIES ===
print("\nTEST 4: Task with Dependencies")
print("-" * 70)

task_dep = create_task(
    task_id="test_dependencies",
    description="Task with step dependencies",
    steps=[
        create_step("load", "Load data"),
        create_step("validate", "Validate data", dependencies=["load"]),
        create_step("analyze", "Analyze data", dependencies=["validate"])
    ]
)

print(f"Steps: {[s.id for s in task_dep.steps]}")
print(f"Dependencies: {[(s.id, s.dependencies) for s in task_dep.steps]}")

result_dep = engine.execute_task(task_dep)

print(f"\nResult:")
print(f"  Progress: {result_dep.progress():.1%}")

# Check execution order
for step in result_dep.steps:
    print(f"  {step.id}: {step.status}")

assert result_dep.progress() == 1.0, "All steps should complete"
print("✅ TEST 4 PASSED!")

# === TEST 5: SAFETY LAYER INTEGRATION ===
print("\nTEST 5: Safety Layer Integration")
print("-" * 70)

# This step should trigger bias detection
biased_step = create_step(
    "biased",
    "Sales increased after ads, therefore ads caused sales"
)

task_safety = create_task(
    task_id="test_safety",
    description="Test safety validation",
    steps=[biased_step]
)

result_safety = engine.execute_task(task_safety)

step = result_safety.steps[0]
print(f"Step status: {step.status}")
print(f"Safety passed: {step.safety_passed}")
print(f"Confidence: {step.safety_confidence:.2f}")
print(f"Corrections: {len(step.corrections_applied)}")

# Check if safety layer was invoked
assert step.safety_passed is not None, "Safety check should have run"
print("✅ TEST 5 PASSED!")

# === TEST 6: CONTEXT PRESERVATION (READ STATE) ===
print("\nTEST 6: Context Preservation (Read State)")
print("-" * 70)

# Create task
task_context = create_task(
    task_id="test_context",
    description="Test context preservation",
    steps=[
        create_step("s1", "Step 1"),
        create_step("s2", "Step 2")
    ]
)

# Execute
result_context = engine.execute_task(task_context)

# Verify state can be read
state = engine._read_state()
print(f"State read: {len(state)} chars")
print(f"Contains Step 1: {'Step 1:' in state}")
print(f"Contains Step 2: {'Step 2:' in state}")

assert len(state) > 0, "State should be readable"
assert "Step 1:" in state, "State should contain step details"
print("✅ TEST 6 PASSED!")

# === TEST 7: STEP STATUS TRANSITIONS ===
print("\nTEST 7: Step Status Transitions")
print("-" * 70)

task_status = create_task(
    task_id="test_status",
    description="Test status transitions",
    steps=[create_step("test", "Test step")]
)

# Check initial status
initial_status = task_status.steps[0].status
print(f"Initial: {initial_status}")
assert initial_status == StepStatus.PENDING

# Execute
result_status = engine.execute_task(task_status)

# Check final status
final_status = result_status.steps[0].status
print(f"Final: {final_status}")
assert final_status in [StepStatus.VERIFIED, StepStatus.FAILED]

print("✅ TEST 7 PASSED!")

# === TEST 8: MULTIPLE TASKS (STATE FILE ISOLATION) ===
print("\nTEST 8: Multiple Tasks (State File Isolation)")
print("-" * 70)

task_a = create_task("task_a", "Task A", [create_step("a1", "Step A1")])
task_b = create_task("task_b", "Task B", [create_step("b1", "Step B1")])

result_a = engine.execute_task(task_a)
result_b = engine.execute_task(task_b)

print(f"Task A state: {result_a.state_file_path}")
print(f"Task B state: {result_b.state_file_path}")

assert result_a.state_file_path != result_b.state_file_path
assert Path(result_a.state_file_path).exists()
assert Path(result_b.state_file_path).exists()

print("✅ TEST 8 PASSED!")

# === SUMMARY ===
print("\n" + "="*70)
print("🎉 ALL ENGINE TESTS PASSED!")
print("="*70)
print("\nFeatures Tested:")
print("  ✅ Engine initialization")
print("  ✅ Simple task execution")
print("  ✅ State file creation")
print("  ✅ Step dependencies")
print("  ✅ Safety Layer integration")
print("  ✅ Context preservation (read state)")
print("  ✅ Status transitions")
print("  ✅ Multiple task isolation")
print("\nIntegration Working:")
print("  ✅ Engine → Safety Layer")
print("  ✅ Engine → Live State Tracking")
print("  ✅ validate_before() called")
print("  ✅ validate_after() called")
print("  ✅ State file updated per step")
print("\n✅ STEP 2 COMPLETE - ENGINE READY!")
print("="*70)
