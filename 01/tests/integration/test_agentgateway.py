"""Real pinned gateway with existing FastMCP tools and a local mock OpenAI API.

GATEWAY_DOCKER_TESTS=true uv run --locked pytest tests/integration/test_agentgateway.py
The default suite checks configuration/diagnostics without Docker or a real model.
"""

import asyncio
import copy
import json
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml
from fastmcp import Client

from marketplace_agent.agent import MarketplaceAgent
from marketplace_agent.config import Settings
from marketplace_agent.gateway_check import (
    SEARCH_TOOLS,
    check_llm,
    check_mcp,
    completion_request,
    validate_completion,
    validate_search,
)
from marketplace_agent.mcp.bazos_server import mcp as bazos_mcp

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config/agentgateway.yaml"
CONFIG = yaml.safe_load(CONFIG_PATH.read_text())
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text())
IMAGE = COMPOSE["services"]["agentgateway"]["image"]
TEST_MODEL = "stage04-local-test-model"
DOCKER = pytest.mark.skipif(
    os.getenv("GATEWAY_DOCKER_TESTS") != "true", reason="Set GATEWAY_DOCKER_TESTS=true"
)


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], cwd=ROOT, capture_output=True, text=True, timeout=180, check=check
    )


def test_configuration_has_two_targets_and_separate_listeners() -> None:
    assert set(COMPOSE["services"]) == {"app", "bazos-mcp", "sbazar-mcp", "agentgateway"}
    assert IMAGE.startswith("cr.agentgateway.dev/agentgateway:v1.7.0@sha256:")
    assert CONFIG["config"]["storage"]["mode"] == "readOnly"
    assert CONFIG["mcp"]["prefixMode"] == "always"
    assert CONFIG["mcp"]["failureMode"] == "failOpen"
    assert CONFIG["mcp"]["targets"] == [
        {"name": "bazos", "mcp": {"host": "http://bazos-mcp:8001/mcp"}},
        {"name": "sbazar", "mcp": {"host": "http://sbazar-mcp:8002/mcp"}},
    ]
    assert CONFIG["mcp"]["gateways"] != CONFIG["llm"]["gateways"]
    for service in ("bazos-mcp", "sbazar-mcp"):
        assert "ports" not in COMPOSE["services"][service]
    assert all(p.startswith("127.0.0.1:") for p in COMPOSE["services"]["agentgateway"]["ports"])


def test_llm_configuration_uses_only_the_environment_and_custom_completions() -> None:
    (model,) = CONFIG["llm"]["models"]
    assert model["name"] == "${UNSLOTH_MODEL}"
    assert model["provider"] == {"custom": {"formats": [{"type": "completions"}]}}
    assert model["params"] == {"baseUrl": "${UNSLOTH_BASE_URL}", "apiKey": "$UNSLOTH_API_KEY"}
    assert set(COMPOSE["services"]["agentgateway"]["environment"]) == {
        "UNSLOTH_BASE_URL",
        "UNSLOTH_MODEL",
        "UNSLOTH_API_KEY",
        "LLM_TIMEOUT",
    }
    assert all(v == "${LLM_TIMEOUT}s" for v in CONFIG["llm"]["policies"]["timeout"].values())
    assert "depends_on" not in COMPOSE["services"]["app"]
    assert all(
        dependency["restart"]
        for dependency in COMPOSE["services"]["agentgateway"]["depends_on"].values()
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"object": "chat.completion", "model": "remote-model", "choices": []},
        {"object": "chat.completion", "model": TEST_MODEL, "choices": []},
    ],
)
def test_diagnostics_reject_invalid_completion_or_wrong_model(payload: dict) -> None:
    with pytest.raises(ValueError):
        validate_completion(payload, TEST_MODEL)


def test_diagnostics_reject_invalid_search_response() -> None:
    with pytest.raises(ValueError):
        validate_search({"query": "test", "count": 1, "listings": []}, "test")


