# src/__main__.py
import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from typing import List

import anyio

# Rich imports
from rich import print
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from mcpcli.chat_handler import handle_chat_mode
from mcpcli.config import load_config
from mcpcli.messages.send_ping import send_ping
from mcpcli.messages.send_prompts import send_prompts_list
from mcpcli.messages.send_resources import send_resources_list
from mcpcli.messages.send_initialize_message import send_initialize
from mcpcli.messages.send_call_tool import send_call_tool
from mcpcli.messages.send_tools_list import send_tools_list
from mcpcli.transport.sse.sse_client import sse_client
from mcpcli.transport.sse.sse_server_parameters import SSEServerParameters
from mcpcli.transport.stdio.stdio_client import stdio_client
from mcpcli.transport.stdio.stdio_server_parameters import StdioServerParameters

# Default path for the configuration file
DEFAULT_CONFIG_FILE = "server_config.json"

# Configure logging
logging.basicConfig(
    level=logging.CRITICAL,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)


def signal_handler(sig, frame):
    # Ignore subsequent SIGINT signals
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # pretty exit
    print("\n[bold red]Goodbye![/bold red]")

    # Immediately and forcibly kill the process
    os.kill(os.getpid(), signal.SIGKILL)


# signal handler
signal.signal(signal.SIGINT, signal_handler)


async def handle_command(command: str, server_streams: List[tuple]) -> bool:
    """Handle specific commands dynamically with multiple servers."""
    try:
        if command == "ping":
            print("[cyan]\nPinging Servers...[/cyan]")
            for i, (read_stream, write_stream) in enumerate(server_streams):
                result = await send_ping(read_stream, write_stream)
                server_num = i + 1
                if result:
                    ping_md = f"## Server {server_num} Ping Result\n\n✅ **Server is up and running**"
                    print(Panel(Markdown(ping_md), style="bold green"))
                else:
                    ping_md = f"## Server {server_num} Ping Result\n\n❌ **Server ping failed**"
                    print(Panel(Markdown(ping_md), style="bold red"))

        elif command == "list-tools":
            print("[cyan]\nFetching Tools List from all servers...[/cyan]")
            for i, (read_stream, write_stream) in enumerate(server_streams):
                response = await send_tools_list(read_stream, write_stream)
                tools_list = response.get("tools", [])
                server_num = i + 1

                if not tools_list:
                    tools_md = (
                        f"## Server {server_num} Tools List\n\nNo tools available."
                    )
                else:
                    tools_md = f"## Server {server_num} Tools List\n\n" + "\n".join(
                        [
                            f"- **{t.get('name')}**: {t.get('description', 'No description')}"
                            for t in tools_list
                        ]
                    )
                print(
                    Panel(
                        Markdown(tools_md),
                        title=f"Server {server_num} Tools",
                        style="bold cyan",
                    )
                )

        elif command == "call-tool":
            tool_name = Prompt.ask(
                "[bold magenta]Enter tool name[/bold magenta]"
            ).strip()
            if not tool_name:
                print("[red]Tool name cannot be empty.[/red]")
                return True

            arguments_str = Prompt.ask(
                "[bold magenta]Enter tool arguments as JSON (e.g., {'key': 'value'})[/bold magenta]"
            ).strip()
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError as e:
                print(f"[red]Invalid JSON arguments format:[/red] {e}")
                return True

            print(f"[cyan]\nCalling tool '{tool_name}' with arguments:\n[/cyan]")
            print(
                Panel(
                    Markdown(f"```json\n{json.dumps(arguments, indent=2)}\n```"),
                    style="dim",
                )
            )

            result = await send_call_tool(tool_name, arguments, server_streams)
            if result.get("isError"):
                print(f"[red]Error calling tool:[/red] {result.get('error')}")
            else:
                response_content = result.get("content", "No content")
                print(
                    Panel(
                        Markdown(f"### Tool Response\n\n{response_content}"),
                        style="green",
                    )
                )

        elif command == "list-resources":
            print("[cyan]\nFetching Resources List from all servers...[/cyan]")
            for i, (read_stream, write_stream) in enumerate(server_streams):
                response = await send_resources_list(read_stream, write_stream)
                resources_list = response.get("resources", []) if response else None
                server_num = i + 1

                if not resources_list:
                    resources_md = f"## Server {server_num} Resources List\n\nNo resources available."
                else:
                    resources_md = f"## Server {server_num} Resources List\n"
                    for r in resources_list:
                        if isinstance(r, dict):
                            json_str = json.dumps(r, indent=2)
                            resources_md += f"\n```json\n{json_str}\n```"
                        else:
                            resources_md += f"\n- {r}"
                print(
                    Panel(
                        Markdown(resources_md),
                        title=f"Server {server_num} Resources",
                        style="bold cyan",
                    )
                )

        elif command == "list-prompts":
            print("[cyan]\nFetching Prompts List from all servers...[/cyan]")
            for i, (read_stream, write_stream) in enumerate(server_streams):
                response = await send_prompts_list(read_stream, write_stream)
                prompts_list = response.get("prompts", [])
                server_num = i + 1

                if not prompts_list:
                    prompts_md = (
                        f"## Server {server_num} Prompts List\n\nNo prompts available."
                    )
                else:
                    prompts_md = f"## Server {server_num} Prompts List\n\n" + "\n".join(
                        [f"- {p}" for p in prompts_list]
                    )
                print(
                    Panel(
                        Markdown(prompts_md),
                        title=f"Server {server_num} Prompts",
                        style="bold cyan",
                    )
                )

        elif command == "chat":
            provider = os.getenv("LLM_PROVIDER", "openai")
            model = os.getenv("LLM_MODEL", "gpt-4o-mini")

            # Clear the screen first
            if sys.platform == "win32":
                os.system("cls")
            else:
                os.system("clear")

            chat_info_text = (
                "Welcome to the Chat!\n\n"
                f"**Provider:** {provider}  |  **Model:** {model}\n\n"
                "Type 'exit' to quit."
            )

            print(
                Panel(
                    Markdown(chat_info_text),
                    style="bold cyan",
                    title="Chat Mode",
                    title_align="center",
                )
            )
            await handle_chat_mode(server_streams, provider, model)

        elif command in ["quit", "exit"]:
            print("\n[bold red]Goodbye![/bold red]")
            return False

        elif command == "clear":
            if sys.platform == "win32":
                os.system("cls")
            else:
                os.system("clear")

        elif command == "help":
            help_md = """
# Available Commands

- **ping**: Check if server is responsive
- **list-tools**: Display available tools
- **list-resources**: Display available resources
- **list-prompts**: Display available prompts
- **chat**: Enter chat mode
- **clear**: Clear the screen
- **help**: Show this help message
- **quit/exit**: Exit the program

**Note:** Commands use dashes (e.g., `list-tools` not `list tools`).
"""
            print(Panel(Markdown(help_md), style="yellow"))

        else:
            print(f"[red]\nUnknown command: {command}[/red]")
            print("[yellow]Type 'help' for available commands[/yellow]")
    except Exception as e:
        print(f"\n[red]Error executing command:[/red] {e}")

    return True


