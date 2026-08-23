# upd

A rich, parallel, multi-level updater for Apple Silicon macOS — the system, your
package managers, your language toolchains and your shell, in one command, with
a legible record of what happened.

```
upd all
```

```
╭──────────────────────────────── 󰚱 upd  macOS updater ─────────────────────────────────╮
│     host  bbmbp  ·  arm64                                                             │
│    macOS  26.5.2                                                                      │
│     brew  /opt/homebrew                                                               │
│  started  2026-08-23 12:41:23                                                         │
│     mode  live  ·  4 jobs                                                             │
╰──────────────────────────────────── upd 0.1.0 ────────────────────────────────────────╯
```

---

## Why

Keeping a Mac current means running a dozen unrelated commands in a fixed order
and reading a dozen different flavours of output. `upd` does that work
concurrently, shows one progress line per module while it runs, and finishes
with a single table saying what succeeded, what was skipped and why, and what
needs your attention. Every command's full output goes to a log file, so the
terminal stays readable without losing anything.

## Highlights

| | |
|---|---|
| **Multi-level subcommands** | `upd <group> <module>` — `upd pkg brew`, `upd system xprotect`, or just `upd all` |
| **Parallel with lanes** | Modules run concurrently; those sharing a lock (`brew`, `python`, `node`, `zsh`) are serialised against each other automatically |
| **Safe by default** | Nothing reboots, nothing scrubs a cache and nothing upgrades a self-updating cask unless you ask with `--greedy` / `--include-restart` |
| **Password-less root** | Uses `/usr/local/sbin/xlog` when it is available; falls back to `sudo`, primed once up front so parallel workers never race for the prompt |
| **Honest dry runs** | `--dry-run` prints the exact argv of every command, syntax-highlighted, and executes nothing |
| **Detects, never guesses** | A module that does not apply to your machine says so, with the reason |
| **Real logs** | `~/.local/state/upd/logs/<timestamp>/<group>.<module>.log`, one per module |

## Install

