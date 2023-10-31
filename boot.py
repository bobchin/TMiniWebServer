import network

import sys
import time

args = ['IP', 'SUB', 'GW', 'DNS']
try:
    with open('laninfo.txt', 'rt') as f:
        args = list(map(lambda s: s.rstrip(), f.readlines()))
        del args[4:]
except:
    print("Failed LAN Configuration.")
    sys.exit(1)

nic = network.WIZNET5K()
nic.active(True)
nic.ifconfig(tuple(args[0:4])) # 固定IP
# nic.ifconfig()           # DHCP

while not nic.isconnected():
    time.sleep(1)

print('Connected!')
print('####################\nIP: %s\nSUBNET: %s\nGW: %s\nDNS: %s\n####################\n' % nic.ifconfig())
