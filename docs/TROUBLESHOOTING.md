# Troubleshooting

## "It just stops responding sometimes, then comes back on its own"

This was the original motivation for this fork. If you deployed this from a
much older copy of `server.py` (before this fork's rewrite of the main
loop), the likely cause was a blocking `Queue.get()` call in the serial-read
path: if a frame arrived from the VMC while no client was actually waiting
for one, the whole single-threaded event loop froze solid - forever, no
crash, no log, the TCP port stayed open (so new connections still
*connected*, they just never got a response). SysV `respawn` in `/etc/inittab`
(or the systemd unit, `Restart=always`) only helps if the process actually
*exits* - a frozen-but-alive process never does, so nothing recovered it
automatically. This fork's `server.py` uses a different design (a `(client,
frame)` pair carried through one queue, borrowed from a later point in
upstream's history) that doesn't have this failure mode at all - there is no
separate "who's waiting" queue to desync from what's actually pending.

## Check whether the server is actually alive and unstuck

`server.py` writes a one-line heartbeat every 5 seconds to
`[debug] heartbeat` in `VMC.ini` (default `/run/vmc/heartbeat.log`, tmpfs -
zero SD wear):

```
cat /run/vmc/heartbeat.log
```

If the timestamp is recent and `messages_q` isn't growing across repeated
checks, the server is fine. If the file doesn't exist at all, either the
config points somewhere else (`grep heartbeat /etc/VMC/VMC.ini`) or you're
running an older `server.py` that predates this feature - redeploy it.

## CGI returns a blank page / empty body after a "200 OK"

If a CGI script prints its HTTP headers (`Status: 200 OK`) before doing any
real work, and then hits an *uncaught* exception, the client sees a
"successful" response with an empty body instead of a useful error - the
traceback only goes to Apache's error log (stderr), not to the response.
`VMCsetExtraction.cgi` in this fork wraps everything after the headers in a
catch-all `except Exception` for exactly this reason. If you add your own
CGI script, do the same, or move the header printing to *after* you know the
request succeeded (see `VMCbinjson.cgi` for that pattern).

## CGI or `server.py` gives a permission error / 500 after copying files

If you deploy files with an SFTP/SCP GUI client (WinSCP and friends often
reset the executable bit on overwrite), Apache/`init` will fail to execute
the script - usually a plain "500 Internal Server Error" from Apache itself
(not from the CGI's own error handling, since the process never started).
Because these files typically end up owned by `root:root` (if you `sudo cp`
them) while Apache's CGI worker runs as `www-data`, the relevant bit isn't
the owner's `x`, it's *others*': `chmod 755` covers all three classes and is
enough. Run `./fix_permissions.sh` after every file transfer, or configure
your SFTP client to preserve/set permissions on upload.

## A `.cgi`/`.py` script "can't find the interpreter" on Linux

Check for a `\r` right after the shebang line:

```
head -c 20 yourscript.cgi | xxd
```

If you see `0d 0a` right after `python`, the file has Windows (CRLF) line
endings - the kernel reads `#!/usr/bin/python\r` as the interpreter path,
which doesn't exist. `dos2unix yourscript.cgi` fixes an individual file; this
repo ships a `.gitattributes` that normalizes new commits to LF for
`.py`/`.cgi`/`.sh`/`.ini` files, but files already committed with CRLF before
that (some of the untouched legacy files in this repo) aren't retroactively
fixed by it.

## No response at all, but the TCP connection succeeds instantly

That specific combination (`connect()` returns immediately, then nothing
ever comes back) usually means the *listening* socket is fine (the OS
accepted the handshake into its backlog queue) but the process behind it
never got around to calling `accept()` - i.e. it's alive but stuck
somewhere else in its loop. See the heartbeat check above.
