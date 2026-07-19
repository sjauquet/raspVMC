#!/usr/bin/python
#
# raspVMC server - RS232/serial <-> TCP bridge for Zehnder/StorkAir ComfoAir-family
# ventilation units (WHR930, WHR960, CA350, ...).
#
# This is a simplified branch of jcoenencom/raspVMC (see README.md), focused on the
# single-VMC-over-RS232 use case: the ConfoSense/CCEASE bridge, the telnet-style
# control port and the KNX/MySQL integrations from upstream have been removed here
# because they were never tested against this fork's fixes. If you need any of
# those, use the upstream project instead - the wire protocol handling (VMC.py) is
# unchanged and compatible either way.

import select
import socket
import sys
import Queue
import ConfigParser
import serial
import string
import binascii
import re
import signal
import os
import time
import subprocess
import syslog
from stat import *

global server
global config
global debugL
global DBGCLIENT
global DBGCONFIG
global DBGFRAME
global DBGFile
global outputs
global inputs


def debug(level, *args):
    if level <= int(debugL):
        print time.strftime('%d/%m/%y %H:%M:%S', time.localtime()), ':',
        for arg in args:
            print arg,
        print
        sys.stdout.flush()


def signal_handler(signum, frame):
    syslog.syslog('Signal {} received, aborting server, clearing socket'.format(signum))
    while inputs:
        instance = inputs.pop()
        mode = os.fstat(instance.fileno()).st_mode
        if S_ISSOCK(mode) and instance != server:
            syslog.syslog('Closing IP socket on client {}'.format(str(instance.getpeername())))
        elif instance == server:
            syslog.syslog('Closing server socket')
            server.close()
        else:
            syslog.syslog('Closing device connection')
            instance.close()
    sys.exit(0)


def reply(tosend):
    # Commands that only get a bare ACK from the VMC (no data frame back) - the rest
    # of the standard protocol always replies with a data frame. List confirmed
    # against the "Schreibkommandos" (write commands) in the protocol reference,
    # see docs/PROTOCOL.md.
    replied = ['\x99', '\x9f', '\xcb', '\xcf', '\xd3', '\xd7', '\xdb', '\xed']
    temp = tosend[3] not in replied
    debug(DBGFRAME, 'Command code:', binascii.hexlify(tosend[3]), 'reply expected:', temp)
    return temp


RESPONSE_TIMEOUT = 2.0  # overall seconds to wait for a full response frame


def response(Sport):
    # Read the response frame from the VMC and ACK it. A single Sport.read(256)
    # (bounded by Sport's own per-read serial timeout) isn't enough: some commands
    # (temperatures, device info, bypass, valve status) take the VMC noticeably
    # longer to answer than others, and their reply can arrive as more than one
    # chunk - found by comparing which fields silently went missing from
    # VMCbinjson.cgi output during testing. Keep accumulating chunks and checking
    # for a complete frame until RESPONSE_TIMEOUT, instead of giving up after one
    # short read - still bounded, just patient enough for a slow reply.
    bread = b''
    deadline = time.time() + RESPONSE_TIMEOUT
    while time.time() < deadline:
        chunk = Sport.read(256)
        if chunk:
            bread += chunk
            debug(DBGFRAME, 'received from VMC', binascii.hexlify(bread))
            frame = re.search(b'(\x07\xf0.{3}(?:[^\x07]|(?:\x07\x07))*\x07\x0f)', bread, flags=re.S)
            if frame:
                debug(DBGFRAME, 'frame received from VMC', binascii.hexlify(frame.group(1)))
                Sport.write(binascii.a2b_hex('07f3'))  # ACK back to the VMC
                return frame.group(1)
    debug(DBGFRAME, 'no frame detected within', RESPONSE_TIMEOUT, 's, got', binascii.hexlify(bread))
    return None


# initialize globals
DBGCONFIG = 2
DBGCLIENT = 3
DBGFRAME = 8

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# read config file
config = ConfigParser.RawConfigParser()
config.read('/etc/VMC/VMC.ini')

# get debug level, default to 0 if not defined
try:
    debugL = config.get('debug', 'level')
except ConfigParser.NoSectionError, ConfigParser.NoOptionError:
    debugL = 0

try:
    DBGFile = config.get('debug', 'log')
    # "none" or empty disables file logging entirely (avoids SD card wear on a Pi)
    if DBGFile.lower() == 'none' or not DBGFile:
        sys.stdout = sys.__stdout__
    else:
        sys.stdout = open(DBGFile, 'a')
