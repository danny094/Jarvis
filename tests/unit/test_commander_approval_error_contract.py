from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding='utf-8')


def test_approval_get_not_found_includes_explicit_error_code():
    src = _read('adapters/admin-api/commander_api/operations.py')
    assert "HTTPException(404, f\"Approval '{approval_id}' not found\")" in src
    assert 'error_code="not_found"' in src
    assert 'details={"approval_id": approval_id}' in src


def test_approval_approve_reject_not_found_include_error_contract_details():
    src = _read('adapters/admin-api/commander_api/operations.py')
    assert 'details={"approved": False, "approval_id": approval_id}' in src
    assert 'details={"rejected": False, "approval_id": approval_id}' in src
    assert src.count('error_code="not_found"') >= 3