@pytest.fixture(scope="module")
def infrastructure(tmp_path_factory: pytest.TempPathFactory) -> Iterator:
    """Isolate test containers from the user's Compose services and Unsloth."""
    network = "stage04-test-" + uuid.uuid4().hex[:10]
    backend = network + "-backends"
    python_image = "marketplace-agent-stage04-tests:local"
    containers = []
    temp = tmp_path_factory.mktemp("gateway")
    docker("build", "--quiet", "--tag", python_image, ".")
    docker("network", "create", network)
    try:
        docker(
            "run",
            "--detach",
            "--name",
            backend,
            "--network",
            network,
            "--network-alias",
            "bazos-mcp",
            "--network-alias",
            "sbazar-mcp",
            "--volume",
            f"{ROOT / 'tests'}:/tests:ro",
            python_image,
            "python",
            "/tests/integration/mock_backends.py",
        )
        containers.append(backend)

        def start(config: dict | None = None, **environment: str) -> dict:
            name = network + "-gateway-" + str(len(containers))
            path = temp / f"{name}.yaml"
            path.write_text(yaml.safe_dump(config or CONFIG))
            env = {
                "UNSLOTH_BASE_URL": f"http://{backend}:8888/v1",
                "UNSLOTH_MODEL": TEST_MODEL,
                "UNSLOTH_API_KEY": "stage04-test-key",
                "LLM_TIMEOUT": "3",
            } | environment
            flags = [flag for key, value in env.items() for flag in ("--env", f"{key}={value}")]
            docker(
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                network,
                "--publish",
                "127.0.0.1::3000",
                "--publish",
                "127.0.0.1::3001",
                "--publish",
                "127.0.0.1::15021",
                "--volume",
                f"{path}:/config.yaml:ro",
                *flags,
                IMAGE,
                "--file",
                "/config.yaml",
            )
            containers.append(name)
            # Docker can return from detached run before Desktop populates host bindings.
            deadline = time.monotonic() + 10
            while True:
                ports = json.loads(docker("inspect", name).stdout)[0]["NetworkSettings"]["Ports"]
                if all(ports.get(f"{port}/tcp") for port in (3000, 3001, 15021)):
                    break
                if time.monotonic() >= deadline:
                    pytest.fail("Gateway host-port bindings were not assigned")
                time.sleep(0.05)
            urls = {
                "mcp": f"http://127.0.0.1:{ports['3000/tcp'][0]['HostPort']}/mcp",
                "llm": f"http://127.0.0.1:{ports['3001/tcp'][0]['HostPort']}/v1",
                "ready": f"http://127.0.0.1:{ports['15021/tcp'][0]['HostPort']}/healthz/ready",
            }
            with httpx.Client(timeout=1, trust_env=False) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        if client.get(urls["ready"]).status_code == 200:
                            return urls
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
            pytest.fail("Gateway not ready: " + docker("logs", name).stderr)

        urls = start()
        # Native readiness is independent of MCP; wait for the actual test upstreams too.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = docker(
                "exec",
                backend,
                "python",
                "-m",
                "marketplace_agent.mcp.healthcheck",
                "http://127.0.0.1:8002/mcp",
                check=False,
            )
            if result.returncode == 0:
                break
            time.sleep(0.1)
        else:
            pytest.fail("Fixture MCP server not ready: " + docker("logs", backend).stderr)
        yield start, urls, backend
    finally:
        for name in reversed(containers):
            docker("rm", "--force", name, check=False)
        docker("network", "rm", network, check=False)


@DOCKER
@pytest.mark.docker
def test_native_configuration_validation_and_rejection(tmp_path: Path) -> None:
    env = [
        "--env",
        "UNSLOTH_MODEL=" + TEST_MODEL,
        "--env",
        "UNSLOTH_BASE_URL=http://host.docker.internal:8888/v1",
        "--env",
        "UNSLOTH_API_KEY=",
        "--env",
        "LLM_TIMEOUT=120",
    ]
    result = docker(
        "run",
        "--rm",
        *env,
        "--volume",
        f"{CONFIG_PATH}:/config.yaml:ro",
        IMAGE,
        "--file",
        "/config.yaml",
        "--validate-only",
    )
    assert "Configuration is valid!" in result.stdout
    bad = tmp_path / "invalid.yaml"
    bad.write_text("mcp:\n  inventedProperty: true\n")
    result = docker(
        "run",
        "--rm",
        "--volume",
        f"{bad}:/config.yaml:ro",
        IMAGE,
        "--file",
        "/config.yaml",
        "--validate-only",
        check=False,
    )
    assert result.returncode != 0


@DOCKER
@pytest.mark.docker
def test_discovery_schemas_and_both_tool_invocations(infrastructure) -> None:
    _, urls, _ = infrastructure

    async def run() -> None:
        async with Client(urls["mcp"]) as client:
            discovered = {tool.name: tool for tool in await client.list_tools()}
            assert set(discovered) == set(SEARCH_TOOLS)
            async with Client(bazos_mcp) as original:
                original_tool = (await original.list_tools())[0]
            for name in SEARCH_TOOLS:
                assert discovered[name].inputSchema == original_tool.inputSchema
                assert discovered[name].outputSchema == original_tool.outputSchema
                result = await client.call_tool(
                    name,
                    {
                        "query": "test product",
                        "min_price": 4000,
                        "sort_by": "price_asc",
                        "limit": 1,
                    },
                )
                assert not result.is_error
                payload = result.structured_content
                validate_search(payload, "test product")
                assert payload["count"] == 1
                assert payload["listings"][0]["price"] == 4000
                marketplace = "bazos.cz" if name.startswith("bazos") else "sbazar.cz"
                assert marketplace in payload["listings"][0]["url"]

    asyncio.run(run())


