#!/usr/bin/env python3
"""Gist Mover - move individual GitHub gist files into a repo folder.

Left panel : your gists and their files (tick the files to move or delete)
Right panel: your repos (writable ones), the repo's folders, target folder box
Move       : copies each ticked file to <repo>/<folder>/<filename>, either as one
             commit per file on the default branch, or on a new branch with a
             pull request. Optionally removes each file from its gist afterwards
             (direct-commit mode only).
Delete     : permanently deletes ticked files from their gists. If every file of
             a gist is ticked, the whole gist is deleted.

Auth (first match wins): GITHUB_TOKEN / GH_TOKEN env var, `gh auth token`,
then a password prompt. The token needs the `gist` and `repo` scopes
(classic PAT, or the token from `gh auth login`).
"""
import base64
import os
import subprocess
import sys
import time
from urllib.parse import quote

import requests
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class GitHub:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gist-mover",
        })

    def _req(self, method, url, **kw):
        if url.startswith("/"):
            url = API + url
        r = self.s.request(method, url, timeout=60, **kw)
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except Exception:
                msg = r.text
            raise GitHubError(r.status_code, msg)
        return r

    def paged(self, url, params=None):
        params = dict(params or {})
        params.setdefault("per_page", 100)
        r = self._req("GET", url, params=params)
        items = []
        while True:
            items.extend(r.json())
            nxt = r.links.get("next")
            if not nxt:
                return items
            r = self._req("GET", nxt["url"])

    def user(self):
        return self._req("GET", "/user").json()

    def gists(self):
        return self.paged("/gists")

    def repos(self):
        return self.paged("/user/repos", {
            "affiliation": "owner,collaborator,organization_member",
            "sort": "full_name",
        })

    def raw(self, url):
        return self._req("GET", url).content

    def dir_tree(self, full, branch):
        """Sorted folder paths, or None if the repo is empty."""
        try:
            r = self._req("GET", f"/repos/{full}/git/trees/{quote(branch, safe='')}",
                          params={"recursive": "1"}).json()
        except GitHubError as e:
            if e.status in (404, 409):
                return None
            raise
        return sorted(t["path"] for t in r.get("tree", []) if t["type"] == "tree")

    def get_sha(self, full, path, branch):
        params = {"ref": branch} if branch else None
        try:
            j = self._req("GET", f"/repos/{full}/contents/{quote(path)}", params=params).json()
        except GitHubError as e:
            if e.status == 404:
                return None
            raise
        return j.get("sha") if isinstance(j, dict) else None

    def put_file(self, full, path, data, message, branch, sha=None):
        body = {"message": message, "content": base64.b64encode(data).decode()}
        if branch:
            body["branch"] = branch
        if sha:
            body["sha"] = sha
        self._req("PUT", f"/repos/{full}/contents/{quote(path)}", json=body)

    # ---- pull requests
    def branch_sha(self, full, branch):
        return self._req("GET", f"/repos/{full}/git/ref/heads/{quote(branch, safe='/')}"
                         ).json()["object"]["sha"]

    def create_branch(self, full, name, sha):
        self._req("POST", f"/repos/{full}/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha})

    def create_pr(self, full, title, head, base, body):
        return self._req("POST", f"/repos/{full}/pulls", json={
            "title": title, "head": head, "base": base, "body": body}).json()["html_url"]

    # ---- gist deletes
    def remove_from_gist(self, gist_id, filename):
        self._req("PATCH", f"/gists/{gist_id}", json={"files": {filename: None}})

    def delete_gist(self, gist_id):
        self._req("DELETE", f"/gists/{gist_id}")


def get_token(parent=None):
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    tok, ok = QInputDialog.getText(
        parent, "GitHub token",
        "Paste a GitHub token (scopes: gist, repo):", QLineEdit.Password)
    return tok.strip() if ok else ""


class Task(QThread):
    """Run fn() off the UI thread."""
    result = Signal(object)
    error = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn())
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class MoveWorker(QThread):
    log = Signal(str)
    moved = Signal(str, str, bool)      # gist_id, filename, removed_from_gist
    pr_created = Signal(str)            # pull request URL
    finished_counts = Signal(int, int, int)

    def __init__(self, gh, jobs, repo, branch, folder, overwrite, delete_src, as_pr=False):
        super().__init__()
        self.gh, self.jobs, self.repo, self.branch = gh, jobs, repo, branch
        self.folder, self.overwrite, self.delete_src = folder, overwrite, delete_src
        self.as_pr = as_pr

    def run(self):
        ok = skipped = failed = 0
        pr_branch = None
        committed = []                  # (target_path, gist_id) for the PR body
        for job in self.jobs:
            if self.isInterruptionRequested():
                self.log.emit("Stopped.")
                break
            gid, desc, name, raw_url = job["id"], job["desc"], job["name"], job["raw_url"]
            target = f"{self.folder}/{name}" if self.folder else name
            try:
                sha = self.gh.get_sha(self.repo, target, self.branch)   # looked up on the base branch
                if sha and not self.overwrite:
                    self.log.emit(f"SKIP  {name} -> {target} (already exists)")
                    skipped += 1
                    continue
                data = self.gh.raw(raw_url)
                if self.as_pr and pr_branch is None:
                    base_sha = self.gh.branch_sha(self.repo, self.branch)
                    pr_branch = "gist-move-" + time.strftime("%Y%m%d-%H%M%S")
                    self.gh.create_branch(self.repo, pr_branch, base_sha)
                    self.log.emit(f"      created branch {pr_branch}")
                commit_branch = pr_branch if self.as_pr else self.branch
                msg = f"Move {name} from gist {gid[:7]}"
                if desc:
                    msg += f"\n\n{desc}"
                msg += f"\n\nSource: https://gist.github.com/{gid}"
                self.gh.put_file(self.repo, target, data, msg, commit_branch, sha)
                where = f"{self.repo}@{pr_branch}" if self.as_pr else self.repo
                self.log.emit(f"OK    {name} -> {where}/{target}")
                ok += 1
                committed.append((target, gid))
                removed = False
                if self.delete_src and not self.as_pr:
                    try:
                        self.gh.remove_from_gist(gid, name)
                        removed = True
                        self.log.emit(f"      removed {name} from gist {gid[:7]}")
                    except GitHubError as e:
                        self.log.emit(f"WARN  copied, but could not remove from gist: {e}")
                self.moved.emit(gid, name, removed)
            except Exception as e:  # noqa: BLE001
                self.log.emit(f"FAIL  {name}: {e}")
                failed += 1

        if self.as_pr and pr_branch and committed:
            try:
                if len(committed) == 1:
                    title = f"Move {os.path.basename(committed[0][0])} from gist {committed[0][1][:7]}"
                else:
                    title = f"Move {len(committed)} files from gists"
                body = "Files moved from GitHub gists:\n\n" + "\n".join(
                    f"- `{t}` (from https://gist.github.com/{g})" for t, g in committed)
                url = self.gh.create_pr(self.repo, title, pr_branch, self.branch, body)
                self.log.emit(f"PR    {url}")
                self.pr_created.emit(url)
            except Exception as e:  # noqa: BLE001
                self.log.emit(f"FAIL  files were pushed to branch {pr_branch}, "
                              f"but the pull request could not be created: {e}")
        self.finished_counts.emit(ok, skipped, failed)


