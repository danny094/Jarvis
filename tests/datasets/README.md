# TRION Test Dataset

Schema-validated YAML test cases for the TRION AI pipeline.

## Structure

```
tests/datasets/
├── schema/
│   └── test_case.schema.json   ← JSON Schema (draft-07)
├── cases/
│   └── core_phase0_5.yaml      ← Core cases: Phase 0–5 + cross-phase memory
└── README.md                   ← This file
```

## Test Case Fields

| Field         | Required | Type                       | Description                                      |
|---------------|----------|----------------------------|--------------------------------------------------|
| `id`          | yes      | slug string                | Unique identifier (`a-z0-9_-`)                   |
| `phase`       | yes      | int or string              | Phase number (0-5) or `"cross"` for cross-phase  |
| `title`       | yes      | string (≥5 chars)          | Human-readable test title                        |
| `mode`        | yes      | `sync`/`stream`/`both`     | Execution mode (`both` runs sync AND stream)     |
| `input`       | yes      | object (requires `prompt`) | Test input specification                         |
| `expected`    | yes      | object                     | Assertions: contains, not_contains, markers      |
| `tags`        | yes      | list of strings (≥1)       | Filter tags (e.g. `smoke`, `phase2`)             |
| `description` | no       | string                     | Longer description of what is being tested       |
| `skip_reason` | no       | string                     | If present, test is skipped with this reason     |

### `input` sub-fields

| Field             | Required | Type   | Description                            |
|-------------------|----------|--------|----------------------------------------|
| `prompt`          | yes      | string | User prompt (≥2 chars)                 |
| `conversation_id` | no       | string | Conversation context identifier        |
| `extra`           | no       | object | Extra key-value pairs for the provider |

### `expected` sub-fields

| Field          | Required | Type           | Description                                      |
|----------------|----------|----------------|--------------------------------------------------|
| `contains`     | no       | list of string | Substrings that MUST appear in response           |
| `not_contains` | no       | list of string | Substrings that MUST NOT appear in response       |
| `markers`      | no       | object         | Expected context marker values (exact match)     |
| `golden_key`   | no       | string         | Filename base for golden snapshot comparison     |

## Validation

```bash
python tools/validate_test_dataset.py
# exits 0 on success, non-zero on schema/format errors
```

## Adding New Cases

1. Add entries to an existing YAML file or create a new file in `tests/datasets/cases/`.
2. Run the validator to check the schema.
3. Reference cases in E2E tests via `load_dataset_cases(tag="your_tag")`.

## Tag Conventions

| Tag             | Meaning                                      |
|-----------------|----------------------------------------------|
| `smoke`         | Fast sanity check, always run in quick gate  |
| `phaseN`        | Phase-specific (phase0 … phase5)             |
| `basic`         | Trivial correctness check                    |
| `stream`        | Stream-mode specific                         |
| `dedup`         | Deduplication invariant                      |
| `single_truth`  | Single Truth Channel                         |
| `typedstate`    | TypedState V1 rendering                      |
| `recovery`      | Container restart recovery                   |
| `graph_hygiene` | Phase 5 graph hygiene                        |
| `memory`        | Memory roundtrip                             |
| `fail_closed`   | Fail-closed safety behavior                  |
| `invariant`     | Hard invariant (must not break)              |
