#!/usr/bin/python

import socket
import sys
import json
import ConfigParser
from VMC import VMC

# Load Configuration
config = ConfigParser.RawConfigParser()
config.read('/etc/VMC/VMC.ini')

try:
    server_ip = config.get('client', 'server').strip('"')
    server_port = int(config.get('server', 'port').strip('"'))
except (ConfigParser.NoOptionError, ConfigParser.NoSectionError, ValueError) as e:
    print "Content-Type: text/plain\n\n"
    print "Error reading configuration: {}".format(str(e))
    sys.exit(1)

# Create a TCP/IP socket and connect to the server
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)  # never let this CGI (and its Apache worker) hang forever
    sock.connect((server_ip, server_port))

    # Fetch VMC data
    rcvd = VMC()
    try:
        rcvd.getfanstatus(sock)
        rcvd.getusage(sock)
        rcvd.getalltemp(sock)
        rcvd.getfanconfig(sock)
        rcvd.getdevinfo(sock)
        rcvd.getinputs(sock)
        rcvd.getbypass(sock)
        rcvd.getvalve(sock)
    except Exception as e:
        print "Content-Type: text/plain\n\n"
        print "Error retrieving data from VMC: {}".format(str(e))
        sock.close()
        sys.exit(1)

    # Print JSON response
    print "Content-Type: application/json\n\n"
    print json.dumps(rcvd.objet, sort_keys=True, indent=4)

    sys.stdout.flush()
    sock.close()

except socket.error as e:
    print "Content-Type: text/plain\n\n"
    print "Error connecting to server: {}".format(str(e))
    sys.exit(1)