class DeleteWorker(QThread):
    log = Signal(str)
    deleted = Signal(str, object)       # gist_id, filename (None = whole gist)
    finished_counts = Signal(int, int)

    def __init__(self, gh, whole, partial):
        super().__init__()
        self.gh, self.whole, self.partial = gh, whole, partial

    def run(self):
        ok = failed = 0
        for gid, _desc, files in self.whole:
            if self.isInterruptionRequested():
                self.log.emit("Stopped.")
                break
            try:
                self.gh.delete_gist(gid)
                self.log.emit(f"DEL   gist {gid[:7]} ({len(files)} file(s))")
                self.deleted.emit(gid, None)
                ok += 1
            except Exception as e:  # noqa: BLE001
                self.log.emit(f"FAIL  delete gist {gid[:7]}: {e}")
                failed += 1
        for gid, _desc, files in self.partial:
            for name in files:
                if self.isInterruptionRequested():
                    self.log.emit("Stopped.")
                    self.finished_counts.emit(ok, failed)
                    return
                try:
                    self.gh.remove_from_gist(gid, name)
                    self.log.emit(f"DEL   {name} from gist {gid[:7]}")
                    self.deleted.emit(gid, name)
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    self.log.emit(f"FAIL  delete {name} from gist {gid[:7]}: {e}")
                    failed += 1
        self.finished_counts.emit(ok, failed)


