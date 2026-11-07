"""Small dependency-free command line interface for project diagnostics."""

import argparse
import logging
import platform
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from marketplace_agent import APP_NAME, __version__
from marketplace_agent.config import Settings
from marketplace_agent.health import serve

FEATURE_STATUS = (
    "Marketplace search, MCP servers, and AI agent functionality are not implemented yet."
)


def _doctor(settings: Settings) -> int:
    """Check local initialization; future service availability is irrelevant."""
    print(f"OK configuration: environment={settings.app_env}, mode={settings.marketplace_mode}")
    if sys.version_info < (3, 12):  # noqa: UP036 - doctor explicitly checks the runtime.
        print(
            f"ERROR Python {platform.python_version()}: Python 3.12+ is required.", file=sys.stderr
        )
        return 1
    print(f"OK Python {platform.python_version()}")
    print(f"OK package: {APP_NAME} {__version__}")
    print("Future LLM, agentgateway, and MCP connections are not checked at this stage.")
    print(FEATURE_STATUS)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a CLI command and return its exit status."""
    parser = argparse.ArgumentParser(
        prog="marketplace-agent", description=APP_NAME, epilog=FEATURE_STATUS
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version", help="Display the application name and version.")
    commands.add_parser(
        "doctor", help="Validate configuration, Python, and package initialization."
    )
    commands.add_parser("serve", help="Run the development health endpoint; no agent runs yet.")
    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"{APP_NAME} {__version__}")
        return 0

    try:
        settings = Settings()
    except ValidationError as exc:
        print("Invalid application configuration:", file=sys.stderr)
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            print(f"  {location}: {error['msg']}", file=sys.stderr)
        return 2

    if args.command == "doctor":
        return _doctor(settings)

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger(__name__).info(FEATURE_STATUS)
    try:
        serve(settings)
    except OSError as exc:
        print(f"Could not start the health server: {exc}", file=sys.stderr)
        return 1
    return 0