@DOCKER
@pytest.mark.docker
def test_llm_routing_authentication_and_parameter_preservation(infrastructure) -> None:
    _, urls, _ = infrastructure
    request = completion_request(TEST_MODEL) | {
        "messages": [
            {"role": "system", "content": "Keep this message"},
            {"role": "user", "content": "Hello"},
        ],
        "temperature": 0.3,
        "top_p": 0.9,
        "seed": 42,
        "stop": ["END"],
        "top_k": 20,
        "min_p": 0.1,
    }
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.post(urls["llm"] + "/chat/completions", json=request)
        response.raise_for_status()
        payload = response.json()
        validate_completion(payload, TEST_MODEL)
        assert json.loads(payload["choices"][0]["message"]["content"]) == request
        models = client.get(urls["llm"] + "/models").json()["data"]
        assert [model["id"] for model in models] == [TEST_MODEL]
        response = client.post(
            urls["llm"] + "/chat/completions", json=request | {"model": "remote-cloud-model"}
        )
        assert response.status_code == 404


@DOCKER
@pytest.mark.docker
def test_unavailable_llm_keeps_mcp_available(infrastructure) -> None:
    start, _, backend = infrastructure
    urls = start(UNSLOTH_BASE_URL=f"http://{backend}:9/v1")
    response = httpx.post(
        urls["llm"] + "/chat/completions",
        json=completion_request(TEST_MODEL),
        timeout=10,
        trust_env=False,
    )
    assert response.status_code == 503
    assert asyncio.run(check_mcp(urls["mcp"]))


@DOCKER
@pytest.mark.docker
def test_unavailable_mcp_keeps_other_namespaced_tool_available(infrastructure) -> None:
    start, _, _ = infrastructure
    config = copy.deepcopy(CONFIG)
    config["mcp"]["targets"][1]["mcp"]["host"] = "http://sbazar-mcp:9/mcp"
    urls = start(config)

    async def run() -> None:
        async with Client(urls["mcp"], timeout=10) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools] == ["bazos_search_listings"]
            result = await client.call_tool(tools[0].name, {"query": "test product", "limit": 1})
            assert not result.is_error
            validate_search(result.structured_content, "test product")

    asyncio.run(run())


@DOCKER
@pytest.mark.docker
def test_configured_llm_timeout_and_authentication_failure(infrastructure) -> None:
    start, _, _ = infrastructure
    urls = start(LLM_TIMEOUT="0.2")
    request = completion_request(TEST_MODEL) | {"messages": [{"role": "user", "content": "slow"}]}
    response = httpx.post(
        urls["llm"] + "/chat/completions", json=request, timeout=10, trust_env=False
    )
    assert response.status_code == 504
    urls = start(UNSLOTH_API_KEY="wrong-test-key")
    response = httpx.post(
        urls["llm"] + "/chat/completions",
        json=completion_request(TEST_MODEL),
        timeout=10,
        trust_env=False,
    )
    assert response.status_code == 401


@DOCKER
@pytest.mark.docker
def test_llm_without_api_key_and_with_custom_base_path(infrastructure) -> None:
    start, _, backend = infrastructure
    urls = start(UNSLOTH_API_KEY="", UNSLOTH_BASE_URL=f"http://{backend}:8888/anonymous/v1")
    response = httpx.post(
        urls["llm"] + "/chat/completions",
        json=completion_request(TEST_MODEL),
        timeout=10,
        trust_env=False,
    )
    response.raise_for_status()
    validate_completion(response.json(), TEST_MODEL)


@DOCKER
@pytest.mark.docker
def test_agent_native_tool_cycle_with_real_gateway_and_fixture_marketplaces(infrastructure) -> None:
    """Real HTTP/MCP orchestration, with an explicitly mocked LLM and invented fixtures."""
    _, urls, _ = infrastructure

    settings = Settings(
        _env_file=None,
        unsloth_model=TEST_MODEL,
        llm_base_url=urls["llm"],
        agentgateway_url=urls["mcp"],
    )
    agent = MarketplaceAgent(settings)
    try:
        answer = agent.run("Search both sources for test product, from 1000 CZK, limit 3.")
        assert agent.tool_call_count == 2
        assert agent.last_results["searched_sources"] == ["Bazoš", "Sbazar"]
        assert agent.last_results["count"] == 3
        assert [item["price"] for item in agent.last_results["listings"]] == [4000, 4000, 12500]
        assert "Fixture search finished." in answer
        assert all(item["url"].startswith("https://") for item in agent.last_results["listings"])
    finally:
        agent.model.client.close()


@pytest.mark.live
@pytest.mark.skipif(os.getenv("UNSLOTH_LIVE_SMOKE") != "true", reason="Set UNSLOTH_LIVE_SMOKE=true")
def test_optional_live_unsloth() -> None:
    """Use actual settings; run inside Compose or override URLs for the host."""
    settings = Settings()
    assert asyncio.run(check_llm(settings, str(settings.llm_base_url)))