class MainWindow(QMainWindow):
    def __init__(self, gh):
        super().__init__()
        self.gh = gh
        self.repos = []
        self.cur_repo = None
        self.cur_branch = None
        self._tasks = set()
        self.worker = None
        self.setWindowTitle("Gist Mover")
        self.resize(1250, 820)

        # ---- left: gists
        self.gist_filter = QLineEdit(placeholderText="Filter gists / files...")
        self.gist_filter.textChanged.connect(self.apply_gist_filter)
        self.gist_tree = QTreeWidget()
        self.gist_tree.setHeaderLabels(["Gists and files", "Size"])
        self.gist_tree.setColumnWidth(0, 450)
        btn_all = QPushButton("Check visible")
        btn_all.clicked.connect(lambda: self.set_visible_checked(Qt.Checked))
        btn_none = QPushButton("Uncheck all")
        btn_none.clicked.connect(lambda: self.set_visible_checked(Qt.Unchecked, everything=True))
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.clicked.connect(self.load_all)
        self.delete_btn = QPushButton("Delete checked...")
        self.delete_btn.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self.delete_btn.setToolTip("Permanently delete the checked files from their gists.\n"
                                   "If all files of a gist are checked, the whole gist is deleted.")
        self.delete_btn.clicked.connect(self.do_delete)
        self.gist_count = QLabel("")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("<b>Gists</b>"))
        lv.addWidget(self.gist_filter)
        lv.addWidget(self.gist_tree)
        row = QHBoxLayout()
        for w in (btn_all, btn_none, self.reload_btn, self.delete_btn):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self.gist_count)
        lv.addLayout(row)

        # ---- right: repos + folders
        self.repo_filter = QLineEdit(placeholderText="Filter repos...")
        self.repo_filter.textChanged.connect(self.apply_repo_filter)
        self.private_only = QCheckBox("Private only")
        self.private_only.setChecked(True)
        self.private_only.toggled.connect(self.apply_repo_filter)
        self.repo_list = QListWidget()
        self.repo_list.currentItemChanged.connect(self.on_repo_selected)
        self.repo_link = QLabel("")
        self.repo_link.setOpenExternalLinks(True)
        self.repo_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabels(["Folders in selected repo"])
        self.folder_tree.currentItemChanged.connect(self.on_folder_selected)
        self.folder_edit = QLineEdit(placeholderText="Target folder (blank = repo root; new folders are fine)")
        self.overwrite = QCheckBox("Overwrite files that already exist in the repo")
        self.as_pr = QCheckBox("Submit as a pull request (new branch) instead of committing directly")
        self.as_pr.toggled.connect(self.on_pr_toggled)
        self.delete_src = QCheckBox("Remove file from the gist after a successful copy")
        self.move_btn = QPushButton("Move checked files  →")
        self.move_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        self.move_btn.clicked.connect(self.do_move)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(lambda: self.worker and self.worker.requestInterruption())
        self.pr_link = QLabel("")
        self.pr_link.setOpenExternalLinks(True)
        self.pr_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("<b>Repositories</b>"))
        rr = QHBoxLayout()
        rr.addWidget(self.repo_filter)
        rr.addWidget(self.private_only)
        rv.addLayout(rr)
        rv.addWidget(self.repo_list, 3)
        rv.addWidget(self.repo_link)
        rv.addWidget(self.folder_tree, 3)
        rv.addWidget(self.folder_edit)
        rv.addWidget(self.overwrite)
        rv.addWidget(self.as_pr)
        rv.addWidget(self.delete_src)
        mr = QHBoxLayout()
        mr.addWidget(self.move_btn, 1)
        mr.addWidget(self.stop_btn)
        rv.addLayout(mr)
        rv.addWidget(self.pr_link)

        top = QSplitter(Qt.Horizontal)
        top.addWidget(left)
        top.addWidget(right)
        top.setSizes([650, 600])
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(5000)
        main = QSplitter(Qt.Vertical)
        main.addWidget(top)
        main.addWidget(self.log)
        main.setSizes([620, 180])
        self.setCentralWidget(main)
        self.statusBar().showMessage("Ready")
        self.load_all()

    # ------------------------------------------------------------ helpers
    def run_task(self, fn, on_result, on_error=None):
        t = Task(fn)
        self._tasks.add(t)
        t.result.connect(on_result)
        t.error.connect(on_error or (lambda m: self.say(f"ERROR {m}")))
        t.finished.connect(lambda: self._tasks.discard(t))
        t.start()

    def say(self, text):
        self.log.appendPlainText(text)

    def set_busy(self, busy):
        for b in (self.move_btn, self.delete_btn, self.reload_btn):
            b.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    def update_gist_count(self):
        n = self.gist_tree.topLevelItemCount()
        files = sum(self.gist_tree.topLevelItem(i).childCount() for i in range(n))
        self.gist_count.setText(f"{n} gists, {files} files")

    def on_pr_toggled(self, on):
        if on:
            self.delete_src.setChecked(False)
        self.delete_src.setEnabled(not on)
        self.delete_src.setToolTip("Not available in pull-request mode: the files only exist in the "
                                   "PR until it is merged. Use 'Delete checked...' after merging."
                                   if on else "")
        self.move_btn.setText("Move checked files as PR  →" if on else "Move checked files  →")

    # ------------------------------------------------------------ loading
    def load_all(self):
        self.statusBar().showMessage("Loading gists and repos...")
        self.gist_tree.clear()
        self.repo_list.blockSignals(True)     # clear() would otherwise "select" a neighbour repo
        self.repo_list.clear()
        self.repo_list.blockSignals(False)
        self.run_task(self.gh.gists, self.fill_gists)
        self.run_task(self.gh.repos, self.fill_repos)

    def fill_gists(self, gists):
        self.gist_tree.clear()
        for g in gists:
            desc = g.get("description") or ""
            vis = "public" if g.get("public") else "secret"
            files = g.get("files", {})
            names = ", ".join(list(files)[:3])
            label = desc or names or g["id"]
            top = QTreeWidgetItem([f"{label}  [{vis}]", ""])
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            top.setCheckState(0, Qt.Unchecked)
            top.setToolTip(0, f"{g['id']}\n{g.get('html_url', '')}")
            top.setData(0, Qt.UserRole, {"id": g["id"], "desc": desc, "label": label})
            for name, f in sorted(files.items()):
                child = QTreeWidgetItem([name, f"{f.get('size', 0):,}"])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                child.setData(0, Qt.UserRole, {"name": name, "raw_url": f["raw_url"]})
                top.addChild(child)
            self.gist_tree.addTopLevelItem(top)
        self.update_gist_count()
        self.apply_gist_filter()
        self.statusBar().showMessage("Ready")

    def fill_repos(self, repos):
        self.repos = [r for r in repos if r.get("permissions", {}).get("push", True)]
        self.apply_repo_filter()

    # ------------------------------------------------------------ filters
    def apply_gist_filter(self):
        q = self.gist_filter.text().strip().lower()
        for i in range(self.gist_tree.topLevelItemCount()):
            top = self.gist_tree.topLevelItem(i)
            top_hit = q in top.text(0).lower() or q in top.data(0, Qt.UserRole)["id"]
            any_child = False
            for j in range(top.childCount()):
                c = top.child(j)
                hit = not q or top_hit or q in c.text(0).lower()
                c.setHidden(not hit)
                any_child = any_child or hit
            top.setHidden(bool(q) and not any_child)
            if q and any_child:
                top.setExpanded(True)

    def apply_repo_filter(self):
        q = self.repo_filter.text().strip().lower()
        priv = self.private_only.isChecked()
        keep = self.cur_repo
        self.repo_list.blockSignals(True)
        self.repo_list.clear()
        match = -1
        for r in self.repos:
            if priv and not r.get("private"):
                continue
            if q and q not in r["full_name"].lower():
                continue
            it = QListWidgetItem(r["full_name"] + ("  \U0001F512" if r.get("private") else ""))
            it.setData(Qt.UserRole, r)
            self.repo_list.addItem(it)
            if r["full_name"] == keep:
                match = self.repo_list.count() - 1
        if match >= 0:
            self.repo_list.setCurrentRow(match)      # keep the highlighted target in sync
        self.repo_list.blockSignals(False)
        if keep and match < 0:                        # target no longer visible: forget it
            self.cur_repo = self.cur_branch = None
            self.repo_link.setText("")
            self.folder_tree.clear()

    def set_visible_checked(self, state, everything=False):
        for i in range(self.gist_tree.topLevelItemCount()):
            top = self.gist_tree.topLevelItem(i)
            if top.isHidden() and not everything:
                continue
            for j in range(top.childCount()):
                c = top.child(j)
                if everything or not c.isHidden():
                    c.setCheckState(0, state)

    # ------------------------------------------------------------ repo / folders
    def on_repo_selected(self, item, _prev=None):
        if not item:
            return
        r = item.data(Qt.UserRole)
        if r["full_name"] != self.cur_repo:      # keep the typed folder when just refreshing
            self.folder_edit.clear()
            self.pr_link.setText("")
        self.cur_repo = r["full_name"]
        self.cur_branch = r.get("default_branch") or "main"
        url = r.get("html_url") or f"https://github.com/{self.cur_repo}"
        self.repo_link.setText(f'<a href="{url}">Open {self.cur_repo} on GitHub</a>')
        self.folder_tree.clear()
        self.statusBar().showMessage(f"Loading folders of {self.cur_repo}...")
        full, branch = self.cur_repo, self.cur_branch

        def done(dirs):
            if full != self.cur_repo:
                return
            if dirs is None:
                self.cur_branch = None      # empty repo: let GitHub create the branch
                dirs = []
                self.say(f"{full} is empty; first commit will create its default branch "
                         "(pull-request mode is unavailable until then).")
            self.populate_folders(dirs)
            self.statusBar().showMessage("Ready")

        self.run_task(lambda: self.gh.dir_tree(full, branch), done)

    def populate_folders(self, dirs):
        self.folder_tree.clear()
        root = QTreeWidgetItem(["/  (repo root)"])
        root.setData(0, Qt.UserRole, "")
        self.folder_tree.addTopLevelItem(root)
        nodes = {"": root}
        for d in dirs:
            parent, _, name = d.rpartition("/")
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.UserRole, d)
            nodes.get(parent, root).addChild(it)
            nodes[d] = it
        root.setExpanded(True)

    def on_folder_selected(self, item, _prev=None):
        if item is not None:
            self.folder_edit.setText(item.data(0, Qt.UserRole))

    # ------------------------------------------------------------ moving
    def checked_jobs(self):
        jobs = []
        for i in range(self.gist_tree.topLevelItemCount()):
            top = self.gist_tree.topLevelItem(i)
            if top.isHidden():
                continue
            meta = top.data(0, Qt.UserRole)
            for j in range(top.childCount()):
                c = top.child(j)
                if c.isHidden() or c.checkState(0) != Qt.Checked:
                    continue
                d = c.data(0, Qt.UserRole)
                jobs.append({"id": meta["id"], "desc": meta["desc"],
                             "name": d["name"], "raw_url": d["raw_url"]})
        return jobs

    def do_move(self):
        jobs = self.checked_jobs()
        if not jobs:
            QMessageBox.information(self, "Nothing to move", "Check at least one gist file first.")
            return
        if not self.cur_repo:
            QMessageBox.information(self, "No repo", "Select a target repository first.")
            return
        as_pr = self.as_pr.isChecked()
        if as_pr and not self.cur_branch:
            QMessageBox.warning(self, "Empty repository",
                                "This repo has no commits yet, so a pull request is impossible. "
                                "Untick the pull-request option for the first commit.")
            return
        folder = self.folder_edit.text().strip().strip("/")
        dest = f"{self.cur_repo}/{folder}" if folder else self.cur_repo
        if as_pr:
            text = f"Copy {len(jobs)} file(s) to {dest} on a new branch and open a pull request?"
        else:
            text = f"Copy {len(jobs)} file(s) to {dest}?"
            if self.delete_src.isChecked():
                text += "\n\nEach file will also be REMOVED from its gist."
        if QMessageBox.question(self, "Confirm", text) != QMessageBox.Yes:
            return
        self.pr_link.setText("")
        self.set_busy(True)
        self.worker = MoveWorker(self.gh, jobs, self.cur_repo, self.cur_branch, folder,
                                 self.overwrite.isChecked(), self.delete_src.isChecked(), as_pr)
        self.worker.log.connect(self.say)
        self.worker.moved.connect(self.on_moved)
        self.worker.pr_created.connect(self.on_pr_created)
        self.worker.finished_counts.connect(self.on_finished)
        self.worker.start()

    def on_pr_created(self, url):
        self.pr_link.setText(f'<a href="{url}">Open pull request on GitHub</a>')

    def find_gist(self, gist_id):
        for i in range(self.gist_tree.topLevelItemCount()):
            top = self.gist_tree.topLevelItem(i)
            if top.data(0, Qt.UserRole)["id"] == gist_id:
                return i, top
        return -1, None

    def on_moved(self, gist_id, name, removed):
        _, top = self.find_gist(gist_id)
        if top is None:
            return
        for j in range(top.childCount()):
            c = top.child(j)
            if c.data(0, Qt.UserRole)["name"] == name:
                if removed:
                    top.removeChild(c)
                else:
                    c.setCheckState(0, Qt.Unchecked)
                break
        self.update_gist_count()

    def on_finished(self, ok, skipped, failed):
        self.set_busy(False)
        self.say(f"Done: {ok} moved, {skipped} skipped, {failed} failed.")
        self.statusBar().showMessage(f"{ok} moved, {skipped} skipped, {failed} failed")
        self.on_repo_selected(self.repo_list.currentItem())   # refresh folder list

    # ------------------------------------------------------------ deleting
    def planned_deletes(self):
        """-> (whole_gists, partial) as lists of (gist_id, label, [filenames])."""
        by_gist = {}
        for j in self.checked_jobs():
            by_gist.setdefault(j["id"], []).append(j["name"])
        whole, partial = [], []
        for i in range(self.gist_tree.topLevelItemCount()):
            top = self.gist_tree.topLevelItem(i)
            meta = top.data(0, Qt.UserRole)
            files = by_gist.get(meta["id"])
            if not files:
                continue
            # only a gist with ALL its files checked (none hidden by a filter) is deleted whole
            (whole if len(files) == top.childCount() else partial).append(
                (meta["id"], meta["label"], files))
        return whole, partial

    def do_delete(self):
        whole, partial = self.planned_deletes()
        if not whole and not partial:
            QMessageBox.information(self, "Nothing to delete", "Check at least one gist file first.")
            return
        lines = []
        if whole:
            lines.append(f"DELETE {len(whole)} ENTIRE gist(s):")
            lines += [f"  • {label}  ({len(files)} file(s))" for _g, label, files in whole]
        if partial:
            n = sum(len(f) for _g, _l, f in partial)
            lines.append(f"Remove {n} file(s) from {len(partial)} gist(s):")
            lines += [f"  • {name}   in {label}" for _g, label, files in partial for name in files]
        if len(lines) > 14:
            lines = lines[:14] + [f"  ... and {len(lines) - 14} more line(s)"]
        text = "\n".join(lines) + "\n\nThis permanently deletes them from GitHub and cannot be undone."
        if QMessageBox.question(self, "Delete from GitHub", text,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.set_busy(True)
        self.worker = DeleteWorker(self.gh, whole, partial)
        self.worker.log.connect(self.say)
        self.worker.deleted.connect(self.on_deleted)
        self.worker.finished_counts.connect(self.on_delete_finished)
        self.worker.start()

    def on_deleted(self, gist_id, name):
        i, top = self.find_gist(gist_id)
        if top is None:
            return
        if name is None:
            self.gist_tree.takeTopLevelItem(i)
        else:
            for j in range(top.childCount()):
                if top.child(j).data(0, Qt.UserRole)["name"] == name:
                    top.removeChild(top.child(j))
                    break
        self.update_gist_count()

    def on_delete_finished(self, ok, failed):
        self.set_busy(False)
        self.say(f"Delete done: {ok} deleted, {failed} failed.")
        self.statusBar().showMessage(f"{ok} deleted, {failed} failed")


def main():
    app = QApplication(sys.argv)
    token = get_token()
    if not token:
        return 1
    gh = GitHub(token)
    try:
        me = gh.user()
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(None, "GitHub login failed", str(e))
        return 1
    w = MainWindow(gh)
    w.setWindowTitle(f"Gist Mover - {me.get('login', '')}")
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())