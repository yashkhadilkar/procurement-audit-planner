"""Run one stage through the Claude Agent SDK and turn its messages into events.

Settings follow scripts/probe_sdk.py: project settings only (CLAUDE.md,
.claude/settings.json, .claude/agents), only our three skills by name,
personal (auto) memory off, and sub-agent tool calls forwarded into the
stream with parent_tool_use_id. Tools run in dontAsk mode from a fixed list; a
PreToolUse hook confines Write/Edit to the workspace's writable folders and
blocks any access to .env.
"""

import json
import re
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

SKILLS = ["extract-rules", "risk-assessment", "audit-program"]
TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "Skill"]
AGENT_TOOLS = {"Agent", "Task"}
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}
DOTENV_IN_COMMAND = re.compile(r"\.env\b")
TEMP_ROOTS = {Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}


@dataclass
class RunSpec:
    run_id: str
    stage: str
    prompt: str
    model: str
    max_budget_usd: float
    cwd: Path
    write_roots: list
    forward_subagent_text: bool = True
    exclude_claude_md: list = field(default_factory=list)
    api_key: str = field(default="", repr=False)
    # The team stage runs each role as its own session: its own tools, a system
    # prompt appended to Claude Code's, a JSON schema for the final reply, and
    # extra denials (command patterns, folders it may not read).
    tools: list = field(default_factory=lambda: list(TOOLS))
    skills: list = field(default_factory=lambda: list(SKILLS))
    system_prompt: str | None = None
    output_format: dict | None = None
    bash_deny: list = field(default_factory=list)  # [(regex, reason)]
    read_deny: list = field(default_factory=list)  # paths: no read, list or search inside them


@dataclass
class Outcome:
    subtype: str
    is_error: bool
    cost_usd: float | None = None
    num_turns: int | None = None
    duration_ms: int | None = None
    result_text: str | None = None
    session_id: str | None = None
    structured_output: object = None


def clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n] + f"... [{len(s) - n} more chars]"


def brief_input(inp):
    out = {}
    for k, v in (inp or {}).items():
        if isinstance(v, str):
            out[k] = clip(v, 1500 if k in ("command", "prompt", "description", "file_path", "path", "pattern",
                                           "subagent_type", "skill") else 300)
        else:
            out[k] = clip(json.dumps(v, default=str), 300)
    return out


def result_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for c in content:
        if isinstance(c, dict):
            parts.append(c.get("text") or f"[{c.get('type', 'block')}]")
        else:
            parts.append(str(c))
    return "\n".join(parts)


def _inside(path, roots):
    return any(path == r or r in path.parents for r in roots)


def make_guard(spec, emit):
    """PreToolUse hook: deny writes outside the writable roots, any .env access, and the spec's extra denials.

    Writes to the system temp folders are allowed too, but never inside the workspace (spec.cwd): if
    WORK_DIR or TMPDIR puts the workspace under a temp root, the write roots alone still apply there."""
    workspace = Path(spec.cwd).resolve()
    write_roots = [Path(r).resolve() for r in spec.write_roots]
    temp_roots = [t for t in TEMP_ROOTS if not _inside(t, [workspace])]
    read_deny = [Path(r).resolve() for r in spec.read_deny]
    bash_deny = [(re.compile(rx), reason) for rx, reason in spec.bash_deny]

    def deny(reason, tool):
        emit({"type": "guard", "tool": tool, "reason": reason})
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}

    async def guard(input_data, tool_use_id, context):
        tool = input_data.get("tool_name", "")
        ti = input_data.get("tool_input") or {}
        base = Path(input_data.get("cwd") or spec.cwd)
        if tool == "Bash":
            command = str(ti.get("command", ""))
            if DOTENV_IN_COMMAND.search(command):
                return deny("The web app does not allow access to .env files.", tool)
            for rx, reason in bash_deny:
                if rx.search(command):
                    return deny(reason, tool)
            return {}
        if tool == "Glob" and read_deny and ti.get("pattern"):
            literal = re.split(r"[*?\[{]", str(ti["pattern"]), maxsplit=1)[0]
            p = Path(ti.get("path") or base) / literal
            if any(_inside(p.resolve(), [r]) for r in read_deny):
                return deny(f"{ti['pattern']} reaches a folder that is not open to this agent.", tool)
        raw = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
        if not raw:
            return {}
        p = Path(raw).expanduser()
        p = (p if p.is_absolute() else base / p).resolve()
        if p.name == ".env" or p.name.startswith(".env."):
            return deny("The web app does not allow access to .env files.", tool)
        if tool in WRITE_TOOLS and not (_inside(p, write_roots)
                                        or (_inside(p, temp_roots) and not _inside(p, [workspace]))):
            return deny(f"Writes are allowed only under {', '.join(str(r) for r in spec.write_roots)}; "
                        f"{p} is outside them.", tool)
        if any(_inside(p, [r]) for r in read_deny):
            return deny(f"{p} is not open to this agent.", tool)
        return {}

    return guard