Requires [uv](https://docs.astral.sh/uv/) and macOS on Apple Silicon.

```bash
git clone git@github.com:bhaskarbhaumik/cli-upd.git
cd cli-upd
make install                     # → ~/.local/bin/upd
make install DESTDIR=/usr/local/bin   # anywhere else
```

`make install` builds a wheel, installs it into an isolated `uv tool`
environment, and links the launcher into `DESTDIR`.

For hacking on it, `make install-symlink` writes a launcher that runs straight
from the checkout instead — no rebuild between edits.

## Usage

```
upd all                       run every applicable module, safely
upd all --dry-run             show exactly what would run, run nothing
upd pkg brew mas              update Homebrew and the App Store only
upd system --include-restart  install macOS updates that reboot the machine
upd all --greedy -j 8         upgrade auto-updating casks, 8 modules at a time
upd run brew omz python       an arbitrary mix, across groups
upd list                      what upd knows how to update on this machine
upd doctor                    check escalation, tooling and configuration
upd logs                      where the last few runs wrote their logs
```

### Flags that matter

| Flag | Effect |
|---|---|
| `-n`, `--dry-run` | Print each command instead of running it. Implies `--serial`. |
| `-j N`, `--jobs N` | Modules in flight at once. Default 4. |
| `-1`, `--serial` | One module at a time. |
| `--greedy` | `brew upgrade --greedy`, `brew cleanup --scrub`, `softwareupdate --all`. |
| `--include-restart` | Permit updates that reboot the machine. Prompts unless `--yes`. |
| `--no-root` | Never escalate; skip every module that needs root. |
| `--escalate xlog\|sudo` | Force a specific escalation backend. |
| `--skip MODULE` | Exclude a module. Repeatable. |
| `-v` / `-vv` | Show output for successful modules / stream it live (serial runs). |
| `--ascii` | Plain markers instead of Nerd Font glyphs. |

Global flags work before or after the subcommand: `upd -n pkg brew` and
`upd pkg brew -n` are the same thing.

### Exit codes

`0` everything fine · `1` at least one module failed · `2` bad usage ·
`130` interrupted.

## Modules

Run `upd list` for the live view, annotated with what applies to *your*
machine. The full set:

### `system` — macOS itself

| Module | What it does | Root |
|---|---|:-:|
| `macos` | `softwareupdate` — recommended updates by default, all with `--greedy` | ● |
| `critical` | Background critical / config-data updates | ● |
| `xprotect` | XProtect malware definitions, plus version and subsystem status | ● |
| `rosetta` | Install or refresh Rosetta 2 | ● |
| `xcode` | Finds and installs the newest Command Line Tools package | ● |
| `msupdate` | Microsoft AutoUpdate — Office and friends. Runs as *you*, not root | |
| `gatekeeper` | Reports Gatekeeper, SIP and FileVault state. Opt-in, read-only | |
| `locatedb` | Rebuilds the `locate(1)` database. Opt-in, slow | ● |

### `pkg` — package managers

`brew` (update → upgrade → autoremove → cleanup → doctor → missing) ·
`mas` (App Store) · `pipx` · `uvtool` (uv tools + cache) · `npm` · `pnpm` ·
`bun` · `gem` · `gcloud` · `az` · `gh` (extensions) · `tldr` ·
`vscode` (opt-in) · `ollama` (opt-in)

### `dev` — language toolchains

`python` (uv interpreters, pyenv) · `conda` · `node` (fnm/volta/nvm/n +
corepack) · `rust` (rustup, cargo-update) · `ruby` (rbenv) · `java` (SDKMAN!) ·
`go` (opt-in, via `gup`)

### `shell` — shell and dotfiles

`omz` (oh-my-zsh) · `plugins` (custom plugin and theme checkouts) ·
`repos` (git checkouts you list in the config) ·
`caches` (bat, fzf, `.zcompdump`)

**Opt-in modules** are excluded from `upd all`. Name one explicitly
(`upd pkg ollama`) or add it to `enable` in the config file.

## How root works

1. **`/usr/local/sbin/xlog`** — a set-uid helper granting password-less root.
   `upd` probes it by running `xlog /usr/bin/id -u` and checking for `0`.
2. **`/usr/bin/sudo`** — the fallback. Because modules run in parallel, `upd`
   primes the sudo timestamp once, serially (`sudo -v`), before any worker
   starts; workers then use `sudo -n` and can never block on a hidden prompt.
3. **Neither available** — root modules are skipped with a reason, and the run
   continues.

`upd doctor` reports which backend is in play.

## Configuration

Optional, at `~/.config/upd/config.toml`. Create a commented template with:

```bash
upd config init
upd config edit
```

```toml
[run]
jobs = 4
greedy = false
include_restart = false
tail_lines = 12
timeout = 3600

[ui]
theme = "the_lawn"     # rich-argparse-plus help theme
ascii = false

[modules]
skip = ["mas"]          # never run these
enable = ["ollama"]     # run these despite being opt-in

[shell]
repos = ["~/opt/open-webui/open-webui"]

[brew]
upgrade_args = []
doctor = true
autoremove = true
```

## Development

```bash
make help          # every target, with the resolved variables
make check         # byte-compile everything
make lint / fmt    # ruff
make smoke         # doctor + a full dry run, from source
make test          # check + smoke
make build         # wheel + sdist into dist/
make reinstall     # uninstall, rebuild, reinstall
```

Repository management, through `gh` and `git`:

```bash
make repo          # create the private GitHub repo and wire up origin
make commit MSG="feat: add rust module"
make push
make tag           # tag v$(VERSION)
make release       # test, build, tag, publish a GitHub release
```

### Adding a module

Modules are declarative. Drop this in the right file under
`src/upd/modules/` and it appears in `upd list`, `upd <group>`, and `upd all`:

```python
@module(
    name="cargo",
    group="dev",
    title="Cargo binaries",
    summary="Refresh binaries installed with cargo install",
    icon="rust",
    lane="rust",              # serialised against other rust-lane modules
    requires=("cargo",),      # every executable must be on PATH
    order=45,
)
def cargo(ctx: Context) -> Iterator[Step]:
    return iter(
        StepList().add(
            "Update cargo-installed binaries",
            ["cargo", "install-update", "--all"],
            allow_fail=True,
            timeout=10800,
        )
    )
```

`ctx` carries the resolved run options (`ctx.greedy`, `ctx.verbose`,
`ctx.config`, …), so a module can shape its own argv rather than declaring
every variant.

## Layout

```
src/upd/
├── cli.py            argparse tree, dispatch, exit codes
├── registry.py       Step / Module model, the registry, lanes
├── context.py        resolved run options and machine facts
├── config.py         ~/.config/upd/config.toml
├── privilege.py      xlog → sudo escalation
├── runner.py         spawn, stream, capture, time, classify
├── orchestrator.py   thread pool, lane locks, cancellation
├── console.py        theme and glyph sets
├── ui.py             every panel, table and progress display
└── modules/
    ├── system.py     macOS, XProtect, Rosetta, CLT, MAU
    ├── packages.py   brew, mas, pipx, uv, npm, gem, cloud CLIs
    ├── dev.py        python, node, rust, go, ruby, java, conda
    └── shell.py      oh-my-zsh, plugins, repos, caches
```

`reference/` holds the original zsh scripts this replaces. They are kept for
provenance, not as a specification.

## License

MIT — see [LICENSE](LICENSE).
