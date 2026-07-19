# raspVMC (hardened, simplified fork)

This is a fork of [jcoenencom/raspVMC](https://github.com/jcoenencom/raspVMC) -
all credit for the original protocol implementation, server/CGI architecture
and web UI goes to that project. This fork exists because a long-running
deployment (Zehnder/StorkAir WHR960, Raspberry Pi, Home Assistant) kept
freezing for reasons that took a fair amount of debugging to actually pin
down, and because KNX/MySQL/ConfoSense support couldn't be tested by this
fork's maintainer and were dropped rather than carried along untested.

If you need KNX, MySQL, or a ConfoSense/CCEASE bridge, use the upstream
project instead - the wire protocol handling (`VMC.py`) is unchanged and
compatible either way, so patches tend to move between the two easily.

## What this fork is for

Bridging a Zehnder/StorkAir ComfoAir-family balanced ventilation unit
(WHR930, WHR960, CA350, ...) connected over RS232 to a Raspberry Pi, exposing
it as JSON over HTTP (CGI), for consumption by Home Assistant or anything
else that can poll a URL.

```
Home Assistant --(HTTP, polling)--> CGI scripts --(TCP)--> server.py --(RS232)--> VMC unit
```

Tested on Raspbian Wheezy (yes, that old) with Python 2.7, Apache 2.2 +
mod_cgi, and a WHR960. Should work unmodified on any Debian-family Pi image
old enough to still ship Python 2 by default.

## What changed vs. upstream, and why

- **`server.py` rewritten around upstream's later `(client, frame)` queue
  design** (not the older `sender`/`message_queues` FIFO pairing this fork's
  maintainer had been running for years) - see
  `docs/TROUBLESHOOTING.md` for the actual multi-day debugging story of why
  the old design would occasionally freeze the whole process solid until
  manually killed.
- **ConfoSense/CCEASE bridge, telnet-style control port, KNX and MySQL
  support removed.** None of it could be tested against this fork's changes.
  `VMCknx.py`, `knx.ini`, `config.py` were removed; `install.bash` no longer
  calls the interactive config wizard and ships a ready-to-edit `VMC.ini`
  instead.
- **A heartbeat file** (`[debug] heartbeat` in `VMC.ini`, tmpfs by default -
  zero SD wear) written every 5 seconds, so a future freeze can actually be
  diagnosed instead of guessed at.
- **CGI scripts get a socket timeout** and a catch-all exception handler, so
  a server-side problem fails fast (~5s) with a readable JSON error instead
  of hanging the calling Apache worker for up to an hour.
- **A checksum-validation bug fixed** in `VMC.py`: `Checksum()` returned `-1`
  (which is truthy in Python) on a failed checksum, so corrupted frames were
  silently parsed as if valid.
- **`0xCF` ("set ventilation levels") exposed**, via `setfanlevels()` /
  `setextraction()` in `VMC.py` and `VMCsetExtraction.cgi` - lets you reduce
  supply air independently of exhaust (useful for night cooling). **Read
  `docs/EXTRACTION_MODE.md` before wiring this into any automation** - it
  documents a real gap between this and the unit's own front-panel button
  that matters if you're relying on it as a safety fallback.
- `fix_permissions.sh` added: GUI SFTP clients (WinSCP and friends) commonly
  reset the executable bit on file overwrite, breaking Apache/`init` in a way
  that looks unrelated at first. Run it after every deploy, or configure your
  client to preserve permissions.
- `.gitattributes` added to normalize new commits to LF line endings for
  scripts - some files in this codebase's history had Windows (CRLF) line
  endings, which breaks the shebang line's interpreter lookup on Linux (see
  `docs/TROUBLESHOOTING.md`).

## Installation

1. `git clone` this repo onto the Pi (or download+unzip).
2. `./install.bash` - installs apache2/socat/python-serial, optionally FHEM,
   copies `VMC.ini` to `/etc/VMC/VMC.ini` and opens it for editing (set
   `[VMC] device=` to your serial port), deploys the CGI scripts and
   `server.py`, and adds the `inittab` respawn entry.
3. On Jessie or later, use `VMCserver.service` (systemd) instead of the
   `inittab` line - see the comments in `install.bash`/`VMCserver.service`.
4. `sudo cp fix_permissions.sh /home/pi/` and run it once, then again after
   any future file transfer.
5. Test: `curl http://localhost/cgi-bin/VMCbinjson.cgi` should return a JSON
   blob with `config`/`data`/`device` keys.

## Home Assistant

See `home-assistant/configuration.yaml.example` for a REST sensor + a full
set of template sensors (temperatures, fan speeds/RPM/%, usage counters,
bypass status, extraction-mode monitoring).

## Extraction-only / night cooling mode

`VMCsetExtraction.cgi?state=on|off` and `VMCextractionWatchdog.py` implement
this, but **read `docs/EXTRACTION_MODE.md` first** - there's a real
difference between how this and the physical front-panel button achieve the
same airflow effect, with consequences for what actually happens if your
automation stack goes down while it's active.

## Other docs

- `docs/PROTOCOL.md` - RS232 protocol quick reference and source.
- `docs/TROUBLESHOOTING.md` - the freeze/permissions/CRLF stories in detail.
- `docs/EXTRACTION_MODE.md` - the extraction-mode software-vs-button gap.

## License

GPL-2.0, same as upstream (see `LICENSE`).
