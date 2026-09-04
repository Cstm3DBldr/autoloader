# Install flow — what an SSH session actually asks you

```bash
cd ~ && git clone https://github.com/Cstm3DBldr/autoloader.git && ~/autoloader/install.sh
```

**Two prompts, at most.** Everything else runs unattended. Both are marked ★
below. A third can appear if `git pull` needs credentials or hits local edits.

```mermaid
flowchart TD
    START([ssh pi@printer<br/>./install.sh]) --> UNINST{--uninstall?}

    UNINST -->|yes| U1[unlink 6 Klipper extras<br/>unlink Moonraker component<br/>remove KS panels + conf]
    U1 --> U2[/copy aside to<br/>~/autoloader-config-backup-EPOCH:<br/>variables.cfg · user.cfg<br/>leds/ · filament_profiles//]
    U2 --> U3[rm -rf config/autoloader<br/>remove update_manager entry]
    U3 --> UEND([exit 0<br/>manual: remove the include<br/>from printer.cfg])

    UNINST -->|no| ROOT{running as root?}
    ROOT -->|yes| ERR1([ERROR: do not run as root<br/>exit 1]):::err
    ROOT -->|no| PULL[git pull origin main<br/>⚠ may prompt for credentials]
    PULL --> LINK[symlink 6 Klipper extras<br/>symlink Moonraker component]
    LINK --> PU[run post_update.sh:<br/>copy cfg + html + KS panels<br/>ship examples/ · create empty leds/]
    PU --> UEX{user.cfg exists?}

    UEX -->|no| CREATE[create it — no prompt]
    UEX -->|yes| ENV{SA_USER_CFG set?}

    ENV -->|invalid value| ERR2([ERROR: must be keep,<br/>upgrade or overwrite<br/>exit 1]):::err
    ENV -->|keep / upgrade / overwrite| ACT
    ENV -->|not set| TTY{stdin a terminal?}

    TTY -->|no| KEEPD[keep — safe default<br/>a scripted run never destroys settings]
    TTY -->|yes| ASK[★ PROMPT<br/>Choice k/u/o]:::ask

    ASK --> ACT{which?}
    KEEPD --> REG
    ACT -->|k keep| K[leave it untouched]
    ACT -->|u upgrade| UPG[append only SA-BLOCKs it lacks<br/>never edits your own lines]
    ACT -->|o overwrite| OVR[back up to user.cfg.bak.EPOCH<br/>then write fresh]

    CREATE --> REG
    K --> REG
    UPG --> REG
    OVR --> REG

    REG[write update_manager/autoloader.ini] --> SUDO[★ PROMPT<br/>sudo password<br/>restart klipper · moonraker · KlipperScreen]:::ask
    SUDO --> DONE([✓ complete])
    DONE --> M1[/manual: add<br/>include autoloader/autoloader.cfg<br/>to printer.cfg/]
    M1 --> M2[/manual: run<br/>scripts/verify.sh/]

    classDef err fill:#7f1d1d,stroke:#ef4444,color:#fff
    classDef ask fill:#78350f,stroke:#f59e0b,color:#fff
```

## The prompts in detail

### ★ 1 — `user.cfg` already exists

Only fires on a **re-install**. `user.cfg` holds your LED switch and any
`[autoloader]` values you moved there to protect them from `post_update.sh`, so
the installer will not touch it without asking.

```
[INSTALL] .../user.cfg already exists.
          It may hold settings that override parameters.cfg.

            k) Keep it as it is                      (default, safe)
            u) Upgrade — append only blocks it is missing, change nothing else
            o) Overwrite — back the current one up first

          Choice [k/u/o]:
```

| answer | effect |
|---|---|
| `k` | nothing changes |
| `u` | appends only marker-fenced blocks your file lacks, under a dated banner. Never removes, reorders, or edits a line you wrote |
| `o` | copies to `user.cfg.bak.<epoch>` first, then writes a fresh template |

Skip it entirely with `SA_USER_CFG=keep|upgrade|overwrite`. **With no terminal
attached it keeps** — a piped or scripted run must never destroy settings by
falling through a prompt nobody answered.

### ★ 2 — sudo password

For `systemctl restart klipper / moonraker / KlipperScreen`. Not asked on a
machine with passwordless sudo for those units.

### ⚠ possible — git

`git pull origin main` can ask for credentials on a private remote, or stop on
local edits to tracked files.

## What is never prompted, and is safe anyway

- **Your calibration.** `variables.cfg` — every bowden length, encoder
  mm/pulse and selector position — is not in the repo, so no install or update
  writes it. Uninstall copies it aside before removing anything.
- **Your LED config.** `leds/` is created empty and never written again.
- **Your `user.cfg`.** Written once; after that only with your answer above.

Everything else under `~/printer_data/config/autoloader/` **is** replaced on
every update. That is what `user.cfg` is for.