async def get_input():
    """Get input asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: input().strip().lower())


async def interactive_mode(server_streams: List[tuple]):
    """Run the CLI in interactive mode with multiple servers."""
    welcome_text = """
# Welcome to the Interactive MCP Command-Line Tool (Multi-Server Mode)

Type 'help' for available commands or 'quit' to exit.
"""
    print(Panel(Markdown(welcome_text), style="bold cyan"))

    while True:
        try:
            command = Prompt.ask("[bold green]\n>[/bold green]").strip().lower()
            if not command:
                continue
            should_continue = await handle_command(command, server_streams)
            if not should_continue:
                return
        except EOFError:
            break
        except Exception as e:
            print(f"\n[red]Error:[/red] {e}")


class GracefulExit(Exception):
    """Custom exception for handling graceful exits."""

    pass


async def run(config_path: str, server_names: List[str], command: str = None) -> None:
    """Main function to manage server initialization, communication, and shutdown."""
    # Clear screen before rendering anything
    if sys.platform == "win32":
        os.system("cls")
    else:
        os.system("clear")

    # Load server configurations and establish connections for all servers
    server_streams = []
    context_managers = []
    client = None
    for server_name in server_names:
        server_params = await load_config(config_path, server_name)

        # Establish stdio or sse communication for each server
        if isinstance(server_params, StdioServerParameters):
            cm = stdio_client(server_params)
            (read_stream, write_stream) = await cm.__aenter__()
            context_managers.append(cm)
            server_streams.append((read_stream, write_stream))

            init_result = await send_initialize(read_stream, write_stream)
            if not init_result:
                print(f"[red]Server initialization failed for {server_name}[/red]")
                return
        elif isinstance(server_params, SSEServerParameters):
            client = sse_client(server_params.endpoint)
            (read_stream, write_stream) = await client.__aenter__()
            context_managers.append(client)
            server_streams.append((read_stream, write_stream))

        else:
            raise ValueError("Server transport not supported")

    try:
        if command:
            # Single command mode
            await handle_command(command, server_streams)
        else:
            # Interactive mode
            await interactive_mode(server_streams)
    finally:
        # Clean up all streams
        for cm in context_managers:
            with anyio.move_on_after(1):  # wait up to 1 second
                await cm.__aexit__()

def cli_main():
    # setup the parser
    parser = argparse.ArgumentParser(description="MCP Command-Line Tool")

    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE,
        help="Path to the JSON configuration file containing server details.",
    )

    parser.add_argument(
        "--server",
        action="append",
        dest="servers",
        help="Server configuration(s) to use. Can be specified multiple times.",
        default=[],
    )

    parser.add_argument(
        "command",
        nargs="?",
        choices=["ping", "list-tools", "list-resources", "list-prompts"],
        help="Command to execute (optional - if not provided, enters interactive mode).",
    )

    parser.add_argument(
        "--provider",
        choices=["openai", "ollama","amazon"],
        default="openai",
        help="LLM provider to use. Defaults to 'openai'.",
    )

    parser.add_argument(
        "--model",
        help=("Model to use. Defaults to 'gpt-4o-mini' for 'openai' and 'qwen2.5-coder' for 'ollama', 'Claude-3-5-sonnet' for 'amazon'."),
    )

    parser.add_argument(
        "--aws-region",
        default="us-east-1",
        help=("AWS region to use. Defaults to 'us-east-1'."),
    )

    args = parser.parse_args()

    model = args.model or (
        "gpt-4o-mini" if args.provider == "openai" 
        else "claude-3.5-sonnet" if args.provider == "amazon"
        else "qwen2.5-coder"
    )
    os.environ["LLM_PROVIDER"] = args.provider
    os.environ["LLM_MODEL"] = model
    os.environ["AWS_REGION"] = args.aws_region 

    try:
        result = anyio.run(run, args.config_file, args.servers, args.command)
        sys.exit(result)
    except Exception as e:
        print(f"[red]Error occurred:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
