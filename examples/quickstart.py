import asyncio
import os

from langchain_openai import ChatOpenAI

from hep_multiagent import Agent


async def main():
    llm = ChatOpenAI(
        model="GPT-5.5",
        base_url="https://apps-dev.inside.anl.gov/argoapi/v1",
        api_key=os.environ["ARGO_USER"],
    )

    agent = Agent(
        llm=llm,
        mcp_servers=[{"name": "hep-tools", "url": os.environ["HEP_MCP_SERVER_URL"]}],
    )
    result = await agent.run(
        "Find three recent papers on dark matter detection and summarize the main methods.",
        output_dir="./output",
    )
    print(result["final_report"])


if __name__ == "__main__":
    asyncio.run(main())
