import argparse
import asyncio
import os
import shlex

from langchain_openai import ChatOpenAI

from .agent import Agent


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run HEP-multiagent with an MCP tool server.")
    parser.add_argument("query", help="User request for the agent")
    parser.add_argument("--output-dir", default="./output", help="Directory for run artifacts")
    parser.add_argument("--model", default=os.environ.get("ARGO_MODEL", "GPT-5.5"))
    parser.add_argument("--base-url", default=os.environ.get("ARGO_BASE_URL", "https://apps-dev.inside.anl.gov/argoapi/v1"))
    parser.add_argument("--argo-user", default=os.environ.get("ARGO_USER"), help="Argo username")
    parser.add_argument("--mcp-name", default="mcp-tools", help="Name for the MCP server")

    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--mcp-url", help="Streamable HTTP MCP endpoint, e.g. http://127.0.0.1:8000/mcp")
    transport.add_argument("--mcp-command", help="Command that starts a stdio MCP server")
    parser.add_argument("--mcp-args", default="", help="Arguments for --mcp-command, parsed with shell-like quoting")
    return parser.parse_args(argv)


def mcp_servers_from_args(args):
    if args.mcp_url:
        return [{"name": args.mcp_name, "url": args.mcp_url, "transport": "streamable_http"}]
    return [{
        "name": args.mcp_name,
        "transport": "stdio",
        "command": args.mcp_command,
        "args": shlex.split(args.mcp_args),
    }]


def llm_from_args(args):
    if not args.argo_user:
        raise ValueError("Set ARGO_USER or pass --argo-user.")
    return ChatOpenAI(model=args.model, base_url=args.base_url, api_key=args.argo_user)


async def run(args):
    agent = Agent(llm=llm_from_args(args), mcp_servers=mcp_servers_from_args(args))
    result = await agent.run(args.query, output_dir=args.output_dir)
    print(result["final_report"])


def main(argv=None):
    asyncio.run(run(parse_args(argv)))
