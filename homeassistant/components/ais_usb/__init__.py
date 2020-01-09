"""
Support to monitoring usb events with inotify on AIS gate.

For more details about this component, please refer to the documentation at
https://www.ai-speaker.com
"""
import asyncio
import logging
import pyinotify
import re
import os
import subprocess
import homeassistant.components.ais_dom.ais_global as ais_global


DOMAIN = "ais_usb"
_LOGGER = logging.getLogger(__name__)
G_ZIGBEE_ID = "0451:16a8"
G_AIS_REMOTE_ID = "1d6b:0003"


def get_device_info(pathname):
    # get devices full info via pathname
    bus = pathname.split("/")[-2]
    device = pathname.split("/")[-1]
    # find the id of the connected device
    for d in ais_global.G_USB_DEVICES:
        if d["bus"] == bus and d["device"] == device:
            return d

    return None


def prepare_usb_device(hass, device_info):
    # start zigbee2mqtt service

    # add info in app
    if device_info["id"] == G_ZIGBEE_ID:
        # Register the built-in zigbee panel
        hass.components.frontend.async_register_built_in_panel(
            "lovelace/ais_zigbee", "Zigbee", "mdi:zigbee"
        )
        # check if zigbee already exists
        if not os.path.isdir("/data/data/pl.sviete.dom/files/home/zigbee2mqtt"):
            # download
            hass.async_add_job(
                hass.services.async_call(
                    "ais_ai_service",
                    "say_it",
                    {
                        "text": "Nie znaleziono pakietu Zigbee2Mqtt zainstaluj go przed pierwszym uruchomieniem usługi "
                        "Zigbee. Szczegóły w dokumentacji Asystenta domowego."
                    },
                )
            )
            return

        # start pm2 zigbee service
        os.system("pm2 stop zigbee")
        os.system("pm2 delete zigbee")
        os.system(
            "cd /data/data/pl.sviete.dom/files/home/zigbee2mqtt && pm2 start npm --name zigbee --output NULL "
            "--error NULL --restart-delay=30000 -- run start "
        )
        os.system("pm2 save")
        if ais_global.G_AIS_START_IS_DONE:
            hass.async_add_job(
                hass.services.async_call(
                    "ais_ai_service", "say_it", {"text": "Uruchomiono serwis zigbee"}
                )
            )


def remove_usb_device(hass, device_info):
    # stop service and remove device from dict
    ais_global.G_USB_DEVICES.remove(device_info)

    if device_info["id"] == G_ZIGBEE_ID:
        # Unregister the built-in zigbee panel
        hass.components.frontend.async_remove_panel("lovelace/ais_zigbee")
        # stop pm2 zigbee service
        os.system("pm2 stop zigbee")
        os.system("pm2 delete zigbee")
        os.system("pm2 save")
        hass.async_add_job(
            hass.services.async_call(
                "ais_ai_service", "say_it", {"text": "Zatrzymano serwis zigbee"}
            )
        )


@asyncio.coroutine
async def async_setup(hass, config):
    """Set up the usb events component."""
    #
    wm = pyinotify.WatchManager()  # Watch Manager
    mask = pyinotify.IN_DELETE | pyinotify.IN_CREATE  # watched events

    class EventHandler(pyinotify.ProcessEvent):
        def process_IN_CREATE(self, event):
            ais_global.G_USB_DEVICES = _lsusb()
            device_info = get_device_info(event.pathname)
            if device_info is not None:
                hass.async_add_job(
                    hass.services.async_call(
                        "ais_ai_service",
                        "say_it",
                        {"text": "Dodano: " + device_info["info"]},
                    )
                )
                # prepare device
                prepare_usb_device(hass, device_info)

        def process_IN_DELETE(self, event):
            device_info = get_device_info(event.pathname)
            if device_info is not None:
                hass.async_add_job(
                    hass.services.async_call(
                        "ais_ai_service",
                        "say_it",
                        {"text": "Usunięto: " + device_info["info"]},
                    )
                )
                # remove device
                remove_usb_device(hass, device_info)

    notifier = pyinotify.ThreadedNotifier(wm, EventHandler())
    notifier.start()
    # excl_lst = ["^/dev/shm", "^/dev/pts*"]
    # excl = pyinotify.ExcludeFilter(excl_lst)
    # wdd = wm.add_watch("/dev/bus", mask, rec=True, exclude_filter=excl)
    wdd = wm.add_watch("/dev/bus", mask, rec=True)

    async def lsusb(call):
        # check if the call was from scheduler or service / web app
        devices = _lsusb()
        for device in devices:
            if device["id"] == G_ZIGBEE_ID:
                # USB zigbee dongle
                prepare_usb_device(hass, device)

    hass.services.async_register(DOMAIN, "lsusb", lsusb)
    return True


def _lsusb():
    device_re = re.compile(
        "Bus\s+(?P<bus>\d+)\s+Device\s+(?P<device>\d+).+ID\s(?P<id>\w+:\w+)", re.I
    )
    df = subprocess.check_output("lsusb")
    devices = []
    for i in df.decode("utf-8").split("\n"):
        if i:
            info = device_re.match(i)
            if info:
                dinfo = info.groupdict()
                devices.append(dinfo)

    di = subprocess.check_output("ls /sys/bus/usb/devices", shell=True)
    for d in di.decode("utf-8").split("\n"):
        try:
            id_vendor = (
                subprocess.check_output(
                    "cat /sys/bus/usb/devices/" + d + "/idVendor", shell=True
                )
                .decode("utf-8")
                .strip()
            )
            id_product = (
                subprocess.check_output(
                    "cat /sys/bus/usb/devices/" + d + "/idProduct", shell=True
                )
                .decode("utf-8")
                .strip()
            )
            product = (
                subprocess.check_output(
                    "cat /sys/bus/usb/devices/" + d + "/product", shell=True
                )
                .decode("utf-8")
                .strip()
            )
            try:
                manufacturer = (
                    subprocess.check_output(
                        "cat /sys/bus/usb/devices/" + d + "/manufacturer", shell=True
                    )
                    .decode("utf-8")
                    .strip()
                )
                manufacturer = " producent " + manufacturer
            except Exception as e:
                manufacturer = " "

            _LOGGER.info("id_vendor: " + id_vendor)
            _LOGGER.info("id_product: " + id_product)
            for device in devices:
                if device["id"] == id_vendor + ":" + id_product:
                    device["product"] = product
                    device["manufacturer"] = manufacturer
                    device["info"] = "urządzenie " + product + manufacturer
                    # special cases
                    if device["id"] == G_ZIGBEE_ID:
                        # USB zigbee dongle
                        device["info"] = "urządzenie Zigbee" + product + manufacturer
                    if device["id"] == G_AIS_REMOTE_ID:
                        # USB ais remote dongle
                        device[
                            "info"
                        ] = "urządzenie Pilot radiowy, producent AI-Speaker"

        except Exception as e:
            _LOGGER.info(str(e))

    return devices