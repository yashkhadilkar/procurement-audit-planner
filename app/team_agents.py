"""The planner and the challenger as Agent SDK sessions, one per task.

Each call is a fresh session in WORK_DIR, through runner.run_sdk: the role's
harness instructions (app/team_prompts/<role>.md) and the audit-program
SKILL.md (the workspace's protected copy) are appended to the system prompt,
the reply is constrained to the call's JSON schema, and the session may spend
at most what is left under the team cap. The roles' tools and denials follow
.claude/agents/planner.md and challenger.md: the planner may write only
outputs/audit-plan.json, the challenger writes nothing and may not read data/
or outputs/analytics-full/.
"""

import json
from pathlib import Path

from .runner import RunSpec, run_sdk
from .team import Reply

PROMPTS = Path(__file__).resolve().parent / "team_prompts"
SKILL = ".claude/skills/audit-program/SKILL.md"
PATH_FLAGS = r"build_pack\.py[^\n;&|]*\s--(root|out-dir|plan|analytics|history|rules|analytics-full)\b"
COMMON_DENY = [
    (r"procurement-holding", "Nothing under ~/procurement-holding/ may be read."),
    (r"plan-backups", "The previous plan and pack in plan-backups/ are not open to the team."),
    (r"\bgit\b(?!\s+status\b)", "Only git status is allowed: the workspace history holds earlier plans."),
    (PATH_FLAGS, "build_pack.py runs without path flags: they point it at copies of the inputs."),
    (r"build_register\.py(?![^\n;&|]*--resolve)", "build_register.py runs only with --resolve."),
]
ROLES = {
    "planner": {
        "tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        "write": ["outputs/audit-plan.json"],
        "read_deny": ["plan-backups", ".git"],
        "bash_deny": COMMON_DENY + [
            (r"run_checks\.py|check_(quotes|numbers|trace|samples)\.py", "The harness runs the QA checks."),
        ],
    },
    "challenger": {
        "tools": ["Read", "Bash", "Glob", "Grep"],
        "write": [],
        "read_deny": ["data", "outputs/analytics-full", "plan-backups", ".git"],
        "bash_deny": COMMON_DENY + [
            (r"build_pack\.py(?![^\n;&|]*--gate)", "The challenger runs build_pack.py only with --gate."),
            (r"--lists\b", "--lists reads the full lists, which the challenger never reads."),
            (r"(^|[\s'\"=/])data/|analytics-full", "The challenger never reads data/ or outputs/analytics-full/."),
        ],
    },
}


def system_prompt(role, root):
    skill = (Path(root) / SKILL).read_text(encoding="utf-8")
    return ((PROMPTS / f"{role}.md").read_text(encoding="utf-8")
            + "\n\n---\n\n# The audit-program skill (.claude/skills/audit-program/SKILL.md)\n\n" + skill)


class SdkTeamAgents:
    """agents(call, emit) -> Reply, for team.run_team."""

    def __init__(self, root, api_key, run_id="team", exclude_claude_md=(), runner=run_sdk):
        self.root = Path(root).resolve()
        self.api_key = api_key
        self.run_id = run_id
        self.exclude_claude_md = list(exclude_claude_md)
        self.runner = runner

    def spec(self, call):
        role = ROLES[call.role]
        return RunSpec(
            run_id=self.run_id, stage=f"team:{call.role}", prompt=call.prompt, model=call.model,
            max_budget_usd=call.max_budget_usd, cwd=self.root,
            write_roots=[self.root / p for p in role["write"]], forward_subagent_text=False,
            exclude_claude_md=self.exclude_claude_md, api_key=self.api_key,
            tools=list(role["tools"]), skills=[], system_prompt=system_prompt(call.role, self.root),
            output_format={"type": "json_schema", "schema": call.schema},
            bash_deny=list(role["bash_deny"]), read_deny=[self.root / p for p in role["read_deny"]])

    async def __call__(self, call, emit):
        outcome = await self.runner(self.spec(call), emit)
        data = outcome.structured_output
        if data is None and outcome.result_text:
            try:
                data = json.loads(outcome.result_text)
            except ValueError:
                data = None
        return Reply(data=data if isinstance(data, dict) else None, cost_usd=outcome.cost_usd,
                     subtype=outcome.subtype, is_error=outcome.is_error)