except Exception as e:
    DBGFile = "stdout"
    print("Problem with log: {}".format(e))
    sys.stdout = sys.__stdout__

# /run is root:root 755, so CGI scripts (running as www-data under Apache) cannot
# write there directly. This server runs as root (inittab/systemd), so it creates a
# world-writable tmpfs subdirectory here at startup for RAM-only shared state: the
# heartbeat file below, and the extraction-mode state file used by
# VMCsetExtraction.cgi if you use it. Nothing here touches the SD card.
try:
    if not os.path.isdir('/run/vmc'):
        os.makedirs('/run/vmc')
    os.chmod('/run/vmc', 0777)
except Exception as e:
    syslog.syslog('VMCserver could not prepare /run/vmc: {}'.format(str(e)))

# Heartbeat file, written every HEARTBEAT_INTERVAL seconds: if this server ever
# freezes again, the last timestamp + queue depths tell you what state it was in.
try:
    HeartbeatFile = config.get('debug', 'heartbeat')
    if HeartbeatFile.lower() == 'none' or not HeartbeatFile:
        HeartbeatFile = None
except Exception:
    HeartbeatFile = '/run/vmc/heartbeat.log'

HEARTBEAT_INTERVAL = 5  # seconds
lastHeartbeat = 0

# open the serial port attached to the VMC
serialport = string.replace(config.get('VMC', 'device'), '"', '')
Sport = serial.Serial(port=serialport, baudrate=9600, timeout=0.25)

# protocol frame regex: 0x07 0xF0 <cmd:2><len:1><data:0-n><ck:1> 0x07 0x0F
pdata = re.compile(b'(\x07\xf0.{3}(?:[^\x07]|(?:\x07\x07))*\x07\x0f)')

# Create the TCP/IP socket clients connect to
try:
    config.get('server', 'port')
    Port = int(string.replace(config.get('server', 'port'), '"', ''))
except:
    Port = 10000
try:
    config.get('server', 'bind')
    bind = string.replace(config.get('server', 'bind'), '"', '')
except:
    bind = ''

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setblocking(0)
server_address = (bind, Port)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(server_address)
server.listen(5)

syslog.syslog('Starting VMC server on device {}, Debug log: {}, running on IP address: {}'.format(serialport, DBGFile, str(server_address)))

# Optional virtual serial port (used by e.g. FHEM's comfoair driver) via socat
try:
    PTY = string.replace(config.get('socat', 'PTY'), '"', '')
    SOCAT_SERVER = string.replace(config.get('client', 'server'), '"', '')
    SOCAT_PORT = string.replace(config.get('server', 'port'), '"', '')
    SOCAT = ['socat', 'PTY,mode=666,link=' + PTY, 'TCP-CONNECT:' + SOCAT_SERVER + ':' + SOCAT_PORT]
    for arg in SOCAT:
        debug(DBGCONFIG, arg)
    PID = subprocess.Popen(SOCAT).pid
    syslog.syslog('socat started on {}, PID: {}'.format(str(PTY), str(PID)))
except:
    e = sys.exc_info()[0]
    print "error: %s" % e
    syslog.syslog('VMCserver cannot start socat (maybe not configured)')

# Sockets from which we expect to read
inputs = [server]

portno = socket.fromfd(Sport.fileno(), socket.AF_INET, socket.SOCK_STREAM)
inputs.append(portno)

# Sockets to which we expect to write
outputs = [portno]
clients = []

# Outgoing (client, frame) pairs waiting to be sent to the VMC. Carrying the client
# reference alongside its frame (rather than a separate FIFO of "who's waiting")
# means a reply can never get paired with the wrong client - see README.md history
# section for why that matters.
messages = Queue.Queue()

