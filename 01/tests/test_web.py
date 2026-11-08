"""Stock GradioUI wiring and the one-button VS Code launch configuration."""

import asyncio
import json
from pathlib import Path

import gradio as gr
import pytest
from smolagents.memory import FinalAnswerStep

from marketplace_agent import web

ROOT = Path(__file__).resolve().parents[2]


class FakeAgent:
    name = "marketplace_agent"
    description = "Test agent"

    def __init__(self):
        self.requests = []
        self.cleared = False

    def run(self, task, **kwargs):
        self.requests.append((task, kwargs))
        yield FinalAnswerStep(output="Actual agent response")

    def clear(self):
        self.cleared = True


@pytest.fixture
def interface(monkeypatch):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    # The stock UI's mascot is irrelevant to offline behavior tests.
    monkeypatch.setattr(gr.Chatbot, "serve_static_file", lambda *args: None)
    agent = FakeAgent()

    async def create():
        return web.create_ui(agent=agent)

    # Gradio's sync lock helpers create event loops when none is running.
    with asyncio.Runner() as runner:
        demo = runner.run(create())
        yield demo, agent
        demo.close(verbose=False)


def test_stock_ui_calls_agent_and_displays_its_real_final_response(interface):
    demo, agent = interface
    assert isinstance(demo, gr.ChatInterface)
    events = list(demo.fn("Najdi iPhone.", []))
    assert "Actual agent response" in events[-1][-1].content
    assert agent.requests == [
        (
            "Najdi iPhone.",
            {
                "images": None,
                "stream": True,
                "reset": False,
                "additional_args": None,
            },
        )
    ]


def test_new_chat_and_clear_are_connected_to_memory_reset(interface):
    demo, agent = interface
    reset_callbacks = [function.fn for function in demo.fns.values() if function.fn == agent.clear]
    assert len(reset_callbacks) == 2
    reset_callbacks[0]()
    assert agent.cleared


def test_web_launch_is_local_and_does_not_enable_a_public_share(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_PORT", "8088")
    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    observed = {}

    class Demo:
        def launch(self, **kwargs):
            observed.update(kwargs)

    monkeypatch.setattr(web, "create_ui", lambda settings: Demo())
    web.main()
    assert observed["share"] is False
    assert observed["ssr_mode"] is False
    assert observed["server_port"] == 8088
    assert observed["server_name"] == "127.0.0.1"


def test_vscode_start_button_runs_the_real_compose_project():
    launch = json.loads((ROOT / ".vscode/launch.json").read_text())["configurations"][0]
    config = json.loads((ROOT / ".vscode/tasks.json").read_text())
    tasks = {task["label"]: task for task in config["tasks"]}
    start = tasks[launch["preLaunchTask"]]
    stop = tasks[launch["postDebugTask"]]
    assert start["command"] == "docker"
    assert start["args"] == ["compose", "up", "-d", "--build", "--wait"]
    assert stop["args"] == ["compose", "stop"]
    assert config["options"]["cwd"] == "${workspaceFolder}/01"
    assert launch["url"] == "http://localhost:8080"
