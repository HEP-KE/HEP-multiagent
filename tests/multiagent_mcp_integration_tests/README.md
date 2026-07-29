# Multiagent MCP Integration Tests

These tests run `hep_multiagent.Agent` against remote streamable HTTP MCP endpoints using Argo as the only LLM backend. They are opt-in because they require Argo credentials and live MCP server URLs.

Run all available live MCP tests:

```bash
RUN_MULTIAGENT_MCP_TESTS=1 \
ARGO_BASE_URL=... \
ARGO_USER=... \
ARGO_MODEL=gpt-5.5 \
KB_MCP_SERVER_URL=https://.../mcp \
MCP_MICROLENSING_SERVER_URL=https://.../mcp \
MCP_KE_SERVER_URL=https://.../mcp \
pytest tests/multiagent_mcp_integration_tests -q
```

Each test writes artifacts under its server-specific subdirectory.

| Server | Endpoint variable | Prompt source |
|--------|-------------------|---------------|
| `kb-mcp` | `KB_MCP_SERVER_URL` | Search a knowledge base for Mu2e detector design |
| `mcp-microlensing` | `MCP_MICROLENSING_SERVER_URL` | Generate a small microlensing analysis summary from the connected tools |
| `mcp-ke` | `MCP_KE_SERVER_URL` | Summarize the cosmology/eBOSS power-spectrum workflow |

Notes:

- These tests do not start local MCP servers.
- Endpoint variables must point to reachable streamable HTTP MCP servers.
- If an endpoint needs auth headers, set `<ENDPOINT_ENV>_HEADERS_JSON` to a JSON object.
