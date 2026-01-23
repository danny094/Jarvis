"""
Quick test for Sequential Thinking types
"""

import sys
sys.path.insert(0, "/DATA/AppData/MCP/Jarvis/Jarvis")

from modules.sequential_thinking.types import (
    Step, Task, Result,
    StepStatus, StepType,
    create_step, create_task,
    validate_step, validate_task
)
from datetime import datetime

print("\n" + "="*70)
print("TESTING SEQUENTIAL THINKING TYPES")
print("="*70)

# === TEST 1: CREATE STEP ===
print("\nTEST 1: Create Step")
print("-" * 70)

step1 = create_step(
    step_id="step_1",
    query="Load CSV data from /data/sales.csv",
    context={"file_path": "/data/sales.csv"}
)

print(f"Created: {step1}")
print(f"  Status: {step1.status}")
print(f"  Type: {step1.step_type}")
print(f"  Safety required: {step1.requires_safety_check}")

assert step1.status == StepStatus.PENDING
assert step1.step_type == StepType.NORMAL
print("✅ TEST 1 PASSED!")

# === TEST 2: STEP WITH DEPENDENCIES ===
print("\nTEST 2: Step with Dependencies")
print("-" * 70)

step2 = create_step(
    step_id="step_2",
    query="Validate data quality",
    dependencies=["step_1"]
)

print(f"Created: {step2}")
print(f"  Dependencies: {step2.dependencies}")

# Not ready yet (step_1 not completed)
assert not step2.is_ready(set())
print("  Not ready (dependencies not met)")

# Ready when step_1 is complete
assert step2.is_ready({"step_1"})
print("  Ready when dependencies met")
print("✅ TEST 2 PASSED!")

# === TEST 3: CREATE RESULT ===
print("\nTEST 3: Create Result")
print("-" * 70)

result = Result(
    output="Loaded 12,543 rows successfully",
    reasoning="Used pandas read_csv with UTF-8 encoding",
    confidence=1.0
)

print(f"Created: {result}")
print(f"  Summary: {result.summary()}")
print(f"  Validated: {result.validated}")

assert result.confidence == 1.0
assert not result.validated  # Not yet validated by Safety Layer!
print("✅ TEST 3 PASSED!")

# === TEST 4: CREATE TASK ===
print("\nTEST 4: Create Task")
print("-" * 70)

task = create_task(
    task_id="task_1",
    description="Analyze Q4 sales data",
    steps=[step1, step2]
)

print(f"Created: {task}")
print(f"  Steps: {len(task.steps)}")
print(f"  Progress: {task.progress():.1%}")
print(f"  Completed: {len(task.completed_steps())}")

assert len(task.steps) == 2
assert task.progress() == 0.0  # No steps completed yet
print("✅ TEST 4 PASSED!")

# === TEST 5: STEP STATUS TRANSITIONS ===
print("\nTEST 5: Step Status Transitions")
print("-" * 70)

step3 = create_step("step_3", "Test step")

print(f"Initial status: {step3.status}")
assert step3.status == StepStatus.PENDING

# Simulate execution
step3.status = StepStatus.RUNNING
step3.started_at = datetime.now()
print(f"Started: {step3.status}")

# Add result
step3.result = Result(
    output="Test output",
    reasoning="Test reasoning",
    confidence=0.95
)

# Safety Layer validates
step3.safety_passed = True
step3.safety_confidence = 0.95
step3.status = StepStatus.VERIFIED
step3.completed_at = datetime.now()

print(f"Completed: {step3.status}")
print(f"  Safety passed: {step3.safety_passed}")
print(f"  Duration: {step3.duration():.3f}s")

assert step3.status == StepStatus.VERIFIED
assert step3.duration() is not None
print("✅ TEST 5 PASSED!")

# === TEST 6: VALIDATION ===
print("\nTEST 6: Step Validation")
print("-" * 70)

# Valid step
errors = validate_step(step1)
print(f"Valid step errors: {len(errors)}")
assert len(errors) == 0

# Invalid step (no ID)
invalid_step = Step(id="", query="Test")
errors = validate_step(invalid_step)
print(f"Invalid step errors: {len(errors)}")
assert len(errors) > 0
print(f"  Errors: {errors}")
print("✅ TEST 6 PASSED!")

# === TEST 7: TASK VALIDATION ===
print("\nTEST 7: Task Validation")
print("-" * 70)

# Valid task
errors = validate_task(task)
print(f"Valid task errors: {len(errors)}")
assert len(errors) == 0

# Invalid task (duplicate IDs)
step_dup = create_step("step_1", "Duplicate ID")
task_invalid = create_task("task_2", "Invalid", [step1, step_dup])
errors = validate_task(task_invalid)
print(f"Invalid task errors: {len(errors)}")
assert len(errors) > 0
print(f"  Errors: {errors}")
print("✅ TEST 7 PASSED!")

# === TEST 8: TASK PROGRESS TRACKING ===
print("\nTEST 8: Task Progress Tracking")
print("-" * 70)

task2 = create_task("progress_test", "Test progress", [
    create_step("s1", "Step 1"),
    create_step("s2", "Step 2"),
    create_step("s3", "Step 3"),
    create_step("s4", "Step 4"),
])

print(f"Initial progress: {task2.progress():.1%}")
assert task2.progress() == 0.0

# Mark 2 steps as verified
task2.steps[0].status = StepStatus.VERIFIED
task2.steps[1].status = StepStatus.VERIFIED

print(f"After 2 steps: {task2.progress():.1%}")
assert task2.progress() == 0.5

# Mark all as verified
for step in task2.steps:
    step.status = StepStatus.VERIFIED

print(f"All complete: {task2.progress():.1%}")
assert task2.progress() == 1.0
print("✅ TEST 8 PASSED!")

# === SUMMARY ===
print("\n" + "="*70)
print("🎉 ALL TYPES TESTS PASSED!")
print("="*70)
print("\nTypes Created:")
print("  ✅ Step - atomic unit of reasoning")
print("  ✅ Result - output from a step")
print("  ✅ Task - container for multiple steps")
print("  ✅ StepStatus - PENDING/RUNNING/VERIFIED/FAILED")
print("  ✅ StepType - NORMAL/GATE/VALIDATION/MITIGATION")
print("\nFeatures Working:")
print("  ✅ Step creation with dependencies")
print("  ✅ Result with confidence scoring")
print("  ✅ Task with progress tracking")
print("  ✅ Status transitions")
print("  ✅ Validation (structure, not logic)")
print("  ✅ Helper functions")
print("\n✅ STEP 1 COMPLETE - TYPES READY!")
print("="*70)
