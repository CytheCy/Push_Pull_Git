from __future__ import annotations

import logging
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from git_repo_sync.git_service import GitService


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str, str]]) -> None:
        self.responses = responses
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command, **kwargs):
        args = tuple(command[3:])
        self.commands.append(args)
        code, stdout, stderr = self.responses.get(args, (0, "", ""))
        return subprocess.CompletedProcess(command, code, stdout, stderr)


class DiscoveryTests(unittest.TestCase):
    def test_discovers_nested_repositories_without_descending_into_them(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "alpha" / ".git").mkdir(parents=True)
            (root / "group" / "beta" / ".git").mkdir(parents=True)
            (root / "alpha" / "fake" / ".git").mkdir(parents=True)
            found = GitService.discover_repositories(root)
            self.assertEqual(found, [root / "alpha", root / "group" / "beta"])

    def test_non_recursive_scan_only_finds_direct_children(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "alpha" / ".git").mkdir(parents=True)
            (root / "group" / "beta" / ".git").mkdir(parents=True)
            self.assertEqual(GitService.discover_repositories(root, False), [root / "alpha"])


class PushTests(unittest.TestCase):
    def test_push_stages_commits_and_pushes_changed_repo(self) -> None:
        responses = {
            ("remote", "get-url", "origin"): (0, "git@github.com:me/repo.git\n", ""),
            ("symbolic-ref", "--short", "HEAD"): (0, "main\n", ""),
            ("status", "--porcelain=v1", "--untracked-files=all"): (0, " M file.txt\n", ""),
        }
        runner = FakeRunner(responses)
        service = GitService(logging.getLogger("test-push"), runner)
        now = datetime(2026, 9, 11, 13, 30, tzinfo=timezone.utc)
        result = service.push_repository(Path("/tmp/repo"), "Sync {day} {repo}", now)
        self.assertEqual(result.status, "pushed")
        self.assertIn(("add", "--all"), runner.commands)
        self.assertIn(("commit", "-m", "Sync 2026-09-11 repo"), runner.commands)
        self.assertIn(("push", "origin", "HEAD:main"), runner.commands)

    def test_push_refuses_https_remote(self) -> None:
        runner = FakeRunner({
            ("remote", "get-url", "origin"): (0, "https://github.com/me/repo.git\n", "")
        })
        result = GitService(logging.getLogger("test-https"), runner).push_repository(
            Path("/tmp/repo"), "Sync {date}"
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("not an SSH URL", result.detail)
        self.assertEqual(len(runner.commands), 1)

    def test_unchanged_repo_is_not_pushed(self) -> None:
        runner = FakeRunner({
            ("remote", "get-url", "origin"): (0, "git@github.com:me/repo.git\n", ""),
            ("symbolic-ref", "--short", "HEAD"): (0, "main\n", ""),
            ("status", "--porcelain=v1", "--untracked-files=all"): (0, "", ""),
        })
        result = GitService(logging.getLogger("test-clean"), runner).push_repository(
            Path("/tmp/repo"), "Sync {date}"
        )
        self.assertEqual(result.status, "unchanged")
        self.assertFalse(any(command[0] == "push" for command in runner.commands))


class PullTests(unittest.TestCase):
    def test_pull_uses_fast_forward_only_and_reports_update(self) -> None:
        responses = {
            ("symbolic-ref", "--short", "HEAD"): (0, "main\n", ""),
            ("rev-parse", "HEAD"): (0, "1111111111111111\n", ""),
        }
        runner = FakeRunner(responses)
        revision_calls = 0

        def changing_runner(command, **kwargs):
            nonlocal revision_calls
            args = tuple(command[3:])
            runner.commands.append(args)
            if args == ("rev-parse", "HEAD"):
                revision_calls += 1
                value = "1111111111111111\n" if revision_calls == 1 else "2222222222222222\n"
                return subprocess.CompletedProcess(command, 0, value, "")
            code, stdout, stderr = responses.get(args, (0, "", ""))
            return subprocess.CompletedProcess(command, code, stdout, stderr)

        result = GitService(logging.getLogger("test-pull"), changing_runner).pull_repository(
            Path("/tmp/repo")
        )
        self.assertEqual(result.status, "pulled")
        self.assertIn(("pull", "--ff-only", "origin", "main"), runner.commands)

    def test_detached_head_is_reported_without_pull(self) -> None:
        runner = FakeRunner({
            ("symbolic-ref", "--short", "HEAD"): (1, "", "fatal: ref HEAD is not a symbolic ref")
        })
        result = GitService(logging.getLogger("test-detached"), runner).pull_repository(
            Path("/tmp/repo")
        )
        self.assertEqual(result.status, "failed")
        self.assertFalse(any(command[0] == "pull" for command in runner.commands))


if __name__ == "__main__":
    unittest.main()
