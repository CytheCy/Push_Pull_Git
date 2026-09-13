from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .git_service import GitOperationResult, GitService, create_logger
from .settings import AppSettings


class GitRepoSyncApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Git Repo Sync")
        self.geometry("860x620")
        self.minsize(700, 500)
        self.settings = AppSettings.load()
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self._apply_theme()
        self.repo_root = tk.StringVar(value=self.settings.repo_root)
        self.recursive = tk.BooleanVar(value=self.settings.recursive)
        self.status_text = tk.StringVar(value="Choose a folder, then scan for repositories.")
        self.repositories: list[Path] = []
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False
        self._build_ui()
        self._apply_theme()
        self.after(100, self._process_events)
        if self.settings.repo_root and Path(self.settings.repo_root).is_dir():
            self.after(150, self.scan)

    def _apply_theme(self) -> None:
        dark = self.settings.appearance == "dark"
        colors = {
            "background": "#242424" if dark else "#f4f4f4",
            "field": "#303030" if dark else "#ffffff",
            "foreground": "#f2f2f2" if dark else "#202020",
            "muted": "#b8b8b8" if dark else "#555555",
            "button": "#3a3a3a" if dark else "#e5e5e5",
            "active": "#4a4a4a" if dark else "#d6d6d6",
            "border": "#5c5c5c" if dark else "#b8b8b8",
            "selection": "#4778c7" if dark else "#2f6fda",
            "selection_text": "#ffffff",
        }
        self.configure(background=colors["background"])
        self.option_add("*Toplevel.background", colors["background"])
        self.style.configure(
            ".",
            background=colors["background"],
            foreground=colors["foreground"],
            bordercolor=colors["border"],
            darkcolor=colors["border"],
            lightcolor=colors["border"],
            troughcolor=colors["background"],
        )
        self.style.configure("TFrame", background=colors["background"])
        self.style.configure(
            "TLabel", background=colors["background"], foreground=colors["foreground"]
        )
        self.style.configure(
            "TButton",
            background=colors["button"],
            foreground=colors["foreground"],
            bordercolor=colors["border"],
            focusthickness=2,
            focuscolor=colors["selection"],
        )
        self.style.map(
            "TButton",
            background=[("active", colors["active"]), ("pressed", colors["selection"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.style.configure(
            "TCheckbutton", background=colors["background"], foreground=colors["foreground"]
        )
        self.style.map("TCheckbutton", background=[("active", colors["background"])])
        self.style.configure(
            "TEntry",
            fieldbackground=colors["field"],
            foreground=colors["foreground"],
            insertcolor=colors["foreground"],
            bordercolor=colors["border"],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=colors["field"],
            background=colors["button"],
            foreground=colors["foreground"],
            arrowcolor=colors["foreground"],
            bordercolor=colors["border"],
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", colors["field"])],
            foreground=[("readonly", colors["foreground"])],
            selectbackground=[("readonly", colors["field"])],
            selectforeground=[("readonly", colors["foreground"])],
        )
        self.option_add("*TCombobox*Listbox.background", colors["field"])
        self.option_add("*TCombobox*Listbox.foreground", colors["foreground"])
        self.option_add("*TCombobox*Listbox.selectBackground", colors["selection"])
        self.option_add("*TCombobox*Listbox.selectForeground", colors["selection_text"])

        repo_list = getattr(self, "repo_list", None)
        if repo_list is not None:
            repo_list.configure(
                background=colors["field"],
                foreground=colors["foreground"],
                selectbackground=colors["selection"],
                selectforeground=colors["selection_text"],
            )
        output = getattr(self, "output", None)
        if output is not None:
            output.configure(
                background=colors["field"],
                foreground=colors["foreground"],
                selectbackground=colors["selection"],
                selectforeground=colors["selection_text"],
                insertbackground=colors["foreground"],
            )

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Repository folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(container, textvariable=self.repo_root).grid(
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(container, text="Browse…", command=self._browse).grid(row=1, column=1)
        ttk.Button(container, text="Scan", command=self.scan).grid(row=1, column=2, padx=(8, 0))

        options = ttk.Frame(container)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        ttk.Checkbutton(options, text="Search subfolders", variable=self.recursive).pack(side="left")
        ttk.Button(options, text="Select all", command=self._select_all).pack(side="right")
        ttk.Button(options, text="Clear selection", command=self._clear_selection).pack(
            side="right", padx=8
        )

        list_frame = ttk.Frame(container)
        list_frame.grid(row=3, column=0, columnspan=3, sticky="nsew")
        self.repo_list = tk.Listbox(
            list_frame, selectmode=tk.EXTENDED, activestyle="dotbox", exportselection=False
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.repo_list.yview)
        self.repo_list.configure(yscrollcommand=scrollbar.set)
        self.repo_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        actions = ttk.Frame(container)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=12)
        self.sync_button = ttk.Button(actions, text="Push / Pull selected", command=self._run)
        self.sync_button.pack(side="left")
        ttk.Button(actions, text="Settings…", command=self._show_settings).pack(side="right")

        ttk.Label(container, textvariable=self.status_text).grid(
            row=5, column=0, columnspan=3, sticky="w"
        )
        self.output = tk.Text(container, height=10, state="disabled", wrap="word")
        self.output.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(6, 0))

        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=3)
        container.rowconfigure(6, weight=2)

    def _browse(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.repo_root.get() or str(Path.home()))
        if selected:
            self.repo_root.set(selected)
            self.scan()

    def scan(self) -> None:
        try:
            self.repositories = GitService.discover_repositories(
                Path(self.repo_root.get()), self.recursive.get()
            )
        except ValueError as exc:
            messagebox.showerror("Cannot scan folder", str(exc), parent=self)
            return
        self.repo_list.delete(0, tk.END)
        root = Path(self.repo_root.get()).expanduser().resolve()
        for repo in self.repositories:
            try:
                label = str(repo.relative_to(root)) or repo.name
            except ValueError:
                label = str(repo)
            self.repo_list.insert(tk.END, label if label != "." else repo.name)
        self._select_all()
        self.settings.repo_root = str(root)
        self.settings.recursive = self.recursive.get()
        self.settings.save()
        self.status_text.set(f"Found {len(self.repositories)} Git repositories; all are selected.")

    def _select_all(self) -> None:
        self.repo_list.selection_set(0, tk.END)

    def _clear_selection(self) -> None:
        self.repo_list.selection_clear(0, tk.END)

    def _run(self) -> None:
        indices = self.repo_list.curselection()
        if not indices:
            messagebox.showinfo("Nothing selected", "Select at least one repository.", parent=self)
            return
        repositories = [self.repositories[index] for index in indices]
        if not messagebox.askyesno(
            "Confirm push / pull",
            f"Synchronize {len(repositories)} selected repositories with origin?\n\n"
            "This may pull updates or stage, commit, and push local changes as needed.",
            parent=self,
        ):
            return
        self._set_busy(True)
        self._append_output(f"\nSYNC started for {len(repositories)} repositories…\n")
        thread = threading.Thread(
            target=self._worker, args=(repositories,), daemon=True
        )
        thread.start()

    def _worker(self, repositories: list[Path]) -> None:
        try:
            logger, log_file = create_logger(Path(self.settings.log_dir).expanduser())
            service = GitService(logger)
            results = service.run_many(
                "sync",
                repositories,
                self.settings.commit_template,
                callback=lambda result: self.events.put(("result", result)),
            )
            self.events.put(("done", (results, log_file)))
        except Exception as exc:  # Keep unexpected worker errors from killing the UI thread.
            self.events.put(("fatal", exc))

    def _process_events(self) -> None:
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "result":
                    result = value
                    assert isinstance(result, GitOperationResult)
                    self._append_output(
                        f"[{result.status.upper()}] {result.repo.name}: {result.detail}\n"
                    )
                elif event == "done":
                    results, log_file = value
                    failures = sum(not result.successful for result in results)
                    self.status_text.set(
                        f"Finished: {len(results) - failures} succeeded, {failures} failed. "
                        f"Log: {log_file}"
                    )
                    self._set_busy(False)
                elif event == "fatal":
                    self._set_busy(False)
                    messagebox.showerror("Operation failed", str(value), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _append_output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert(tk.END, text)
        self.output.see(tk.END)
        self.output.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.sync_button.configure(state=state)
        if busy:
            self.status_text.set("Git operation in progress…")

    def _show_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Settings")
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        log_dir = tk.StringVar(value=self.settings.log_dir)
        template = tk.StringVar(value=self.settings.commit_template)
        appearance = tk.StringVar(value=self.settings.appearance.title())
        ttk.Label(frame, text="Log folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=log_dir, width=58).grid(row=1, column=0, sticky="ew")
        ttk.Button(
            frame,
            text="Browse…",
            command=lambda: self._choose_log_folder(log_dir),
        ).grid(row=1, column=1, padx=(8, 0))
        ttk.Label(frame, text="Commit message template").grid(
            row=2, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Entry(frame, textvariable=template, width=58).grid(row=3, column=0, columnspan=2, sticky="ew")
        ttk.Label(frame, text="Available fields: {date}, {day}, {repo}").grid(
            row=4, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, text="Appearance").grid(
            row=5, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Combobox(
            frame,
            textvariable=appearance,
            values=("Light", "Dark"),
            state="readonly",
            width=16,
        ).grid(row=6, column=0, sticky="w")

        def save() -> None:
            try:
                template.get().format(date="date", day="day", repo="repo")
            except (KeyError, ValueError) as exc:
                messagebox.showerror("Invalid template", str(exc), parent=dialog)
                return
            self.settings.log_dir = log_dir.get()
            self.settings.commit_template = template.get()
            self.settings.appearance = appearance.get().lower()
            self.settings.save()
            self._apply_theme()
            dialog.destroy()

        ttk.Button(frame, text="Cancel", command=dialog.destroy).grid(
            row=7, column=0, sticky="e", pady=(16, 0)
        )
        ttk.Button(frame, text="Save", command=save).grid(
            row=7, column=1, sticky="e", pady=(16, 0)
        )

    def _choose_log_folder(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(initialdir=variable.get(), parent=self)
        if selected:
            variable.set(selected)


def main() -> None:
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        raise SystemExit("Git is not installed or is not available on PATH.")
    app = GitRepoSyncApp()
    app.mainloop()
