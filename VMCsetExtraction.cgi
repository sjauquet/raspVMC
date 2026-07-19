#!/usr/bin/python

import socket
import sys
import string
import json
import os
import ConfigParser
from VMC import VMC
import cgi, cgitb

print "Status: 200 OK"
print "Content-Type: application/json"
print ""

# RAM-backed state file (tmpfs): remembers the supply (admission) percentages
# that were active before "on" was requested, so "off" can restore them without
# writing anything to the SD card.
# Lives under /run/vmc/ (not /run/ directly) because /run itself is root:root 755 -
# server.py (running as root via inittab) creates /run/vmc/ world-writable at startup
# so this CGI (running as www-data under Apache) can write into it.
STATE_FILE = '/run/vmc/extraction_state.json'

form = cgi.FieldStorage()
state = form.getvalue('state')  # 'on' or 'off'

if state not in ('on', 'off'):
    print json.dumps({'error': 'parameter "state" must be "on" or "off"'})
    sys.exit(0)

config = ConfigParser.RawConfigParser()
config.read('/etc/VMC/VMC.ini')

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(5)  # never let this CGI (and its Apache worker) hang forever

try:
    server_address = (string.replace(config.get('client', 'server'), '"', ''), int(string.replace(config.get('server', 'port'), '"', '')))
    sock.connect(server_address)

    rcvd = VMC()

    if state == 'on':
        if not os.path.exists(STATE_FILE):
            rcvd.getfanconfig(sock)
            saved = rcvd.fansettings['admission']
            with open(STATE_FILE, 'w') as f:
                json.dump(saved, f)
        rcvd.setextraction(sock, 0)
        result = {'extraction_only': True}
    else:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                saved = json.load(f)
            fs = rcvd.getfanconfig(sock).fansettings['extraction']
            rcvd.setfanlevels(sock, fs['absent'], fs['vitesse1'], fs['vitesse2'],
                               saved['absent'], saved['vitesse1'], saved['vitesse2'],
                               fs['vitesse3'], saved['vitesse3'])
            os.remove(STATE_FILE)
            result = {'extraction_only': False, 'restored': saved}
        else:
            rcvd.getfanconfig(sock)
            result = {'extraction_only': False, 'restored': None, 'note': 'no saved state, nothing to restore'}

    result['ventilateurs'] = rcvd.objet['config']['ventilateurs']
    print json.dumps(result, sort_keys=True, indent=4)
    sys.stdout.flush()
    sock.close()

except Exception as e:
    # catch-all: without this, any error past this point (e.g. a permission
    # error writing STATE_FILE) would crash silently after the "200 OK" header
    # was already sent, and the client would just see an empty body.
    print json.dumps({'error': '{}: {}'.format(type(e).__name__, str(e))})
    sys.exit(1)
