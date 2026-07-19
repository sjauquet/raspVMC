#!/bin/bash
# Run this on the Pi after transferring files via WinSCP/SFTP - GUI clients often
# reset the executable bit on overwrite, which makes Apache/init fail to run the
# script (500 error / silent respawn failure) without any obvious error message.

sudo chmod 755 /home/pi/server.py
sudo chmod 755 /home/pi/VMCextractionWatchdog.py
sudo chmod 755 /usr/lib/cgi-bin/VMCbinjson.enhanced.cgi
sudo chmod 755 /usr/lib/cgi-bin/VMCbinjson.cgi
sudo chmod 755 /usr/lib/cgi-bin/VMCsetTConf.cgi
sudo chmod 755 /usr/lib/cgi-bin/VMCresetfilter.cgi
sudo chmod 755 /usr/lib/cgi-bin/VMCsetExtraction.cgi
sudo chmod 644 /usr/lib/pymodules/python2.7/VMC.py
sudo chmod 644 /etc/VMC/VMC.ini

echo "Permissions VMC réappliquées."
