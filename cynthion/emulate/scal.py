#! /usr/bin/env python3

from facedancer.configuration import USBConfiguration
from facedancer.descriptor import StringRef
from facedancer.device import USBDevice
from facedancer.devices import default_main
from facedancer.endpoint import USBEndpoint
from facedancer.interface import USBInterface
from facedancer.magic import use_inner_classes_automatically
from facedancer.request import (
    USBControlRequest,
    vendor_request_handler,
    to_this_interface,
)
from facedancer.types import DeviceSpeed, USBDirection

from cynthion import Cynthion
from cynthion.interfaces.gpio import PinDirection

import subprocess
import skrf
import time

from eeprom import EEPROM, date
from enum import IntEnum
from pyftdi.gpio import GpioController


# gpio settings
# 2 bit = 4-port switch (port 2)
# 1 bit = 2-port switch (port 2)
# 1 bit = 2-port switch (port 1)
# 2 bit = 4-port switch (port 1)
class PORT1(IntEnum):
    SHORT = 0b00_0_0_01
    OPEN = 0b00_0_0_10
    LOAD = 0b00_0_0_00
    THRU = 0b00_0_1_11
    ATT = 0b00_0_0_11
    LOAD2 = 0b00_0_1_00
    SHORT2 = 0b00_0_1_01
    OPEN2 = 0b00_0_1_10


# 2 MSB = 4-port switch
# 1 LSB = 2-port THRU/ATT switch
class PORT2(IntEnum):
    SHORT = 0b11_0_0_00
    OPEN = 0b00_0_0_00
    LOAD = 0b10_0_0_00
    THRU = 0b01_0_0_00
    ATT = 0b01_1_0_00
    OPEN2 = 0b00_1_0_00
    LOAD2 = 0b10_1_0_00
    SHORT2 = 0b11_1_0_00


gpio = GpioController()
gpio.configure(
    "ftdi://ftdi:232h:FT07ND6B/1",
    direction=0b0011_1111,
    frequency=1e3,
    initial=PORT1.LOAD | PORT2.LOAD,
)


# fp = open("n4691d.log", "w")

eeprom = EEPROM(
    nports=2,
    serial="AV42069",
    connector_info="35F 35F",
    model="BGS1412",
    mfg_date=date(2026, 7, 14),
    mfg_location="Belgium Flanders",
    lot_code="000000000",
    configs=[
        [
            skrf.Network(
                f"data/scal/eeprom-{config_a | PORT2.LOAD}.s2p",
                name=str(config_a | PORT2.LOAD),
            ).s11
            for config_a in [PORT1.OPEN, PORT1.SHORT, PORT1.LOAD, PORT1.THRU]
        ],
        [
            skrf.Network(
                f"data/scal/eeprom-{PORT1.LOAD | config_b}.s2p",
                name=str(PORT1.LOAD | config_b),
            ).s22
            for config_b in [PORT2.OPEN, PORT2.SHORT, PORT2.LOAD, PORT2.THRU]
        ],
        [
            skrf.Network(
                f"data/scal/eeprom-{PORT1.THRU | PORT2.THRU}.s2p",
                name=str(PORT1.THRU | PORT2.THRU),
            )
        ],
        [
            skrf.Network(
                f"data/scal/eeprom-{PORT1.ATT | PORT2.ATT}.s2p",
                name=str(PORT1.ATT | PORT2.ATT),
            )
        ],
    ],
    freq_break=None,
    default_config=None,
    confidence_config=None,
    options="None",
)
eeprom.to_file("data/EEPROM/scal.bin")


