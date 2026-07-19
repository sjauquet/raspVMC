# Extraction-only ("night cooling") mode - read this before using

Some ComfoAir-family units have two touch buttons + LEDs on the front panel to
force exhaust-only operation (handy for night cooling: run the extract fan
only, so a slight negative pressure pulls cool night air in through window
trickle vents, without the balanced supply fan pre-warming it through the
heat exchanger).

`VMCsetExtraction.cgi` / `VMC.py`'s `setfanlevels()` and `setextraction()`
reproduce the **physical effect** of that mode from software - but not
through the same mechanism, and that difference matters.

## What we found

- The front-panel button does **not** touch the persisted per-level fan
  table (`vitesse1/vitesse2/vitesse3` as read by `getfanconfig()`). It looks
  like a live/transient override: only the *currently active* value
  (`admission.actuel`) drops to 0, the stored table is untouched.
- `VMCsetExtraction.cgi` (via command `0xCF`, "Ventilationsstufe setzen")
  instead **rewrites the persisted table itself**, setting the supply
  percentage to 0 at every level, then restores the original values on
  `state=off`.
- Both approaches produce the same measurable result (supply fan ~0%,
  extract fan unaffected, bypass valve opens to 100% automatically) - so for
  monitoring/telemetry purposes they're equivalent.
- **They are not equivalent for recovery.** If the persisted table is
  currently zeroed by software and someone presses the physical OFF button
  (reasonably expecting it to fix things), it most likely just clears the
  button's own internal live override - which was never engaged, since
  software took the other path - and the unit falls back to reading the
  persisted table, which is still zeroed. The LED goes off, but the house
  keeps getting no fresh air. This was never confirmed with an oscilloscope
  or protocol sniff, only deduced from JSON diffs before/after each trigger
  method - treat it as a strong warning, not a certainty, and verify on your
  own unit before relying on it.

## `extractionetat` has counter-intuitive polarity

`config.ventilateurs.extractionetat` (from `VMC.py`'s `Rfansettings()`, byte
labeled "Abluft Ventilator aktiv" / "exhaust fan active" in the protocol
reference) reads **1 in normal balanced mode and 0 when extraction-only mode
is active** - the opposite of what the name suggests. Taken literally,
"exhaust fan active" should stay 1 in both cases: the extract fan keeps
running in extraction-only mode too, it's the *supply* fan that stops.

What's actually observed: this bit tracks whether **both fans are running in
balanced operation** (1) versus **asymmetric operation** (0) - regardless of
which fan is the odd one out, and regardless of whether extraction-only mode
was triggered via the button or via software. The 2011 reverse-engineered
protocol doc's byte label is best treated as an approximate guess, not a
guarantee - trust what you measure over what the label says. The Home
Assistant example in `home-assistant/configuration.yaml.example` inverts this
in the template itself (`extractionetat == 0`) so the resulting sensor
("Extraction Active") reads `true` exactly when extraction-only mode is
actually active, matching its name.

We could not find a documented RS232 command matching the button's actual
behavior (see `docs/PROTOCOL.md`'s source PDF) - it may be a firmware-local
feature that never goes out over RS232 at all. If you find it (e.g. by
enabling `[debug] level=8` in `VMC.ini` and sniffing the bus while pressing
the button on ON and OFF), please open an issue/PR - it would let
`VMCsetExtraction.cgi` reuse the exact same mechanism, making the physical
button a real universal fail-safe again.

## Consequences for automation

If you plan to drive this from Home Assistant (or anything else) rather than
just monitor it:

- **The physical button is not a reliable "undo" for the software-triggered
  state.** Don't assume a human can just walk up and press a button to
  recover.
- **A Raspberry Pi (or whatever runs `server.py`) can die** (SD card
  corruption, power loss, ...) while extraction mode is active in software,
  with no way for anything running *on that same device* to ever restore
  normal ventilation again.
- `VMCextractionWatchdog.py` covers the "automation/HA is down but the Pi is
  still alive" case: run it from `cron` (independent scheduler, doesn't
  depend on HA) and it force-restores the saved fan table after
  `extraction_max_hours` (see `VMC.ini`) if nobody called `state=off`.
- It does **not** cover "the Pi itself is dead" - nothing running on a dead
  device can fix anything. Consider a Home Assistant automation that alerts
  you if the VMC sensor data goes stale for more than ~15 minutes
  (independent of the Pi, since it runs on the HA host), so a human finds
  out quickly rather than days later.
- If you want a fail-safe that survives the Pi itself dying, look at
  physically automating the front-panel button (e.g. a relay wired to its
  contacts, driven by a *different* piece of hardware) rather than the
  software table rewrite - assuming you can confirm the button's own
  override doesn't persist across a power cycle of the VMC unit itself,
  which would make it self-healing independent of any computer.

Given all this, the safest default is what this fork's author actually
ships: use `Extraction Active` (`config.ventilateurs.extractionetat`,
inverted - see above) purely as a **read-only monitoring sensor** in Home
Assistant, and leave `VMCsetExtraction.cgi`/`VMCextractionWatchdog.py`
undeployed unless you've worked through the risk above for your own setup.
