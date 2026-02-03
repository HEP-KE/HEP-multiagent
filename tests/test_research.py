"""Test script that runs the same code as the demo notebook."""

import asyncio
import os
from datetime import datetime

async def run_demo():
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    from hep_multiagent import Agent

    load_dotenv("../.env")

    api_key = os.environ.get("ARGO_USER", "")
    if not api_key:
        print("ERROR: ARGO_USER not set. Set it in .env or environment.")
        print("Checking for ANTHROPIC_API_KEY instead...")
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(model="claude-sonnet-4-20250514")
            print("Using Anthropic API")
        else:
            print("No API key found. Cannot run demo.")
            return None
    else:
        llm = ChatOpenAI(
            model="claudesonnet4",
            base_url="https://apps-dev.inside.anl.gov/argoapi/v1",
            api_key=api_key
        )
        print("Using Argo API")

    print("\n=== Initializing Agent ===")
    agent = await Agent(
        llm=llm,
        mcp_servers=None,  # Skip MCP for faster test
        approval=False,    # Auto-approve plans
    )

    try:
        print(f"\nAgent initialized with {len(agent.tools)} MCP tools")
    except RuntimeError:
        print("\nAgent initialized (no MCP tools, using built-in tools only)")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR = f"./output_demo_test_{timestamp}"

    query = "Search arxiv for 5 papers on dark matter detection, Briefly provide information on the most recent method. then create a bar chart showing the publication year distribution of the papers found."

    print(f"\n=== Running Query ===")
    print(f"Query: {query}")
    print(f"Output dir: {OUTPUT_DIR}")
    print()

    result = await agent.run(
        query=query,
        output_dir=OUTPUT_DIR,
    )

    print(f"\n=== Result ===")
    print(f"Final report: {result.get('final_report', 'None')[:500] if result else 'No result'}...")

    # Check what was created
    if os.path.exists(OUTPUT_DIR):
        print(f"\n=== Files Created ===")
        for f in os.listdir(OUTPUT_DIR):
            fpath = os.path.join(OUTPUT_DIR, f)
            size = os.path.getsize(fpath)
            print(f"  {f} ({size} bytes)")

    return result

if __name__ == "__main__":
    result = asyncio.run(run_demo())
