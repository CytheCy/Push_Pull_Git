# Git Repo Sync

A small Python/Tkinter desktop app for synchronizing a selected group of Git repositories.

## What it does

- Scans a chosen folder for Git repositories (optionally including nested folders).
- Lets you select all, some, or none of the discovered repositories.
- **Push / Pull selected** fetches each repository and chooses what it needs: a fast-forward-only pull, a push, or both.
- Working-tree changes are staged and committed with a dated message before they are pushed. Existing unpushed commits are detected too.
- Records every result in a dated log file and displays results in the app.
- Requires an SSH `origin` for pushes, such as `git@github.com:owner/project.git`.

The app never force-pushes and never creates automatic merge commits. A repository with a detached HEAD, a conflicting/diverged pull, no `origin`, an HTTPS push URL, or another Git error is reported as failed while the batch continues.

## Requirements

- Python 3.10 or newer with Tkinter
- Git on `PATH`
- GitHub SSH authentication configured (`ssh -T git@github.com` can verify it)
- Git user name and email configured for commits

On Debian/Ubuntu, install Tkinter if needed with `sudo apt install python3-tk`.

## Run

```bash
python3 main.py
```

Choose the folder containing your repositories, click **Scan**, select the desired repositories, and use **Push / Pull selected**. Settings and logs default to `~/.git-repo-sync/`.

Use **Settings… → Appearance** to switch between the light and dark themes. The choice is
saved for future sessions.

The commit template supports `{date}` (local date, time, and UTC offset), `{day}` (`YYYY-MM-DD`), and `{repo}` (folder name).

## Test

```bash
python3 -m unittest discover -s tests -v
```
