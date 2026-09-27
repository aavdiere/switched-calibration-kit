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
    to_device,
    to_this_interface,
)
from facedancer.types import DeviceSpeed, USBDirection

from cynthion import Cynthion
from cynthion.interfaces.gpio import PinDirection

import subprocess

fp = open("n4691-6006.log", "w")


@use_inner_classes_automatically
class ECalDevice(USBDevice):  # type: ignore[misc]
    vendor_id: int = 0x0957
    product_id: int = 0x0001

    manufacturer_string: StringRef = StringRef(string="Agilent Technologies")
    product_string: StringRef = StringRef(string="USB ECal Module")
    serial_number_string: StringRef = StringRef(string="S/N 07576")
    device_speed: DeviceSpeed = DeviceSpeed.FULL

    address: int = 0
    bytes_requested: int = 0
    config: int = 0
    data: bytes = open("data/EEPROM/n4691-60006.bin", "rb").read()

    @vendor_request_handler(number=4, direction=USBDirection.OUT)  # type: ignore[misc]
    @to_this_interface  # type: ignore[misc]
    def handle_control_request_4(self, request: USBControlRequest) -> None:
        # print(request)
        print(
            f"Vendor request #{request.number}, index {request.index}, value {request.value}"
        )
        self.address = (request.value << 16) | request.index
        request.ack()

    @vendor_request_handler(number=2, direction=USBDirection.OUT)  # type: ignore[misc]
    @to_this_interface  # type: ignore[misc]
    def handle_control_request_2(self, request: USBControlRequest) -> None:
        # print(request)
        print(
            f"Vendor request #{request.number}, index {request.index}, value {request.value}"
        )
        self.bytes_requested = request.value
        request.ack()

    @vendor_request_handler(number=1, direction=USBDirection.OUT)  # type: ignore[misc]
    @to_this_interface  # type: ignore[misc]
    def handle_control_request_1(self, request: USBControlRequest) -> None:
        # print(request)
        print(
            f"Vendor request #{request.number}, index {request.index}, value {request.value}"
        )
        self.config = request.value

        subprocess.run(["python3", "set_state.py", str(self.config)])

        request.ack()

    class ECalConfiguration(USBConfiguration):  # type: ignore[misc]
        class ECalInterface(USBInterface):  # type: ignore[misc]
            class ECalInEndpoint(USBEndpoint):  # type: ignore[misc]
                number: int = 1
                direction: USBDirection = USBDirection.IN

                def handle_data_requested(self) -> None:
                    # get device
                    dev: ECalDevice = self.get_device()
                    dev_data = bytearray(dev.data)

                    # send packet of data, either max packet size or remaining bytes
                    bytes_to_send = min(
                        self.max_packet_size, dev.bytes_requested
                    )

                    if dev.address >= len(dev_data):
                        print(
                            f"Warning: Requested address {dev.address} exceeds data length {len(dev_data)}. Sending 0xff bytes.",
                            file=fp,
                        )
                        data = b"\xff" * bytes_to_send
                    elif dev.address + bytes_to_send > len(dev_data):
                        print(
                            f"Warning: Requested address {dev.address} + bytes to send {bytes_to_send} exceeds data length {len(dev_data)}. Clamping to available data.",
                            file=fp,
                        )
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
                        f"Bulk transfer of {len(data)} bytes on endpoint 1 IN: [{data.hex()}]"
                    )
                    self.send(data)

            class ECalOutEndpoint(USBEndpoint):  # type: ignore[misc]
                number: int = 1
                direction: USBDirection = USBDirection.OUT

                def handle_data_received(self, data: bytes) -> None:
                    print(f"Received data: {data!r}")


default_main(ECalDevice)
