import re
from pathlib import Path

from core.plan_runtime_bridge import LEGACY_RUNTIME_KEYS

TARGET_FILES = [
    Path("core/layers/output.py"),
    Path("core/orchestrator_sync_flow_utils.py"),
    Path("core/orchestrator_stream_flow_utils.py"),
    Path("core/orchestrator_tool_execution_sync_utils.py"),
]

WRITE_RE = re.compile(
    r'\b[A-Za-z_][A-Za-z0-9_]*\s*\[\s*"(?P<key>_[A-Za-z0-9_]+)"\s*\]\s*=\s*(?!=)'
)
READ_RE = re.compile(
    r'\b[A-Za-z_][A-Za-z0-9_]*\s*\.get\(\s*"(?P<key>_[A-Za-z0-9_]+)"\s*[,)]'
)
SUBSCRIPT_READ_RE = re.compile(
    r'\b[A-Za-z_][A-Za-z0-9_]*\s*\[\s*"(?P<key>_[A-Za-z0-9_]+)"\s*\]'
)
POP_RE = re.compile(
    r'\b[A-Za-z_][A-Za-z0-9_]*\s*\.pop\(\s*"(?P<key>_[A-Za-z0-9_]+)"\s*[,)]'
)


def test_no_direct_legacy_runtime_reads_or_writes_in_core_flow_files():
    violations = []
    for rel in TARGET_FILES:
        text = rel.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for regex, mode in (
                (WRITE_RE, "write"),
                (READ_RE, "read:get"),
                (SUBSCRIPT_READ_RE, "read:subscript"),
                (POP_RE, "read:pop"),
            ):
                m = regex.search(line)
                if not m:
                    continue
                key = m.group("key")
                if key in LEGACY_RUNTIME_KEYS:
                    violations.append(f"{rel}:{lineno}:{mode}:{key}")

    assert not violations, "Direct legacy runtime access detected:\n" + "\n".join(violations)
