"""
llm_query.py - Standalone LLM query script using ChatOpenAI interface.

Supports multiple backends: argo, amsc-i2, alcf-first.
No agentic framework - just plain LLM access and query/answer.

Usage:
    python llm_query.py                           # interactive mode, all backends
    python llm_query.py --backend argo            # single backend
    python llm_query.py --backend argo amsc-i2    # multiple backends
    python llm_query.py --query "What is dark matter?"
    python llm_query.py --backend argo --query "What are twin primes?" --list-backends
"""

import os
import sys
import argparse
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv(".env")


# ---------------------------------------------------------------------------
# Backend definitions
# ---------------------------------------------------------------------------

def build_backends():
    backends = {
        "argo": {
            "model": "claudeopus46",
            "base_url": "https://apps-dev.inside.anl.gov/argoapi/v1",
            "api_key": os.environ.get("ARGO_USER", ""),
        },
        "amsc-i2": {
            "model": "claude-sonnet",
            "base_url": "https://api.i2-core.american-science-cloud.org/",
            "api_key": os.environ.get("AMSC_I2_API_KEY", ""),
        },
        "alcf-first": {
            "model": "openai/gpt-oss-120b",
            "base_url": "https://inference-api.alcf.anl.gov/resource_server/sophia/vllm/v1",
            "api_key": None,  # filled via Globus auth below
        },
    }
    return backends


def get_alcf_token():
    try:
        from inference_auth_token_alcf_first import get_access_token
        return get_access_token()
    except ImportError:
        print("WARNING: inference_auth_token_alcf_first.py not found. alcf-first backend will fail.")
        return ""
    except Exception as e:
        print(f"WARNING: Could not get ALCF token: {e}")
        return ""


def get_llm(backend_name: str, backends: dict, **kwargs) -> ChatOpenAI:
    """Return a ChatOpenAI instance for the given backend name."""
    if backend_name not in backends:
        raise ValueError(f"Unknown backend '{backend_name}'. Available: {list(backends)}")
    cfg = backends[backend_name].copy()
    cfg.update(kwargs)
    return ChatOpenAI(**cfg)


# ---------------------------------------------------------------------------
# Query logic
# ---------------------------------------------------------------------------

def query_llm(llm: ChatOpenAI, query: str, system_prompt: str = "") -> str:
    """Send a query to the LLM and return the response text."""
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=query))
    response = llm.invoke(messages)
    return response.content


def query_all(backends_to_use: list[str], backends: dict, query: str, system_prompt: str = "") -> dict:
    """Query multiple backends and return {backend_name: answer} dict."""
    results = {}
    for name in backends_to_use:
        print(f"\n{'='*60}")
        print(f"Backend: {name}  (model: {backends[name]['model']})")
        print(f"{'='*60}")
        try:
            llm = get_llm(name, backends)
            answer = query_llm(llm, query, system_prompt)
            results[name] = answer
            print(answer)
        except Exception as e:
            results[name] = f"ERROR: {e}"
            print(f"ERROR: {e}")
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Query one or more LLM backends via the ChatOpenAI interface.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--backend", "-b",
        nargs="+",
        metavar="BACKEND",
        help="Backend(s) to query. Choices: argo, amsc-i2, alcf-first. Defaults to all.",
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Query string. If omitted, you will be prompted interactively.",
    )
    parser.add_argument(
        "--system", "-s",
        type=str,
        default="",
        help="Optional system prompt.",
    )
    parser.add_argument(
        "--list-backends",
        action="store_true",
        help="List available backends and exit.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    backends = build_backends()

    if args.list_backends:
        print("Available backends:")
        for name, cfg in backends.items():
            print(f"  {name:12s}  model={cfg['model']}  url={cfg['base_url']}")
        sys.exit(0)

    # Resolve ALCF token lazily (only if needed)
    requested = args.backend or list(backends)
    if "alcf-first" in requested and backends["alcf-first"]["api_key"] is None:
        print("Fetching ALCF Globus token...")
        backends["alcf-first"]["api_key"] = get_alcf_token()

    # Validate requested backends
    invalid = [b for b in requested if b not in backends]
    if invalid:
        print(f"ERROR: Unknown backend(s): {invalid}. Available: {list(backends)}")
        sys.exit(1)

    # Get query
    query = args.query
    if not query:
        print("Enter your query (end with a blank line or Ctrl+D):")
        lines = []
        try:
            while True:
                line = input()
                if line == "":
                    break
                lines.append(line)
        except EOFError:
            pass
        query = "\n".join(lines).strip()

    if not query:
        print("No query provided. Exiting.")
        sys.exit(1)

    print(f"\nQuery: {query}")
    if args.system:
        print(f"System: {args.system}")

    query_all(requested, backends, query, system_prompt=args.system)


if __name__ == "__main__":
    main()
