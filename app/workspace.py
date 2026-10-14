"""WORK_DIR: the self-contained workspace the agents run in.

The skills' builders and scripts/common.py locate the project root from
Path(__file__).resolve(), so agents cannot run against the repo (they would
write the repo's outputs/) or through symlinks (resolve() follows them back).
WORK_DIR therefore holds its own copies:

    outputs/              seeded from the repo's committed outputs/ (git HEAD)
    data/, CLAUDE.md,     copied from the repo before every run; read-only
    .claude/skills|agents|settings.json
    scripts/,             copied when the workspace is seeded or reset; the
    .claude/agent-memory  spend-analyst rewrites scripts/, agents add memory
    .venv                 symlink to the repo's virtualenv
    runs/                 one <id>.json per run (not part of the workspace git)

WORK_DIR is its own git repository: the agents run `git status --porcelain`
to confirm they changed only their own files, and the app commits before and
after each run, so a run's outputs are the diff between the two commits.
"""

import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .settings import REPO

READ_ONLY_INPUTS = ["data", "CLAUDE.md", ".claude/skills", ".claude/agents", ".claude/settings.json"]
SEEDED_ONCE = ["scripts", ".claude/agent-memory"]
WRITABLE = ["outputs", "scripts", ".claude/agent-memory"]
IGNORE = shutil.ignore_patterns("__pycache__", ".DS_Store")
GITIGNORE = ".venv\nruns/\nworkspace.json\n__pycache__/\n.DS_Store\n"
GIT_ID = ["-c", "user.name=audit-planner app", "-c", "user.email=app@localhost",
          "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, root, repo=REPO):
        self.root = Path(root).resolve()
        self.repo = Path(repo).resolve()
        self.outputs = self.root / "outputs"
        self.runs = self.root / "runs"
        self.info_file = self.root / "workspace.json"

    # ------------------------------------------------------------ lifecycle

    def ensure(self):
        """Create the workspace, seeding it from the signed-off run if it has no outputs."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs.mkdir(exist_ok=True)
        if not self.outputs.is_dir() or not any(self.outputs.iterdir()):
            self._seed("Seed workspace from the signed-off run")
        else:
            self.refresh_inputs()
            self._git_init()

    def reset(self):
        """Restore outputs/, scripts/ and agent memory to the signed-off run. Run logs are kept."""
        for rel in ["outputs", *SEEDED_ONCE]:
            shutil.rmtree(self.root / rel, ignore_errors=True)
        self._seed("Reset to the signed-off run")

    def _seed(self, message):
        commit = self._seed_outputs()
        for rel in SEEDED_ONCE:
            self._copy(rel)
        self.refresh_inputs()
        self._git_init()
        sha = self.commit(message)
        self.info_file.write_text(json.dumps(
            {"seeded_at": now_iso(), "source_commit": commit, "workspace_commit": sha}, indent=2) + "\n")

    def info(self):
        try:
            return json.loads(self.info_file.read_text())
        except (OSError, ValueError):
            return {}

    # ------------------------------------------------------------ copying

    def _seed_outputs(self):
        """Extract outputs/ as committed at the repo's HEAD; returns that commit, or None
        if git is unavailable and the working-tree copy was used instead."""
        shutil.rmtree(self.outputs, ignore_errors=True)
        try:
            sha = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, check=True).stdout.strip()
            tar = subprocess.run(["git", "-C", str(self.repo), "archive", "--format=tar", "HEAD", "outputs"],
                                 capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            shutil.copytree(self.repo / "outputs", self.outputs, ignore=IGNORE)
            return None
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
                tf.extractall(tmp, filter="data")
            shutil.move(str(Path(tmp) / "outputs"), self.outputs)
        return sha

    def _copy(self, rel):
        src, dst = self.repo / rel, self.root / rel
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        elif dst.exists() or dst.is_symlink():
            dst.unlink()
        if not src.exists():
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=IGNORE)
        else:
            shutil.copy2(src, dst)

    def refresh_inputs(self):
        """Copy the read-only inputs from the repo, so every run sees the repo's current versions."""
        for rel in READ_ONLY_INPUTS:
            self._copy(rel)
        venv = self.root / ".venv"
        if not venv.exists() and (self.repo / ".venv").exists():
            venv.symlink_to(self.repo / ".venv", target_is_directory=True)
        (self.root / ".gitignore").write_text(GITIGNORE)

    # ------------------------------------------------------------ git

    def _git(self, *args, check=True):
        r = subprocess.run(["git", *GIT_ID, "-C", str(self.root), *args], capture_output=True, text=True)
        if check and r.returncode != 0:
            raise WorkspaceError(f"git {args[0]} failed in the workspace: {r.stderr.strip()[:300]}")
        return r.stdout

    def _git_init(self):
        if not (self.root / ".git").exists():
            self._git("init", "-q", "-b", "main")

    def commit(self, message):
        """Commit everything in the workspace; returns HEAD (unchanged if there was nothing to commit)."""
        self._git("add", "-A")
        if self._git("status", "--porcelain").strip() or not self._git("rev-parse", "--verify", "-q", "HEAD", check=False):
            self._git("commit", "-q", "--allow-empty", "-m", message)
        return self._git("rev-parse", "HEAD").strip()

    def changed(self, before, after):
        """[(status, path)] between two workspace commits."""
        out = self._git("diff", "--name-status", "--no-renames", before, after)
        return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]

    # ------------------------------------------------------------ paths

    def write_roots(self):
        return [self.root / rel for rel in WRITABLE]
