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

## Notes

- Gist revision history is not carried over (one new commit per file). To keep history, clone the gist and push it instead.
- Existing files are skipped unless "Overwrite" is ticked.
- A gist cannot be emptied through the API, so removing a gist's last file will warn; delete that gist on github.com.
- Files are copied from the gist's latest version.
