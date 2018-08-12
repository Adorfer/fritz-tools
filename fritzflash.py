#! /usr/bin/env python3
import argparse
import ipaddress
import os
import socket
import time
from ftplib import FTP

AUTODISCOVER_TIMEOUT = 1
AUTODISCOVER_MAX_RETRY = 10
FTP_TIMEOUT = 2
FTP_MAX_RETRY = 10


class FritzFTP(FTP):
    class ConnectionTimeout(Exception):
        pass

    def __init__(self, ip, username='adam2', password='adam2', timeout=1, max_retry=0, retry_cb=None):
        i = 1
        while i <= max_retry:
            try:
                retry_cb(i, max_retry)
                super().__init__(ip, user=username, passwd=password, timeout=timeout)
                break
            except socket.timeout:
                i += 1
            except OSError as e:
                time.sleep(1)
                i += 1
        if i > max_retry:
            raise FritzFTP.ConnectionTimeout()
        self.set_pasv(True)

    def getenv(self):
        env = [b'']
        fritzenv = {}

        def storeenv(x):
            env[0] += x

        self.voidcmd('MEDIA SDRAM')
        try:
            self.retrbinary('RETR env', storeenv)
        except socket.timeout:
            pass

        for line in env[0].decode('ascii').splitlines():
            l = line.split()
            fritzenv[l[0]] = l[1]

        return fritzenv

    def set_flash_timeout(self):
        self.sock.settimeout(60 * 5)

    def upload_image(self, image):
        self.set_flash_timeout()
        self.voidcmd('MEDIA FLSH')
        self.storbinary('STOR mtd1', image)

    def reboot(self):
        self.voidcmd('REBOOT')
        self.close()


def connection_refused_message():
    print("\nIt seems you have a booted-up AVM device running in your Network.\n"
          "This might be because you missed the 10 second window after powering on your AVM device.\n"
          "In this case: Powercycle your device and retry.\n"
          "If this problem persits, check if you might have connections to another AVM Device, e.g. via WiFi/WLAN.\n\n")


def start_message():
    print(
        "This program will help you installing Gluon, a widely used Firmware for Freifunk networks, onto your AVM device.\n"
        "You can always find the most current version of this script at https://www.github.com/freifunk-darmstadt/fritz-tools\n\n"
        "It is strongly recommended to only connect your computer to the Device you want to flash.\n"
        "Disable all other connections (Ethernet, WiFi/WLAN)!\n")


def network_message(ip_address):
    print(
        "Before we start, make sure you have assigned your PC a static IP Address in the Subnet of the Device you want to flash.")
    print("The following example would be a completely fine option:\n")
    print("IP-Address: %s" % str(ipaddress.ip_address(ip_address) + 1))
    print("Subnet: 255.255.255.0")
    print("Gateway: Leave blank")
    print("DNS Servers: Leave blank\n")
    print("Press enter when you have adjusted or verified your settings.")


def power_off_message():
    print("Disconnect power from the device and press enter.")


def power_on_message():
    print("Now connect the power-supply back and press enter.")


def connect_message():
    print("We will now connect to your devices bootloader.")


def flash_message():
    print("\nYour Gluon image will now be written to your AVM device.\n"
          "This process can take a lot of time.\n\n"
          "First, the Device will erase it's current Operating System.\n"
          "Afterwards the Device will write the Gluon image to it's memory.\n"
          "The red Info LED will illuminate in this step. Don't worry, this is expected behavior.\n\n"
          "We will tell you when your device has finished installing Gluon.")


def finish_message():
    print("\n== Congratulations! ==\n\n"
          "Your Device is now running Gluon.\n"
          "It will restart and in 2-5 minutes you will be able to visit it's config-mode.\n"
          "You can reach config-mode by typing in http://192.168.1.1/ in your preferred Webbrowser.")


def retry_status(current_try, max_try):
    print("-->Try %d of %d" % (current_try, max_try))


