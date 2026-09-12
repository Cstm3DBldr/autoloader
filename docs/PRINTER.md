# The printer — access, observation, and sharing it

**Project-neutral. Copy this file into any repo that touches this machine.**
Nothing here is specific to the Autoloader except where it says so, and the
sections that are get marked.

**This is a map, not a snapshot.** It describes the machine as of 2026-09-11.
Anything it claims about what is installed, which branch is live or what a
config holds should be **re-read from the machine** before it is relied on —
especially once a second project starts changing things. The access routes and
the gotchas are the durable part; the inventory is not.

---

## Access

**No secrets, and none are needed.** Every route is key-based or
unauthenticated on the LAN. No password, token or private key needs reading,
storing or typing. If a session finds itself needing one, that is new — stop
and ask rather than go hunting.

| What | Address | Auth |
|---|---|---|
| The printer (Voron StealthChanger, `sc350`) | `ssh pi@192.168.1.214` | SSH key, `BatchMode=yes` |
| Moonraker REST | `http://192.168.1.214:7125` | none, LAN only |
| Mainsail | `http://192.168.1.214/` | none |
| UI testbench (an Ender, no autoloader hardware) | `ssh biqu@192.168.1.75` | SSH key |

### Two gotchas that waste an hour each

**ssh prints a post-quantum warning on every call.** It is noise, not a
failure, and it appears on stderr for every command. Filter it or output is
unreadable:

```
2>&1 | grep -v "post-quantum\|store now\|may need\|^\*\*"
```

**scp needs `-O`.** OpenSSH 9+ defaults to the SFTP protocol and this sshd
closes on it. The error is `scp: Connection closed`, which names neither the
transport nor the cause and reads like an unreachable host — directly after a
successful `ssh` to the same box.

---

## Observing it without screenshots

This is the single most useful thing to know. Moonraker exposes the console,
so there is no need to ask anyone to photograph a screen.

**The console, as JSON:**

```
curl -s "http://192.168.1.214:7125/server/gcode_store?count=60"
```

Returns `result.gcode_store[]`, each with `time`, `type` (`command` or
`response`) and `message`. Filter the `B:…T0:…` temperature lines or they
drown everything else.

**Send a command:**

```
curl -s -X POST "http://192.168.1.214:7125/printer/gcode/script?script=STATUS"
```

It blocks until the gcode finishes, so a long operation needs a generous
timeout — or fire it and poll `idle_timeout` instead.

**Read live state:**

```
curl -s "http://192.168.1.214:7125/printer/objects/query?toolhead&print_stats&idle_timeout"
```

**Is it busy?** `idle_timeout.state` is `Printing` during *any* gcode, not just
a print job. `print_stats.state` is the one that means a real print.

**Is it healthy?**

```
curl -s "http://192.168.1.214:7125/printer/info"
```

`state` is `ready`, `error` or `shutdown`, and `state_message` says why.

**Sensors are their own objects.** A `filament_switch_sensor foo` is queried as
`printer/objects/query?filament_switch_sensor%20foo` and carries
`filament_detected`. They are not fields on any project's status object.

---

## Restarting the right thing

| Change | What reloads it |
|---|---|
| a `.cfg` under `printer_data/config` | `FIRMWARE_RESTART` |
| a Python file in `klipper/klippy/extras/` | **service restart** — `FIRMWARE_RESTART` will NOT |
| a KlipperScreen panel | KlipperScreen service restart |
| an MCU shutdown (`Timer too close`, emergency stop) | `FIRMWARE_RESTART` |

**`FIRMWARE_RESTART` does not reload Python extras.** It re-parses the config
and resets the MCUs; the running klippy process keeps every module it imported
at startup. This has cost days before — code was deployed, the restart was
reported, and the old module kept running.

**`sudo systemctl restart` over ssh fails silently.** Without a terminal it
returns "a terminal is required to read the password" and exit 1, which paired
with a `2>/dev/null` is a restart that reports nothing and does nothing.
KlipperScreen ran for two days on two-day-old code that way. Go through
Moonraker's `/machine/services/restart` instead — the Autoloader repo wraps
that in `scripts/klipper_service_restart.sh` and `scripts/service_restart.sh`,
and the second one also checks the PID actually changed, because KlipperScreen's
MainPID is a launcher and the process holding the panels is a grandchild.

