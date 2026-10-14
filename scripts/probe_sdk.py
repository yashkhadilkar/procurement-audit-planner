"""Probe the Claude Agent SDK against this repo before building the Part B web app.

Answers three questions with one cheap, read-only run:
  a. Does the SDK load CLAUDE.md, .claude/skills and .claude/agents?
  b. Can it run one sub-agent (findings-analyst, asked only to name its inputs)?
  c. Does it support agent teams, or only sub-agents?

ANTHROPIC_API_KEY is read from .env and passed to the SDK; it is never printed.

Usage: .venv/bin/python scripts/probe_sdk.py
"""

import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    __version__,
)
from claude_agent_sdk._cli_version import __cli_version__

REPO = Path(__file__).resolve().parent.parent
MODEL = "claude-haiku-5-5"  # cheapest current model
READ_ONLY = ["Read", "Glob", "Grep"]
TEAM_TOOLS = {"TeamCreate", "TeamDelete", "SendMessage"}

PROMPT = """This is a probe of the Claude Agent SDK. Do not do any audit work.

1. Without using any tool, answer from your context only:
   - The first markdown heading of the project instructions (CLAUDE.md), or "NOT LOADED".
   - Every skill you can see, by name.
   - Every sub-agent type you can launch with the Agent tool, by name.
   - Any tools you have for creating an agent team or messaging teammates, by name, or "NONE".
2. Launch the findings-analyst sub-agent exactly once, with this prompt:
   "PROBE ONLY. Do not open, read or run anything. Reply in at most 5 lines with
   the input file paths or globs you would read and the one output file you
   would write, then stop."
3. Report its reply verbatim and stop."""


def load_api_key():
    """Return ANTHROPIC_API_KEY from .env without echoing any line of the file."""
    env_file = REPO / ".env"
    if not env_file.exists():
        sys.exit("STOP: .env not found at repo root")
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        name, sep, value = line.partition("=")
        if sep and name.strip() == "ANTHROPIC_API_KEY":
            value = value.strip().strip('"').strip("'")
            if value:
                return value
    sys.exit("STOP: ANTHROPIC_API_KEY missing or empty in .env")


def names(items):
    return sorted(i if isinstance(i, str) else i.get("name") or i.get("agentType") or str(i) for i in items or [])


async def main():
    options = ClaudeAgentOptions(
        cwd=str(REPO),
        model=MODEL,
        # Project only: CLAUDE.md, .claude/settings.json, .claude/skills, .claude/agents.
        # Leaves out ~/.claude so the probe sees what the web app would see.
        setting_sources=["project"],
        skills="all",
        # Full built-in tool set so the init list shows whether team tools exist,
        # but only read-only tools (plus Agent to launch the sub-agent) may run:
        # dontAsk denies anything not in allowed_tools, and writes are denied outright.
        tools={"type": "preset", "preset": "claude_code"},
        allowed_tools=READ_ONLY + ["Agent"],
        disallowed_tools=["Write", "Edit", "NotebookEdit", "Bash"],
        permission_mode="dontAsk",
        max_turns=4,
        max_budget_usd=0.50,
        env={"ANTHROPIC_API_KEY": load_api_key()},
    )

    print(f"claude-agent-sdk {__version__} (bundled CLI {__cli_version__}), model {MODEL}\n")
    async with ClaudeSDKClient(options=options) as client:
        info = await client.get_server_info() or {}
        usage = await client.get_context_usage()

        print("=== (a) What the session loaded, before any prompt ===")
        memory = [m.get("path", m) for m in usage.get("memoryFiles", [])]
        print("memory files (CLAUDE.md):", memory or "NONE")
        print("skills:", [s for s in names(info.get("commands")) if s in {"extract-rules", "risk-assessment", "audit-program"}]
              or "see init message below")
        print("agents (context usage):", names(usage.get("agents")))

        await client.query(PROMPT)
        async for msg in client.receive_response():
            if isinstance(msg, SystemMessage) and msg.subtype == "init":
                d = msg.data
                tools = d.get("tools", [])
                print("init apiKeySource:", d.get("apiKeySource"))
                print("init model:", d.get("model"))
                print("init skills:", sorted(d.get("skills", [])))
                print("init agents:", sorted(d.get("agents", [])))
                print("init tools:", sorted(tools))
                print("\n=== (c) Team tools present in this session ===")
                print("team tools:", sorted(TEAM_TOOLS & set(tools)) or "NONE")
                print("\n=== (b) Run transcript ===")
            elif isinstance(msg, AssistantMessage):
                who = "sub-agent" if msg.parent_tool_use_id else "main"
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        print(f"[{who}] {block.text}")
                    elif isinstance(block, ToolUseBlock):
                        brief = {k: v for k, v in block.input.items() if k != "prompt"}
                        print(f"[{who}] TOOL {block.name} {brief}")
            elif isinstance(msg, ResultMessage):
                print("\n=== Result ===")
                print(f"subtype={msg.subtype} is_error={msg.is_error} turns={msg.num_turns} "
                      f"duration={msg.duration_ms / 1000:.1f}s")
                cost = msg.total_cost_usd
                print("total cost: " + (f"${cost:.4f}" if cost is not None else "not reported"))
                for model, mu in (getattr(msg, "model_usage", None) or {}).items():
                    print(f"  {model}: {mu}")


if __name__ == "__main__":
    asyncio.run(main())