def autodiscover_avm_ip():
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sender.settimeout(1)

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.settimeout(AUTODISCOVER_TIMEOUT)
    receiver.bind(('0.0.0.0', 5035))

    i = 1
    while i <= AUTODISCOVER_MAX_RETRY:
        try:
            print("Try %d" % i)
            receiver.sendto(b'aa', ("192.168.178.1", 5035))  # Dirty hack to add conntrack entry
            sender.sendto(bytearray.fromhex("0000120101000000c0a8b20100000000"), ('255.255.255.255', 5035))
            while 1:
                data, addr = receiver.recvfrom(64)
                if addr[0] == '192.168.178.1':
                    print("FritzBox found at %s" % addr[0])
                    return addr[0]
        except socket.timeout:
            i += 1
        except OSError:
            i += 1
            time.sleep(1)

    return None


def determine_image_name(env_string):
    models = {
        "219": "avm-fritz-box-4020-sysupgrade.bin",
        "227": "avm-fritz-box-4040-bootloader.bin"
    }
    for model in models.keys():
        if model == env_string:
            return models[model]
    return None


def autoload_image(ip):
    print("-> Starting automatic image-selection!")
    print("--> Establishing connection to device!")

    try:
        ftp = FritzFTP(ip, timeout=FTP_TIMEOUT, max_retry=FTP_MAX_RETRY, retry_cb=retry_status)
    except FritzFTP.ConnectionTimeout:
        print("-> Max retrys exceeded! Check connection and try again.")
        exit(1)
    except ConnectionRefusedError:
        connection_refused_message()
        exit(1)

    env = ftp.getenv()
    ftp.close()

    if 'HWRevision' not in env:
        print("-> Automatic image-selection unsuccessful!")
        print("--> No model saved on device!")
        exit(1)

    model = determine_image_name(env["HWRevision"])

    if model is None:
        print("-> Automatic image-selection unsuccessful!")
        print("--> Unknown Model %s!" % env["HWRevision"])
        exit(1)

    dir_content = os.listdir(os.getcwd())
    files = []
    for file in dir_content:
        cwd = os.getcwd()
        file = os.path.join(cwd, file)
        if not os.path.isfile(file):
            continue
        if model in file:
            files.append(file)

    if len(files) > 1:
        print("-> Automatic image-selection unsuccessful!")
        print("--> Multiple potential image files found!")
        for file in files:
            print("----> %s" % file)
        exit(1)

    if len(files) is 0:
        print("-> Automatic image-selection unsuccessful!")
        print("--> No potential image file found!")
        exit(1)

    print("-> Automatic image-selection successful!")
    print("--> Will flash %s" % files[0])

    return open(files[0], 'rb')


def perform_flash(ip, file):
    print("-> Establishing connection to device!")

    try:
        ftp = FritzFTP(ip, timeout=FTP_TIMEOUT, max_retry=FTP_MAX_RETRY, retry_cb=retry_status)
    except FritzFTP.ConnectionTimeout:
        print("-> Max retrys exceeded! Check connection and try again.")
        exit(1)
    except ConnectionRefusedError:
        connection_refused_message()
        exit(1)

    print("-> Flash image")
    flash_message()
    ftp.upload_image(file)
    print("-> Image write successful")
    print("-> Performing reboot")
    ftp.reboot()
    finish_message()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Flash Gluon image to AVM Devices using EVA.')
    parser.add_argument('--ip', type=str, help='IP Address of device. Autodiscovery if not specified.')
    parser.add_argument('--image', type=str, help='Image file to transfer.')
    args = parser.parse_args()

    imagefile = None

    if args.ip:
        try:
            socket.inet_aton(args.ip)
        except socket.error:
            print("%s is not a valid IPv4 address!" % args.ip_address)
            exit(1)

    if args.image:
        try:
            imagefile = open(args.image, 'rb')
        except FileNotFoundError:
            print("Image file \"%s\" does not exist!" % os.path.abspath(args.image_path))
            exit(1)

    start_message()
    network_message("192.168.178.1")
    input()
    power_off_message()
    input()
    power_on_message()
    input()

    ip = args.ip
    if ip is None:
        print("-> Trying to autodiscover!")
        ip = autodiscover_avm_ip()

        if ip is None:
            print("-> Autodiscovery failed!")
            exit(1)

        print("-> Autodiscovery succesful!")
        print("-> Device is at %s." % ip)

    if args.image is None:
        # Try to automatically locate an image to use
        imagefile = autoload_image(ip)

    perform_flash(ip, imagefile)
