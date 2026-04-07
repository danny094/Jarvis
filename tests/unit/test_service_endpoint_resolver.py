from unittest.mock import mock_open, patch

from utils.service_endpoint_resolver import (
    candidate_service_endpoints,
    default_service_endpoint,
    docker_default_gateway_endpoint,
    resolve_public_endpoint_host,
)


def test_default_service_endpoint_prefers_service_name_in_container():
    with patch("utils.service_endpoint_resolver.is_running_in_container", return_value=True):
        endpoint = default_service_endpoint("ollama", 11434)
    assert endpoint == "http://ollama:11434"


def test_default_service_endpoint_uses_loopback_outside_container():
    with patch("utils.service_endpoint_resolver.is_running_in_container", return_value=False):
        endpoint = default_service_endpoint("ollama", 11434)
    assert endpoint == "http://127.0.0.1:11434"


def test_docker_default_gateway_endpoint_parsing():
    route_content = (
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
    )
    with patch("builtins.open", mock_open(read_data=route_content)):
        endpoint = docker_default_gateway_endpoint(11434)
    assert endpoint == "http://172.18.0.1:11434"


def test_candidate_service_endpoints_use_service_and_dynamic_gateway_without_legacy_bridge():
    with patch("utils.service_endpoint_resolver.docker_default_gateway_endpoint", return_value="http://172.19.0.1:8420"):
        endpoints = candidate_service_endpoints(
            configured="",
            port=8420,
            service_name="jarvis-admin-api",
            prefer_container_service=True,
        )
    assert endpoints[0] == "http://jarvis-admin-api:8420"
    assert "http://172.19.0.1:8420" in endpoints
    assert "http://host.docker.internal:8420" in endpoints
    assert "http://172.17.0.1:8420" not in endpoints


def test_resolve_public_endpoint_host_prefers_configured_public_host():
    host = resolve_public_endpoint_host(
        configured_public_host="demo.local",
        host_ip="203.0.113.22",
    )
    assert host == "demo.local"


def test_resolve_public_endpoint_host_uses_specific_host_ip_without_config():
    host = resolve_public_endpoint_host(
        configured_public_host="",
        host_ip="203.0.113.22",
    )
    assert host == "203.0.113.22"


def test_resolve_public_endpoint_host_avoids_generic_bind_ips():
    host = resolve_public_endpoint_host(
        configured_public_host="",
        host_ip="0.0.0.0",
    )
    assert host == ""