---

## Hardware layout

| MCU | Board | Carries |
|---|---|---|
| `mcu` | BTT Manta M8P | the printer itself — motion, bed, the machine's own config |
| `et0`–`et5` | BTT EBB36, one per toolhead | extruder, hotend, part fan, toolhead sensors, LEDs |
| `autoloader` | BTT MMB CAN V2.0, uuid `329ce333239a` | *(Autoloader project)* two steppers, servo, 6 encoders, 6 entry sensors |

Six toolheads on a StealthChanger — tool changes are a mechanical head swap
driven by `klipper-toolchanger`, selected with `T0`–`T5`.

**The `autoloader` board has no timing slack.** It bit-bangs software SPI for
two TMC5160s — hardware SPI fails on it — and polls twelve button pins every
2ms. It reports roughly **41× the per-task time of the main MCU**, and it has
shut down with `Timer too close` when the *host* stalled. Anything that blocks
the Klipper host long enough starves that board first. The known offender is
repeated `SAVE_VARIABLE`: each one rewrites the whole variables file
synchronously, and twelve in a row took the machine down three times.

That matters to any project on this machine, not just the Autoloader: **if you
add synchronous file I/O to a hot path, this is the board that dies.**

---

## Sharing the machine

Two projects on one printer is a coordination hazard with four specific edges.

**1. Restarting Klipper interrupts whatever else is running.** Check before you
restart:

```
curl -s "http://192.168.1.214:7125/printer/objects/query?idle_timeout&print_stats"
```

`idle_timeout.state == "Printing"` means gcode is executing — someone's
calibration, an unload, a real print. Restarting there aborts it mid-motion.

**2. Moonraker's Update Manager is configured per repo.** Each project gets its
own `[update_manager <name>]` block in `moonraker.conf` with its own
`primary_branch`. Read the block for *your* project — other blocks in that file
belong to other things and will say different branches. Getting this wrong
means deploying to a branch the printer does not follow, and the change simply
never arrives.

**3. `printer.cfg` and `klipper-toolchanger` are owned by the machine, not by
any project.** Do not edit them. Projects add an `[include]` and keep their own
config under their own directory.

**4. Symlinked vs copied.** Klipper extras and Moonraker components are usually
symlinked from the repo, so a `git reset` changes the running code the moment
the service restarts. Config files and KlipperScreen panels are **copied**, so
they silently keep running old code until whatever copies them is run. Know
which kind each of your files is; the failure mode of forgetting is a change
that appears deployed and is not.

---

## What lives where — Autoloader project *(project-specific)*

```
  repo ~/autoloader/  ──symlink──►  ~/klipper/klippy/extras/*.py   (6 extras)
                      ──symlink──►  ~/moonraker/.../sa_moonraker.py
                      ──copy─────►  ~/printer_data/config/autoloader/*.cfg
                      ──copy─────►  ~/KlipperScreen/panels/sa_*.py
                      ──generate─►  parameters.cfg, hardware.cfg, pin_aliases.cfg
                      ──build────►  ~/mainsail/plugins/autoloader-panel-plugin.js
```

Branches: `main` is what end users install, `dev` carries confirmed fixes, and
**this printer follows `printer-dev`**. `./post_update.sh` is the canonical
"sync everything not symlinked" step.

Three cfgs are **generated** from `installer/templates/` when an answer file
exists, so editing the repo copy alone does nothing — `post_update` regenerates
it and the change vanishes.

Calibration values live in `~/printer_data/config/autoloader/variables.cfg`,
which is **not in the repo and exists nowhere else**. Hours of measurement.
Do not delete that directory.

---

## Before trusting anything above

```
curl -s "http://192.168.1.214:7125/printer/info"
ssh pi@192.168.1.214 'ls ~/printer_data/config/'
ssh pi@192.168.1.214 'grep -n "^\[update_manager" ~/printer_data/config/moonraker.conf'
```

Three commands, and they replace every inventory claim in this file with what
is actually there.
