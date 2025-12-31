# Critical Rettungs-Tests for Jarvis Maintenance
Recommended by ChatGPT - 2025-12-31

These are NOT normal unit tests.
These are SYSTEM INVARIANTS that prevent catastrophic failures.

---

## Top 5 IMMEDIATE Priority

1. test_maintenance_is_lossless_for_facts
2. test_graph_has_no_self_loops
3. test_merge_threshold_respected  
4. test_no_cross_persona_merges
5. test_maintenance_dry_run_has_no_side_effects

Your: Airbag + ABS + ESP + Seatbelt + Safety Features

---

## Category 1: Data Loss Prevention

### test_maintenance_is_lossless_for_facts
Prevents: Silent knowledge loss
Test: Hash facts before/after, verify all exist or were merged
Why: Without this, maintenance can silently delete knowledge

### test_no_fact_changes_without_reason
Prevents: Semantic drift, silent rewrites
Test: Fact text immutable unless merged
Why: Prevents AI hallucinations disguised as optimization

### test_maintenance_is_idempotent_per_stage  
Prevents: Non-deterministic behavior
Test: Run each substep 3x, should be stable
Why: Each step must be individually stable

---

## Category 2: Graph Integrity

### test_graph_has_no_self_loops
Prevents: Infinite loops, exploding traversals
Test: No edge where source == target
Why: Self-loops crash semantic search

### test_graph_is_connected_or_intentionally_disconnected
Prevents: Orphaned facts, unfindable memories
Test: No components < 3 nodes
Why: Prevents facts from becoming unreachable

### test_graph_cluster_count_stable
Prevents: Sudden knowledge reorganization
Test: Cluster count changes < 20%
Why: Structure should evolve gradually

---

## Category 3: AI-Specific Traps

### test_embedding_similarity_not_inverted
Prevents: False merges, knowledge corruption
Test: Similar facts have higher similarity
Why: Wrong similarities = wrong merges = data corruption

### test_merge_threshold_respected
Prevents: Over-merging, data loss
Test: Similarity below threshold = no merge
Why: Threshold is the firewall against data loss

### test_no_cross_persona_merges
Prevents: Privacy leaks, data contamination
Test: No memory sharing between personas
Why: Prevents persona leak disasters

---

## Category 4: Safety & Meta

### test_maintenance_dry_run_has_no_side_effects
Prevents: Accidental writes
Test: DB hash unchanged after dry-run
Why: Dry-run MUST be truly read-only

### test_maintenance_logs_actions
Prevents: Debug hell, untraceable changes
Test: Every merge logged with reason
Why: Cannot debug what you cannot see

### test_maintenance_fails_loud_on_schema_mismatch
Prevents: Silent corruption
Test: Missing column = immediate abort
Why: Schema drift should fail fast, not corrupt silently

---

## Implementation Strategy

Week 1 (NOW): Top 5 tests (4-6 hours, prevents 90% of catastrophes)
Week 2: Category 1 & 2 (3-4 hours, full data integrity)
Week 3+: Category 3 & 4 (2-3 hours, AI-specific safety)

---

## What These Tests Protect Against

- AI hallucinations
- Refactoring accidents  
- Data corruption
- 3am debugging sessions
- Silent knowledge loss
- Privacy leaks
- Infinite loops

---

Source: ChatGPT analysis
Date: 2025-12-31
Status: Recommended for immediate implementation
