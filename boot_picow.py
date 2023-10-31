import sys
import network
from time import sleep

args = ['IP', 'SUB', 'GW', 'DNS', 'SSID', 'PASS']
try:
    with open('laninfo.txt', 'rt') as f:
        args = list(map(lambda s: s.rstrip(), f.readlines()))
        del args[6:]
except:
    print("Failed LAN Configuration.")
    sys.exit(1)

print("Connecting to network...")
wlan = network.WLAN(network.STA_IF)
if not wlan.isconnected():
    wlan.active(True)
    wlan.connect(args[4], args[5])
    wlan.ifconfig(tuple(args[0:4]))

    while not wlan.isconnected():
        print("waiting for connection...")
        sleep(1)

print('Connected!')
print('####################\nIP: %s\nSUBNET: %s\nGW: %s\nDNS: %s\n####################\n' % wlan.ifconfig())