async def run_sdk(spec, emit):
    """Run spec.prompt through the Agent SDK, calling emit(event) for each step. Returns an Outcome."""
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher,
                                  ResultMessage, SystemMessage, TextBlock, ThinkingBlock, ToolResultBlock,
                                  ToolUseBlock, UserMessage)

    stderr_tail = deque(maxlen=40)
    options = ClaudeAgentOptions(
        cwd=str(spec.cwd),
        model=spec.model,
        setting_sources=["project"],
        skills=list(spec.skills),
        tools=list(spec.tools),
        allowed_tools=list(spec.tools),
        system_prompt=({"type": "preset", "preset": "claude_code", "append": spec.system_prompt,
                        "exclude_dynamic_sections": True} if spec.system_prompt else None),
        output_format=spec.output_format,
        permission_mode="dontAsk",
        max_budget_usd=spec.max_budget_usd,
        forward_subagent_text=spec.forward_subagent_text,
        settings=json.dumps({"autoMemoryEnabled": False, "claudeMdExcludes": spec.exclude_claude_md}),
        # The agent's own process gets the API key and nothing else of ours. Background
        # tasks are off: a backgrounded sub-agent dies when the main turn ends and the
        # session closes. Sub-agents run on the stage's model, whatever their file says.
        env={"ANTHROPIC_API_KEY": spec.api_key, "ACCESS_CODE": "", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
             "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1", "CLAUDE_CODE_SUBAGENT_MODEL": spec.model},
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[make_guard(spec, emit)])]},
        stderr=stderr_tail.append,
    )

    agents = {}  # Agent tool_use id -> sub-agent name
    background = {}  # task_id -> description, for backgrounded tasks not yet finished

    def who(parent):
        return agents.get(parent, "subagent") if parent else "main"

    outcome = None
    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(spec.prompt)
            async for msg in client.receive_response():
                if isinstance(msg, SystemMessage):
                    d = msg.data or {}
                    if msg.subtype == "init":
                        # skills_discovered is everything on disk; only skills_enabled are
                        # listed to the model and accepted by the Skill tool.
                        emit({"type": "session", "model": d.get("model"), "cwd": d.get("cwd"),
                              "permission_mode": d.get("permissionMode"), "skills_enabled": list(SKILLS),
                              "skills_discovered": sorted(d.get("skills", [])),
                              "agents": sorted(d.get("agents", [])), "tools": sorted(d.get("tools", []))})
                    else:
                        if msg.subtype == "task_started" and str(d.get("is_backgrounded")).lower() == "true":
                            background[d.get("task_id")] = d.get("description") or d.get("subagent_type")
                        elif msg.subtype == "task_notification":
                            background.pop(d.get("task_id"), None)
                        emit({"type": "system", "subtype": msg.subtype,
                              "data": {k: clip(v, 300) for k, v in d.items()
                                       if isinstance(v, (str, int, float, bool)) and k not in ("uuid", "session_id")}})
                elif isinstance(msg, AssistantMessage):
                    agent = who(msg.parent_tool_use_id)
                    for b in msg.content:
                        if isinstance(b, TextBlock) and b.text.strip():
                            emit({"type": "text", "agent": agent, "parent": msg.parent_tool_use_id,
                                  "text": clip(b.text, 8000)})
                        elif isinstance(b, ThinkingBlock) and b.thinking.strip():
                            emit({"type": "thinking", "agent": agent, "parent": msg.parent_tool_use_id,
                                  "text": clip(b.thinking, 2000)})
                        elif isinstance(b, ToolUseBlock):
                            if b.name in AGENT_TOOLS:
                                agents[b.id] = (b.input or {}).get("subagent_type") or "subagent"
                            emit({"type": "tool_use", "agent": agent, "parent": msg.parent_tool_use_id,
                                  "id": b.id, "name": b.name, "input": brief_input(b.input)})
                elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                    agent = who(msg.parent_tool_use_id)
                    for b in msg.content:
                        if isinstance(b, ToolResultBlock):
                            emit({"type": "tool_result", "agent": agent, "parent": msg.parent_tool_use_id,
                                  "tool_use_id": b.tool_use_id, "is_error": bool(b.is_error),
                                  "content": clip(result_text(b.content), 3000)})
                elif isinstance(msg, ResultMessage):
                    outcome = Outcome(subtype=msg.subtype, is_error=bool(msg.is_error),
                                      cost_usd=msg.total_cost_usd, num_turns=msg.num_turns,
                                      duration_ms=msg.duration_ms, result_text=msg.result,
                                      session_id=msg.session_id,
                                      structured_output=getattr(msg, "structured_output", None))
                    emit({"type": "result", "subtype": msg.subtype, "is_error": bool(msg.is_error),
                          "cost_usd": msg.total_cost_usd, "num_turns": msg.num_turns,
                          "duration_ms": msg.duration_ms, "text": clip(msg.result or "", 8000),
                          "model_usage": {m: {k: v for k, v in (u if isinstance(u, dict) else vars(u)).items()
                                              if isinstance(v, (int, float))}
                                          for m, u in (getattr(msg, "model_usage", None) or {}).items()}})
    except Exception as e:
        tail = "\n".join(stderr_tail)
        raise RuntimeError(f"{type(e).__name__}: {clip(e, 1000)}" + (f"\nCLI stderr:\n{clip(tail, 3000)}" if tail else ""))
    if outcome is None:
        raise RuntimeError("the agent session ended without a result message")
    if background:
        outcome.is_error = True
        outcome.subtype = "error_background_task_unfinished"
        emit({"type": "error", "message": "the session ended while background tasks were still running: "
                                          + ", ".join(str(v) for v in background.values())})
    return outcome
