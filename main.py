import _thread
import pycom
import socket
import time
import machine
import ubinascii
import gc
import ujson
import os
from utils import Utils as utils
from network import LoRa, WLAN
from machine import SD
from L76GNSS import L76GNSS
from pytrack import Pytrack

LORA_BAT_PSU = 0
LORA_BAT_CANNOT_MEASURE = 255

# Hardware setup
py = Pytrack()

# Software setup
gc.enable()
thread_list = {}
thread_list_mutex = _thread.allocate_lock()
conf = {}

def printt(*args, **kwargs):
    global thread_list
    try:
        print("[" + thread_list[_thread.get_ident()] + "] " + " ".join(map(str, args)), **kwargs)
    except KeyError:
        pass

def load_config(filename):
    global conf
    try:
        f = open(filename, 'r')
        conf = ujson.load(f)
        f.close()
    except OSError:
        print("Cannot load config (%s), please upload before proceeding!" % (filename))
        while (True):
            time.sleep(1)

def lora_set_battery():
    voltage = py.read_battery_voltage()
    lora_batery_state = LORA_BAT_CANNOT_MEASURE

    if voltage > 4.3:
        lora_batery_state = LORA_BAT_PSU
        printt("[PSU] Voltage %0.2f V" % (voltage))
    else:
        lora_batery_state = int(utils.map(voltage, 3.6, 4.3, 1, 254))
        printt("[BAT] Voltage %0.2f V mapped to %d" % (voltage, lora_batery_state))

def lora_task():
    with thread_list_mutex:
        thread_list[_thread.get_ident()] = 'LORA'

    # Initialise LoRa in LORAWAN mode.
    # Please pick the region that matches where you are using the device:
    # Asia = LoRa.AS923
    # Australia = LoRa.AU915
    # Europe = LoRa.EU868
    # United States = LoRa.US915
    lora = LoRa(mode=LoRa.LORAWAN, region=LoRa.EU868, tx_power=14)
    printt("DevEUI: %s" % (ubinascii.hexlify(lora.mac()).decode('ascii')))

    # create an OTAA authentication parameters
    app_eui = ubinascii.unhexlify(conf['lora']['app_eui'])
    app_key = ubinascii.unhexlify(conf['lora']['app_key'])

    printt("Joining LORAWAN with EUI: %s and KEY: %s" % (conf['lora']['app_eui'], conf['lora']['app_key']))

    # join a network using OTAA (Over the Air Activation)
    lora.join(activation=LoRa.OTAA, auth=(app_eui, app_key), timeout=0)

    lora_setup_done = False
    while (True):
        # Set LORA battery state
        lora_set_battery()

        # wait until the module has joined the network
        if (not lora.has_joined()):
            pycom.rgbled(0x100000)
            printt('Joining network...')
            time.sleep(2.5)
        else:
            if (not lora_setup_done):
                # Succesfully joined
                pycom.rgbled(0x001000)

                # create a LoRa socket
                s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)

                # set the LoRaWAN data rate
                s.setsockopt(socket.SOL_LORA, socket.SO_DR, 5)

                lora_setup_done = True
            
            # make the socket blocking
            # (waits for the data to be sent and for the 2 receive windows to expire)
            s.setblocking(True)

            # send some data
            s.send(bytes([0x01, 0x02, 0x03]))

            # make the socket non-blocking
            # (because if there's no data received it will block forever...)
            s.setblocking(False)

            # get any data received (if any...)
            data = s.recv(64)
            print(data)

        time.sleep(0.1)

def gnss_task():
    sd_mounted = False

    with thread_list_mutex:
        thread_list[_thread.get_ident()] = 'GNSS'

    # Mount SD if possible
    sd = SD()
    try:
        os.mount(sd, '/sd')
        os.listdir('/sd')
        sd_mounted = True
    except OSError:
        pass
    
    gnss = L76GNSS(py, timeout=5)

    while True:
        coord = gnss.rmc()
        printt(coord)

        # if sd_mounted:
        #     logfile = open('/sd/gnss.txt', 'a')
        #     logfile.write(logstring)
        #     logfile.close()

        time.sleep(2)

def system_task():
    with thread_list_mutex:
        thread_list[_thread.get_ident()] = 'SYST'

    while True:
        gc.collect()
        time.sleep(2)

print('LORA GPS TRACKER APPLICATION')
time.sleep(2)

# Load configuration file from flas
load_config('config/app.json')

# Check if we need wifi
if conf['wifi']['enabled']:
    wlan = WLAN(mode=WLAN.STA)
    nets = wlan.scan()
    for net in nets:
        if (net.ssid == conf['wifi']['ssid']):
            print('Network found: %s' % (conf['wifi']['ssid']))
            wlan.connect(net.ssid, auth=(net.sec, conf['wifi']['key']), timeout=5000)
            while not wlan.isconnected():
                machine.idle() # save power while waiting
            print('WLAN connection succeeded!')
            break

# Start processing threads
_thread.stack_size(32768)
_thread.start_new_thread(lora_task, ())
_thread.start_new_thread(gnss_task, ())
_thread.start_new_thread(system_task, ())

gc.collect()

while (True):
    try:
        time.sleep(0.1)
    except KeyboardInterrupt:
        print("received keyboard interrupt")
    except:
        print("Got another interrupt")