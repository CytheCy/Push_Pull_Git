from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class GitOperationResult:
    repo: Path
    operation: str
    status: str
    detail: str

    @property
    def successful(self) -> bool:
        return self.status in {"pushed", "pulled", "synced", "unchanged"}


class GitCommandError(RuntimeError):
    pass


class GitService:
    def __init__(
        self,
        logger: logging.Logger,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.logger = logger
        self._command_runner = command_runner

    @staticmethod
    def discover_repositories(root: Path, recursive: bool = True) -> list[Path]:
        root = root.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Repository folder does not exist: {root}")

        repositories: list[Path] = []
        if (root / ".git").exists():
            repositories.append(root)
        if recursive:
            for current, directories, files in os.walk(root):
                current_path = Path(current)
                if current_path == root and (root / ".git").exists():
                    directories[:] = []
                    continue
                if ".git" in directories or ".git" in files:
                    repositories.append(current_path)
                    directories[:] = []
                else:
                    directories[:] = [d for d in directories if not d.startswith(".")]
        else:
            for child in root.iterdir():
                if child.is_dir() and (child / ".git").exists():
                    repositories.append(child.resolve())
        return sorted(set(repositories), key=lambda path: str(path).lower())

    def push_repository(
        self, repo: Path, commit_template: str, now: datetime | None = None
    ) -> GitOperationResult:
        repo = repo.resolve()
        try:
            remote = self._git(repo, "remote", "get-url", "origin").strip()
            if not self._is_ssh_url(remote):
                raise GitCommandError(
                    f"origin is not an SSH URL ({remote}). Configure an SSH origin first."
                )
            branch = self._current_branch(repo)
            changes = self._git(repo, "status", "--porcelain=v1", "--untracked-files=all")
            if not changes.strip():
                detail = "No local changes; nothing was committed or pushed."
                self.logger.info("UNCHANGED %s - %s", repo, detail)
                return GitOperationResult(repo, "push", "unchanged", detail)

            timestamp = now or datetime.now().astimezone()
            message = commit_template.format(
                date=timestamp.strftime("%Y-%m-%d %H:%M:%S %z"),
                day=timestamp.strftime("%Y-%m-%d"),
                repo=repo.name,
            )
            self._git(repo, "add", "--all")
            self._git(repo, "commit", "-m", message)
            self._git(repo, "push", "origin", f"HEAD:{branch}")
            detail = f"Committed as '{message}' and pushed branch {branch} to origin."
            self.logger.info("PUSHED %s - %s", repo, detail)
            return GitOperationResult(repo, "push", "pushed", detail)
        except (GitCommandError, KeyError, ValueError) as exc:
            detail = str(exc)
            self.logger.error("PUSH FAILED %s - %s", repo, detail)
            return GitOperationResult(repo, "push", "failed", detail)

    def pull_repository(self, repo: Path) -> GitOperationResult:
        repo = repo.resolve()
        try:
            branch = self._current_branch(repo)
            before = self._git(repo, "rev-parse", "HEAD").strip()
            # Fast-forward-only avoids silently creating merge commits during a batch run.
            self._git(repo, "pull", "--ff-only", "origin", branch)
            after = self._git(repo, "rev-parse", "HEAD").strip()
            status = "pulled" if before != after else "unchanged"
            detail = (
                f"Updated branch {branch} ({before[:8]} -> {after[:8]})."
                if status == "pulled"
                else f"Branch {branch} is already up to date."
            )
            self.logger.info("%s %s - %s", status.upper(), repo, detail)
            return GitOperationResult(repo, "pull", status, detail)
        except GitCommandError as exc:
            detail = str(exc)
            self.logger.error("PULL FAILED %s - %s", repo, detail)
            return GitOperationResult(repo, "pull", "failed", detail)

    def sync_repository(self, repo: Path, commit_template: str) -> GitOperationResult:
        """Bring one repository up to date, then publish any local work."""
        repo = repo.resolve()
        try:
            branch = self._current_branch(repo)
            remote = self._git(repo, "remote", "get-url", "origin").strip()
            self._git(repo, "fetch", "origin")
            counts = self._git(
                repo, "rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"
            ).split()
            if len(counts) != 2:
                raise GitCommandError(
                    "Could not determine whether the branch is ahead or behind origin."
                )
            ahead, behind = (int(value) for value in counts)
            if ahead and behind:
                raise GitCommandError(
                    f"Branch {branch} has diverged from origin ({ahead} ahead, {behind} behind); "
                    "resolve it manually."
                )

            pulled = False
            if behind:
                # Pull before committing so a non-conflicting dirty tree can still fast-forward.
                self._git(repo, "pull", "--ff-only", "origin", branch)
                pulled = True

            changes = self._git(repo, "status", "--porcelain=v1", "--untracked-files=all")
            if (ahead or changes.strip()) and not self._is_ssh_url(remote):
                raise GitCommandError(
                    f"origin is not an SSH URL ({remote}). Configure an SSH origin first."
                )
            committed = False
            message = ""
            if changes.strip():
                timestamp = datetime.now().astimezone()
                message = commit_template.format(
                    date=timestamp.strftime("%Y-%m-%d %H:%M:%S %z"),
                    day=timestamp.strftime("%Y-%m-%d"),
                    repo=repo.name,
                )
                self._git(repo, "add", "--all")
                self._git(repo, "commit", "-m", message)
                committed = True

            pushed = bool(ahead or committed)
            if pushed:
                self._git(repo, "push", "origin", f"HEAD:{branch}")

            if pulled and pushed:
                status = "synced"
                detail = f"Pulled and pushed branch {branch}"
            elif pulled:
                status = "pulled"
                detail = f"Pulled branch {branch}"
            elif pushed:
                status = "pushed"
                detail = f"Pushed branch {branch}"
            else:
                status = "unchanged"
                detail = f"Branch {branch} is already up to date"
            if committed:
                detail += f" after committing as '{message}'"
            detail += "."
            self.logger.info("%s %s - %s", status.upper(), repo, detail)
            return GitOperationResult(repo, "sync", status, detail)
        except (GitCommandError, KeyError, ValueError) as exc:
            detail = str(exc)
            self.logger.error("SYNC FAILED %s - %s", repo, detail)
            return GitOperationResult(repo, "sync", "failed", detail)

    def run_many(
        self,
        operation: str,
        repositories: Iterable[Path],
        commit_template: str,
        callback: Callable[[GitOperationResult], None] | None = None,
    ) -> list[GitOperationResult]:
        results = []
        for repo in repositories:
            if operation == "sync":
                result = self.sync_repository(repo, commit_template)
            elif operation == "push":
                result = self.push_repository(repo, commit_template)
            else:
                result = self.pull_repository(repo)
            results.append(result)
            if callback:
                callback(result)
        return results

    def _current_branch(self, repo: Path) -> str:
        branch = self._git(repo, "symbolic-ref", "--short", "HEAD").strip()
        if not branch:
            raise GitCommandError("HEAD is detached; check out a branch first.")
        return branch

    def _git(self, repo: Path, *arguments: str) -> str:
        command: Sequence[str] = ("git", "-C", str(repo), *arguments)
        try:
            completed = self._command_runner(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitCommandError(f"Could not run {' '.join(arguments)}: {exc}") from exc
        if completed.returncode != 0:
            output = (completed.stderr or completed.stdout or "Unknown Git error").strip()
            raise GitCommandError(f"git {' '.join(arguments)} failed: {output}")
        return completed.stdout

    @staticmethod
    def _is_ssh_url(remote: str) -> bool:
        return remote.startswith("ssh://") or (
            ":" in remote and "@" in remote.split(":", 1)[0]
        )


def create_logger(log_dir: Path) -> tuple[logging.Logger, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"git-repo-sync-{datetime.now():%Y-%m-%d}.log"
    logger = logging.getLogger("git_repo_sync")
    logger.setLevel(logging.INFO)
    for old_handler in logger.handlers[:]:
        old_handler.close()
        logger.removeHandler(old_handler)
    logger.propagate = False
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger, log_file
