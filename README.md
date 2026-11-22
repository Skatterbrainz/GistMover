# Gist Mover

Qt GUI for moving individual GitHub gist files into folders of your repos.

## Run (Linux Mint)

```bash
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python gist_mover.py
```

Run it once like this to set up, or skip all of this and use the [AppImage](#appimage-run-on-other-linux-machines-without-python-or-a-venv).
If Qt reports `Could not load the Qt platform plugin "xcb"`, install the missing library with
`sudo apt install libxcb-cursor0`.

### Desktop launcher script

`run_gist_mover.sh` starts the app from this folder using the `venv` above, adds `~/.local/bin` and
`/usr/local/bin` to `PATH` (so the app can find `gh`), and appends all output to
`~/.cache/gist_mover.log`, the first place to look when a menu launcher "does nothing". Point a
`.desktop` file at it with an absolute path: `Exec=/full/path/to/run_gist_mover.sh`.

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

### Download a prebuilt AppImage

Tagged versions (`v1.0.0`, ...) are built automatically by GitHub Actions
(`.github/workflows/appimage.yml`) and attached to the repo's **Releases** page, along with a `.sha256`
checksum. Download `Gist-Mover-x86_64.AppImage`, then:

```bash
chmod +x Gist-Mover-x86_64.AppImage
./Gist-Mover-x86_64.AppImage
```

No Python, venv or Qt install is needed. See [AppImage requirements](#appimage-requirements) below for
the few things the host still needs (FUSE 2, and `gh` or a token for login).

These builds are made on Ubuntu 22.04, so they run on Linux Mint 21 / Ubuntu 22.04 and newer. They are
x86_64 only.

To publish a new version (maintainer):

```bash
git tag v1.0.0
git push origin v1.0.0
```

To try a build without making a release, open the **Actions** tab, choose **Build AppImage**, and use
**Run workflow**; the AppImage appears as a downloadable artifact on that run.

### Build it yourself

Needs python3 (with the `venv` module) and internet access. Run it once:

```bash
./packaging/build_appimage.sh
```

The script builds in its own temporary venv, bundles the app with PyInstaller, and writes
`Gist-Mover-x86_64.AppImage` (roughly 60-70 MB) into the repo folder. Copy that single file to any other
machine.

PyInstaller bundles only the libraries installed on the build machine, so the script checks that the
bundled Qt X11 plugin has everything it needs and stops with an `apt install` hint if not. On a bare
Debian/Ubuntu/Mint machine, install these first:

```bash
sudo apt install libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1
```

The AppImage is built against the glibc of the machine that built it, so it runs on that distro version
and newer. Build on Mint 22 / Ubuntu 24.04 and it runs on Mint 22 and newer; to support older systems,
build on the oldest one you need.

### AppImage requirements

For a downloaded or a self-built AppImage:
- **FUSE 2** is needed to run any AppImage: `sudo apt install libfuse2t64` on Mint 22 / Ubuntu 24.04, or
  `sudo apt install libfuse2` on Mint 21 / Ubuntu 22.04. Without it, launch with
  `./Gist-Mover-x86_64.AppImage --appimage-extract-and-run`.
- **Display:** it runs through Qt's X11 (xcb) platform and has only been tested on X11.
- **Authentication** is unchanged: set `GITHUB_TOKEN`, or install `gh` and run `gh auth login`, or paste a
  token when prompted. A launcher started from the menu does not see variables from `.bashrc`, so
  `gh auth login` is the easiest route.
- **Menu entry:** copy the AppImage somewhere permanent (e.g. `~/Applications`) and create
  `~/.local/share/applications/gist-mover.desktop` with `Exec=/full/path/Gist-Mover-x86_64.AppImage`.
