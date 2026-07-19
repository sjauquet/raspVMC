#!/usr/bin/python

# Safety net for VMCsetExtraction.cgi: if extraction-only mode was left "on" for
# too long (Home Assistant crashed, network down, automation never fired the
# state=off call, ...), force the normal ventilation levels back regardless.
#
# Meant to run from cron, independently of Home Assistant/Apache, so the house
# keeps getting fresh air even if the rest of the home automation stack is dead.
# Suggested crontab (every 15 min):
#   */15 * * * * /usr/bin/python /home/pi/VMCextractionWatchdog.py

import socket
import string
import json
import os
import time
import syslog
import ConfigParser
from VMC import VMC

STATE_FILE = '/run/vmc/extraction_state.json'
DEFAULT_MAX_HOURS = 8

if not os.path.exists(STATE_FILE):
    exit(0)  # not in extraction-only mode, nothing to do

config = ConfigParser.RawConfigParser()
config.read('/etc/VMC/VMC.ini')

try:
    max_hours = float(config.get('VMC', 'extraction_max_hours'))
except Exception:
    max_hours = DEFAULT_MAX_HOURS

age = time.time() - os.path.getmtime(STATE_FILE)
if age < max_hours * 3600:
    exit(0)  # still within the allowed window

try:
    with open(STATE_FILE) as f:
        saved = json.load(f)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    server_address = (string.replace(config.get('client', 'server'), '"', ''), int(string.replace(config.get('server', 'port'), '"', '')))
    sock.connect(server_address)

    rcvd = VMC()
    fs = rcvd.getfanconfig(sock).fansettings['extraction']
    rcvd.setfanlevels(sock, fs['absent'], fs['vitesse1'], fs['vitesse2'],
                       saved['absent'], saved['vitesse1'], saved['vitesse2'],
                       fs['vitesse3'], saved['vitesse3'])
    sock.close()

    os.remove(STATE_FILE)
    syslog.syslog('VMC extraction watchdog: forced restore after {}s without state=off'.format(int(age)))
except Exception as e:
    syslog.syslog('VMC extraction watchdog: restore attempt failed: {}'.format(str(e)))
