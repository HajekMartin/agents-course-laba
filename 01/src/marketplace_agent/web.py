"""The stock smolagents GradioUI; no custom frontend or chat API."""

from smolagents import GradioUI

from marketplace_agent.agent import MarketplaceAgent
from marketplace_agent.config import Settings


def create_ui(settings: Settings | None = None, *, agent=None):
    agent = agent or MarketplaceAgent(settings or Settings())
    demo = GradioUI(agent, reset_agent_memory=False).create_app()
    with demo:
        demo.chatbot.clear(agent.clear, queue=False)
        demo.new_chat_button.click(agent.clear, queue=False)
    return demo


def main():
    settings = Settings()
    create_ui(settings).launch(
        server_name=settings.app_host,
        server_port=settings.app_port,
        share=False,
        ssr_mode=False,
        show_error=True,
    )
