# Gist Mover

Qt GUI for moving individual GitHub gist files into folders of your repos.

## Run (Linux Mint)

```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python gist_mover.py
```

## Auth

Uses, in order: `GITHUB_TOKEN` / `GH_TOKEN`, the output of `gh auth token`, or a prompt.
The token needs the `gist` and `repo` scopes (a classic PAT, or the token from `gh auth login`).

## Use

1. Left: tick the gist files to move (ticking a gist ticks all its files; the filter box narrows the list).
2. Right: pick a repo (private-only by default), then a folder, or type a new folder path.
3. Optional: overwrite existing files, remove each file from its gist after copying.
4. **Move checked files.** Each file becomes one commit on the repo's default branch.
   With "Submit as a pull request" ticked, the files go to a new `gist-move-<timestamp>` branch and a
   PR is opened against the default branch (a clickable link appears under the Move button; there is
   also an "Open repo on GitHub" link under the repo list). Gist removal is disabled in PR mode, since
   the files only exist in the PR until it is merged.

## Viewing

Right-click a file in the Gists list and choose **View Contents** to open it in a read-only window
(monospace, with a Copy button; you can open several at once). Large files are cut off at 200,000
characters, and binary files show their size instead. Right-clicking a gist or file also offers
**Open gist on GitHub**.

## Deleting

**Delete checked...** (next to Reload) permanently deletes the checked files from their gists. If every
file in a gist is checked, the whole gist is deleted. A confirmation lists exactly what will go, and
filtered-out (hidden) files are never included. Deleted gists cannot be restored.

## Notes

- Gist revision history is not carried over (one new commit per file). To keep history, clone the gist and push it instead.
- Existing files are skipped unless "Overwrite" is ticked.
- "Remove file from the gist after copying" runs after the whole batch. If every file of a gist was copied
  (GitHub won't remove a gist's last file), the gist itself is deleted; otherwise only the copied files are removed.
- A file already in the repo with identical content counts as copied (so re-running cleans up the gist);
  one that exists but differs is skipped and kept in the gist unless you tick Overwrite.
- Files are copied from the gist's latest version.

## AppImage (run on other Linux machines without Python or a venv)

Build (once, on a machine with python3 and internet access):

```bash
./packaging/build_appimage.sh
```

This creates `Gist-Mover-x86_64.AppImage` (about 70 MB) in the repo folder. Copy that single file to
any other machine, then:

```bash
chmod +x Gist-Mover-x86_64.AppImage
./Gist-Mover-x86_64.AppImage
```

Notes:
- It is built against the glibc of the machine that built it. Build on Linux Mint 22 / Ubuntu 24.04
  and it runs on Mint 22 and newer; for older distros, build on the oldest one you need.
- AppImages need FUSE 2. If it won't start, run `sudo apt install libfuse2t64`, or launch it with
  `./Gist-Mover-x86_64.AppImage --appimage-extract-and-run`.
- Authentication is unchanged: set `GITHUB_TOKEN`, or install `gh` and run `gh auth login`, or paste a
  token when prompted. A launcher started from the menu does not see variables from `.bashrc`, so
  `gh auth login` is the easiest route.
- For a menu entry, copy the AppImage somewhere permanent (e.g. `~/Applications`) and create
  `~/.local/share/applications/gist-mover.desktop` with `Exec=/full/path/Gist-Mover-x86_64.AppImage`.