@use_inner_classes_automatically
class SCalDevice(USBDevice):  # type: ignore[misc]
    vendor_id: int = 0x2A8D
    product_id: int = 0x3F01

    manufacturer_string: StringRef = StringRef(
        string="Achim Technologies, Uninc."
    )
    product_string: StringRef = StringRef(string="SCal Module")
    serial_number_string: StringRef = StringRef(string=f"S/N {eeprom.serial}")
    device_speed: DeviceSpeed = DeviceSpeed.HIGH

    address: int = 0
    bytes_requested: int = 0
    config: int = 0
    data: bytes = open("data/EEPROM/scal.bin", "rb").read()

    @vendor_request_handler(number=4, direction=USBDirection.OUT)  # type: ignore[misc]
    @to_this_interface  # type: ignore[misc]
    def handle_control_request_4(self, request: USBControlRequest) -> None:
        # print(request)
        print(
            f"Vendor request #{request.number}, index {request.index}, value {request.value}, data ["
            + ", ".join(f"{d:02x}" for d in request.data)
            + "]",
            # file=fp,
        )
        # fp.flush()

        self.address = (request.value << 16) | request.index
        request.ack()

    @vendor_request_handler(number=2, direction=USBDirection.OUT)  # type: ignore[misc]
    @to_this_interface  # type: ignore[misc]
    def handle_control_request_2(self, request: USBControlRequest) -> None:
        # print(request)
        print(
            f"Vendor request #{request.number}, index {request.index}, value {request.value}, data ["
            + ", ".join(f"{d:02x}" for d in request.data)
            + "]",
            # file=fp,
        )
        # fp.flush()

        self.bytes_requested = request.value
        request.ack()

    @vendor_request_handler(number=1, direction=USBDirection.OUT)  # type: ignore[misc]
    @to_this_interface  # type: ignore[misc]
    def handle_control_request_1(self, request: USBControlRequest) -> None:
        # print(request)

        if self.vendor_id == 0x2A8D and self.product_id == 0x3F01:
            self.config = int.from_bytes(
                request.data, byteorder="little", signed=False
            )
            print(
                f"Vendor request #{request.number}, index {request.index}, value {request.value}, data [{PORT1(self.config & 0b000_111).name}, {PORT2(self.config & 0b111_000).name}]",
                # file=fp,
            )
            # fp.flush()
        else:
            self.config = request.value
            print(
                f"Vendor request #{request.number}, index {request.index}, value {request.value}, data ["
                + ", ".join(f"{d:02x}" for d in request.data)
                + "]",
                # file=fp,
            )
            # fp.flush()

        gpio.write(self.config)
        time.sleep(1)

        request.ack()

    class ECalConfiguration(USBConfiguration):  # type: ignore[misc]
        class ECalInterface(USBInterface):  # type: ignore[misc]
            class ECalInEndpoint(USBEndpoint):  # type: ignore[misc]
                number: int = 1
                direction: USBDirection = USBDirection.IN

                def handle_data_requested(self) -> None:
                    # get device
                    dev: SCalDevice = self.get_device()
                    dev_data = bytearray(dev.data)

                    # send packet of data, either max packet size or remaining bytes
                    bytes_to_send = min(
                        self.max_packet_size, dev.bytes_requested
                    )

                    if dev.address >= len(dev_data):
                        print(
                            f"Warning: Requested address {dev.address} exceeds data length {len(dev_data)}. Sending 0xff bytes.",
                            # file=fp,
                        )
                        # fp.flush()

                        data = b"\xff" * bytes_to_send
                    elif dev.address + bytes_to_send > len(dev_data):
                        print(
                            f"Warning: Requested address {dev.address} + bytes to send {bytes_to_send} exceeds data length {len(dev_data)}. Clamping to available data.",
                            # file=fp,
                        )
                        # fp.flush()

                        data = dev_data[dev.address :] + b"\xff" * (
                            bytes_to_send - (len(dev_data) - dev.address)
                        )
                    else:
                        data = dev_data[
                            dev.address : dev.address + bytes_to_send
                        ]

                    # update state
                    dev.address += bytes_to_send
                    dev.bytes_requested -= bytes_to_send

                    print(
                        f"Bulk transfer of {len(data)} bytes on endpoint 1 IN: [{data.hex()}]",
                        # file=fp,
                    )
                    # fp.flush()

                    self.send(data)

            class ECalOutEndpoint(USBEndpoint):  # type: ignore[misc]
                number: int = 1
                direction: USBDirection = USBDirection.OUT

                def handle_data_received(self, data: bytes) -> None:
                    print(
                        f"Received data: {data!r}",
                        # file=fp,
                    )
                    # fp.flush()


default_main(SCalDevice)
