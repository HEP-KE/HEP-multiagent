import asyncio
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from hep_multiagent import Agent


async def main():
    load_dotenv()

    llm = ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        api_key=os.environ["OPENAI_API_KEY"],
    )

    mcp_url = os.environ.get("HEP_MCP_SERVER_URL")
    mcp_servers = [{"name": "hep-tools", "url": mcp_url}] if mcp_url else None

    agent = await Agent(llm=llm, mcp_servers=mcp_servers)
    result = await agent.run(
        "Find three recent papers on dark matter detection and summarize the main methods.",
        output_dir="./output",
    )
    print(result.get("final_report", result))


if __name__ == "__main__":
    asyncio.run(main())
