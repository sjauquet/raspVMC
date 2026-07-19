# ComfoAir / Zehnder / StorkAir RS232 protocol - quick reference

This project talks to the ventilation unit over a proprietary RS232 protocol used
across the Zehnder ComfoAir / StorkAir WHR9xx / CA350 family. The authoritative,
reverse-engineered description of this protocol is:

**"Protokollbeschreibung Zehnder ComfoAir"** by see-solutions.de (21.08.2011)
<http://www.see-solutions.de/sonstiges/Protokollbeschreibung_ComfoAir.pdf>

`VMC.py` in this repo is an implementation of that protocol (frame building,
checksum, command dispatch). This page summarizes the parts most relevant to
using/extending it - see the PDF above for the complete command list.

## Frame format

```
Start      Command    Length    Data       Checksum   End
2 bytes    2 bytes    1 byte    0-n bytes  1 byte     2 bytes
0x07 0xF0  0x00 <cmd>           payload               0x07 0x0F
```

- A `0x07` byte appearing inside the data is escaped as `0x07 0x07` (not counted
  towards length/checksum).
- Every frame received must be acknowledged with `0x07 0xF3` (2 bytes).
- The command byte in a *response* is always the *request*'s command byte + 1.
- Checksum = (sum of command + length + data bytes) + 173, low byte only.

## Read vs. write commands

Read ("Lesekommandos") commands send no data and get a data frame back at
`cmd+1`. Write ("Schreibkommandos") commands carry data and, with one
exception (`0x9B` RS232 mode), only get a bare ACK back - no data frame. This
matters for anyone extending `server.py`'s `reply()` function: getting this
wrong for a given command either makes the server wait forever for a data
frame that will never come, or discards a data frame that was actually sent.
The `replied` blacklist in `reply()` already covers every currently
implemented write command (`0x99` set speed, `0x9F` set analog values, `0xCB`
set delays, `0xCF` set ventilation levels, `0xD3` set comfort temperature,
`0xD7` set status, `0xDB` reset/self-test, `0xED` set EWT/preheat) - add new
write commands to that list, not the other way round.

## Command highlights used by this fork

| Command | Name | Notes |
|---|---|---|
| `0x69` / `0x6A` | Get firmware version | `getdevinfo()` |
| `0x0B` / `0x0C` | Get fan status (RPM, %) | `getfanstatus()` |
| `0xDD` / `0xDE` | Get usage counters (hours) | `getusage()` |
| `0xD1` / `0xD2` | Get temperatures | `getalltemp()` |
| `0xCD` / `0xCE` | Get ventilation levels (per-level supply/exhaust %) | `getfanconfig()` |
| `0xCF` | **Set** ventilation levels | `setfanlevels()` - see `docs/EXTRACTION_MODE.md` |
| `0xDF` / `0xE0` | Get bypass status | `getbypass()` |
| `0x99` | Set fan speed (1=absent .. 4=high) | `setspeed()` |
| `0xD3` | Set comfort temperature | `setTconfort()` |
| `0xDB` | Reset / self-test | not exposed via CGI in this fork |

## Checksum gotcha

`VMC.py`'s `Checksum()` returns the computed checksum byte on success, or the
integer `-1` on mismatch. **`-1` is truthy in Python** - code that does
`if self.Checksum():` treats a *failed* checksum as success and parses the
payload anyway. Always check `if self.Checksum() != -1:` instead (fixed in
this fork's `VMC.py`, both call sites).