while inputs:
  try:
    # 5s timeout so the loop always cycles even during silence, keeping the
    # heartbeat file (and any pending cleanup) alive.
    readable, writable, exceptional = select.select(inputs, outputs, inputs, 5)

    for s in readable:
        if s is server:
            connection, client_address = s.accept()
            debug(DBGCLIENT, 'new client connection from', client_address)
            connection.setblocking(0)
            inputs.append(connection)
            clients.append(connection)
        elif s is portno:
            # Deliberately do nothing here. All VMC reads happen synchronously
            # inside response(Sport), called right after writing a command in the
            # writable-handling section below. Reading here too would race with
            # that: if portno shows up in both readable and writable in the same
            # select() cycle, an eager read here can steal the very bytes
            # response(Sport) is about to wait for, leaving it with nothing (or a
            # shifted fragment that fails checksum) - this was a real regression,
            # found by comparing field-by-field JSON output during testing. Any
            # bytes sitting in the OS serial buffer are perfectly safe to leave
            # for the next response(Sport) call.
            pass
        elif s in clients:
            try:
                data = s.recv(1024)
            except socket.error as e:
                # client reset the connection instead of closing it cleanly
                debug(DBGCLIENT, 'client connection reset:', str(e))
                data = None
            if data:
                # A single recv() can contain more than one complete request frame
                # (the VMC.py client sends its next command immediately once it has
                # read a response, and the OS is free to coalesce both writes into
                # one chunk here) - use findall(), not match(), or every frame past
                # the first in a batch is silently dropped. Found live: getalltemp/
                # getdevinfo/getbypass kept going missing from VMCbinjson.cgi output
                # with no error, traced via [debug] level=8 frame logging to exactly
                # this - two requests arriving concatenated, the second discarded.
                frames = pdata.findall(data)
                if frames:
                    debug(DBGFRAME, 'received', binascii.hexlify(data), 'from client', '({} frame(s))'.format(len(frames)))
                    for frame in frames:
                        messages.put((s, frame))  # store (client, frame) to send
                # Deliberately not acking here: VMC.py's GetResp() does a single
                # recv(64) expecting the real response frame directly, not a
                # separate intermediate ACK. Sending one anyway (as upstream does)
                # races with the real, slower response: the client's recv() can
                # return with just this ACK, decide (wrongly) that it has its
                # answer, and move on to the next command while the real response
                # is still in flight - the exact cause of the frame-coalescing
                # above. The 0x07 0xF3 ACK is a VMC<->server protocol detail; the
                # server<->client link here doesn't need one.
            else:
                # empty read = client closed the connection
                debug(DBGCLIENT, 'closing client connection after reading no data')
                if s in outputs:
                    outputs.remove(s)
                if s in clients:
                    clients.remove(s)
                inputs.remove(s)
                s.close()
                del s
        else:
            inputs.remove(s)

    for s in writable:
        if s is portno:
            if not messages.empty():
                (client, tosend) = messages.get()
                debug(DBGFRAME, 'sending frame', binascii.hexlify(tosend), 'to VMC')
                Sport.write(tosend)
                if reply(tosend):
                    next_msg = response(Sport)
                    if next_msg is not None:
                        debug(DBGFRAME, 'sending', binascii.hexlify(next_msg), 'to client')
                        try:
                            client.send(next_msg)
                        except socket.error as e:
                            # The client gave up and closed its socket (e.g. its own
                            # timeout elapsed) before the VMC's reply made it back -
                            # found live as an uncaught "Broken pipe" that crashed the
                            # whole server for every other client too. Losing this one
                            # reply is fine; the CGI script already got its own error.
                            debug(DBGCLIENT, 'client gone, could not deliver reply:', str(e))
                else:
                    debug(DBGFRAME, 'not expecting a reply')

    for s in exceptional:
        debug(DBGCLIENT, 'handling exceptional condition for a socket')
        inputs.remove(s)
        if s in outputs:
            outputs.remove(s)
        if s in clients:
            clients.remove(s)
        s.close()

    if HeartbeatFile:
        now = time.time()
        if (now - lastHeartbeat) >= HEARTBEAT_INTERVAL:
            try:
                with open(HeartbeatFile, 'w') as hb:
                    hb.write('{} inputs={} outputs={} clients={} messages_q={}\n'.format(
                        time.strftime('%Y-%m-%d %H:%M:%S'), len(inputs), len(outputs), len(clients), messages.qsize()))
            except Exception:
                pass
            lastHeartbeat = now

    time.sleep(0.008)
  except (KeyboardInterrupt, SystemExit):
    raise
  except Exception as e:
    # Last-resort safety net: nothing anticipated should reach here (the specific
    # failure points above are already handled), but this server controls house
    # ventilation - an unanticipated bug should log and keep running, not take the
    # whole bridge down for every client because of one bad exchange. Found the
    # need for this the hard way: an uncaught "Broken pipe" on client.send() used
    # to kill the entire process.
    syslog.syslog('VMCserver: unexpected error in main loop, continuing: {}'.format(str(e)))
    debug(DBGCLIENT, 'unexpected error in main loop:', str(e))
