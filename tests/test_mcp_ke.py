"""Test script that runs with the mcp-ke MCP server.

Example queries from https://github.com/HEP-KE/mcp-ke:
1. "Compare ΛCDM and wCDM models with eBOSS data"
2. "Find recent papers on galaxy mass estimation methods"
3. Power spectrum computations across cosmological models
"""

import asyncio
import os
from datetime import datetime

MCP_SERVER = "https://github.com/HEP-KE/mcp-ke.git"

QUERIES = {
    "power_spectrum": "Compare ΛCDM and wCDM models with eBOSS data and plot the power spectra",
    "research": "Find recent papers on galaxy mass estimation methods and summarize the key approaches",
    "simple": "Load the eBOSS observational data and compute the LCDM power spectrum",
}


async def run_test(query_name: str = "power_spectrum"):
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    from hep_multiagent import Agent

    load_dotenv("../.env")

    api_key = os.environ.get("ARGO_USER", "")
    if not api_key:
        print("ERROR: ARGO_USER not set. Set it in .env or environment.")
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(model="claude-sonnet-4-20250514")
            print("Using Anthropic API")
        else:
            print("No API key found. Cannot run test.")
            return None
    else:
        llm = ChatOpenAI(
            model="claudesonnet4",
            base_url="https://apps-dev.inside.anl.gov/argoapi/v1",
            api_key=api_key
        )
        print("Using Argo API")

    query = QUERIES.get(query_name, QUERIES["power_spectrum"])
    print(f"\n=== Test: {query_name} ===")
    print(f"Query: {query}")

    print(f"\n=== Initializing Agent with MCP Server ===")
    print(f"MCP: {MCP_SERVER}")

    agent = await Agent(
        llm=llm,
        mcp_servers=[{"url": MCP_SERVER}],
        approval=False,
    )

    print(f"\nAgent initialized with {len(agent.tools)} tools:")
    for t in agent.tools[:10]:
        print(f"  - {t.name}")
    if len(agent.tools) > 10:
        print(f"  ... and {len(agent.tools) - 10} more")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUT_DIR = f"./output_mcp_ke_test_{query_name}_{timestamp}"

    print(f"\n=== Running Query ===")
    print(f"Output dir: {OUTPUT_DIR}")
    print()

    result = await agent.run(
        query=query,
        output_dir=OUTPUT_DIR,
    )

    print(f"\n=== Result ===")
    if result:
        final_report = result.get('final_report', '')
        print(f"Final report preview: {final_report[:500] if final_report else 'None'}...")
    else:
        print("No result returned")

    if os.path.exists(OUTPUT_DIR):
        print(f"\n=== Files Created ===")
        for f in sorted(os.listdir(OUTPUT_DIR)):
            fpath = os.path.join(OUTPUT_DIR, f)
            size = os.path.getsize(fpath)
            print(f"  {f} ({size} bytes)")

    # Check for references.bib if research query
    if query_name == "research":
        bib_path = os.path.join(OUTPUT_DIR, "references.bib")
        if os.path.exists(bib_path):
            print(f"\n=== Citations Created ===")
            with open(bib_path) as f:
                print(f.read()[:1000])
        else:
            print("\nWARNING: No references.bib created for research query")

    return result


if __name__ == "__main__":
    import sys
    query_name = sys.argv[1] if len(sys.argv) > 1 else "power_spectrum"

    if query_name not in QUERIES:
        print(f"Available queries: {list(QUERIES.keys())}")
        sys.exit(1)

    result = asyncio.run(run_test(query_name))
