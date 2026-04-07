from container_commander.runtime_hardware_blueprint import _service_file_map, runtime_hardware_dockerfile


def test_runtime_hardware_dockerfile_embeds_service_sources():
    dockerfile = runtime_hardware_dockerfile()

    assert "FROM python:3.12-slim" in dockerfile
    assert 'ENV RUNTIME_HARDWARE_WRITE_SCRIPT_B64_000=' in dockerfile
    assert 'RUN python3 -c "import base64, os; exec(base64.b64decode(' in dockerfile
    assert 'CMD ["uvicorn", "main:app"' in dockerfile
    assert "/app/requirements.txt" in dockerfile
    assert "EXPOSE 8420" in dockerfile


def test_runtime_hardware_dockerfile_stays_below_line_limit():
    dockerfile = runtime_hardware_dockerfile()
    max_line_length = max(len(line) for line in dockerfile.splitlines())

    assert max_line_length < 65535


def test_runtime_hardware_blueprint_tracks_storage_discovery_module():
    file_map = _service_file_map()

    assert (
        file_map["runtime_hardware/connectors/container_storage_discovery.py"]
        == "runtime_hardware/connectors/container_storage_discovery.py"
    )


def test_runtime_hardware_blueprint_tracks_container_display_module():
    file_map = _service_file_map()

    assert (
        file_map["runtime_hardware/connectors/container_display.py"]
        == "runtime_hardware/connectors/container_display.py"
    )
