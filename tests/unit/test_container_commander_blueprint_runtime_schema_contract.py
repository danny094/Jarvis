from pathlib import Path


def _read(path: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / path).read_text(encoding="utf-8")


def test_models_blueprint_exposes_runtime_schema_fields():
    src = _read("container_commander/models.py")
    assert "ports: List[str]" in src
    assert "runtime: str" in src
    assert "devices: List[str]" in src
    assert "hardware_intents: List[HardwareIntent]" in src
    assert "environment: Dict[str, str]" in src
    assert "healthcheck: Dict[str, Any]" in src
    assert "pre_start_exec: Optional[PreStartExec]" in src
    assert "cap_add: List[str]" in src
    assert "security_opt: List[str]" in src
    assert "cap_drop: List[str]" in src
    assert "privileged: bool" in src
    assert "read_only_rootfs: bool" in src
    assert "shm_size: str" in src
    assert "ipc_mode: str" in src


def test_blueprint_store_persists_runtime_schema_fields():
    src = _read("container_commander/blueprint_store.py")
    assert "ports_json TEXT DEFAULT '[]'" in src
    assert "runtime TEXT DEFAULT ''" in src
    assert "devices_json TEXT DEFAULT '[]'" in src
    assert "hardware_intents_json TEXT DEFAULT '[]'" in src
    assert "environment_json TEXT DEFAULT '{}'" in src
    assert "healthcheck_json TEXT DEFAULT '{}'" in src
    assert "pre_start_exec_json TEXT DEFAULT '{}'" in src
    assert "cap_add_json TEXT DEFAULT '[]'" in src
    assert "security_opt_json TEXT DEFAULT '[]'" in src
    assert "cap_drop_json TEXT DEFAULT '[]'" in src
    assert "privileged INTEGER DEFAULT 0" in src
    assert "read_only_rootfs INTEGER DEFAULT 0" in src
    assert "shm_size TEXT DEFAULT ''" in src
    assert "ipc_mode TEXT DEFAULT ''" in src
    assert "ALTER TABLE blueprints ADD COLUMN ports_json TEXT DEFAULT '[]'" in src
    assert "ALTER TABLE blueprints ADD COLUMN runtime TEXT DEFAULT ''" in src
    assert "ALTER TABLE blueprints ADD COLUMN hardware_intents_json TEXT DEFAULT '[]'" in src
    assert "ALTER TABLE blueprints ADD COLUMN pre_start_exec_json TEXT DEFAULT '{}'" in src
    assert "ALTER TABLE blueprints ADD COLUMN security_opt_json TEXT DEFAULT '[]'" in src
    assert "ALTER TABLE blueprints ADD COLUMN cap_drop_json TEXT DEFAULT '[]'" in src
    assert "ALTER TABLE blueprints ADD COLUMN privileged INTEGER DEFAULT 0" in src
    assert "ALTER TABLE blueprints ADD COLUMN read_only_rootfs INTEGER DEFAULT 0" in src
    assert "ALTER TABLE blueprints ADD COLUMN ipc_mode TEXT DEFAULT ''" in src
    assert "\"ports_json\": json.dumps(bp.ports)" in src
    assert "\"runtime\": bp.runtime" in src
    assert "\"hardware_intents_json\": json.dumps([intent.model_dump() for intent in bp.hardware_intents])" in src
    assert "\"pre_start_exec_json\": bp.pre_start_exec.model_dump_json() if bp.pre_start_exec else \"{}\"" in src
    assert "\"security_opt_json\": json.dumps(bp.security_opt)" in src
    assert "\"cap_drop_json\": json.dumps(bp.cap_drop)" in src
    assert "\"privileged\": 1 if bp.privileged else 0" in src
    assert "\"ipc_mode\": bp.ipc_mode" in src


def test_engine_wires_runtime_fields_into_docker_run_contract():
    src = _read("container_commander/engine.py")
    assert "def _build_port_bindings" in src
    assert "def _build_healthcheck_config" in src
    assert "def _run_pre_start_exec" in src
    assert "port_bindings = _build_port_bindings(bp.ports)" in src
    assert "healthcheck = _build_healthcheck_config(bp.healthcheck)" in src
    assert "_run_pre_start_exec(bp, image_tag, env_vars)" in src
    assert "run_kwargs[\"ports\"] = port_bindings" in src
    assert "run_kwargs[\"runtime\"] = bp.runtime" in src
    assert "run_kwargs[\"devices\"] = list(bp.devices)" in src
    assert "run_kwargs[\"cap_add\"] = list(bp.cap_add)" in src
    assert "run_kwargs[\"security_opt\"] = list(bp.security_opt)" in src
    assert "run_kwargs[\"cap_drop\"] = list(bp.cap_drop)" in src
    assert "run_kwargs[\"privileged\"] = True" in src
    assert "run_kwargs[\"read_only\"] = True" in src
    assert "run_kwargs[\"shm_size\"] = bp.shm_size" in src
    assert "run_kwargs[\"ipc_mode\"] = bp.ipc_mode" in src
    assert "run_kwargs[\"healthcheck\"] = healthcheck" in src


def test_mcp_blueprint_create_accepts_runtime_fields():
    src = _read("container_commander/mcp_tools.py")
    assert "\"ports\":" in src
    assert "\"runtime\":" in src
    assert "\"devices\":" in src
    assert "\"hardware_intents\":" in src
    assert "\"environment\":" in src
    assert "\"healthcheck\":" in src
    assert "\"pre_start_exec\":" in src
    assert "\"cap_add\":" in src
    assert "\"security_opt\":" in src
    assert "\"cap_drop\":" in src
    assert "\"privileged\":" in src
    assert "\"read_only_rootfs\":" in src
    assert "\"shm_size\":" in src
    assert "\"ipc_mode\":" in src
    assert "ports=args.get(\"ports\", [])" in src
    assert "runtime=args.get(\"runtime\", \"\")" in src
    assert "devices=args.get(\"devices\", [])" in src
    assert "hardware_intents=args.get(\"hardware_intents\", [])" in src
    assert "pre_start_exec=args.get(\"pre_start_exec\")" in src
    assert "security_opt=args.get(\"security_opt\", [])" in src
    assert "cap_drop=args.get(\"cap_drop\", [])" in src
    assert "privileged=bool(args.get(\"privileged\", False))" in src
    assert "read_only_rootfs=bool(args.get(\"read_only_rootfs\", False))" in src
    assert "ipc_mode=args.get(\"ipc_mode\", \"\")" in src
