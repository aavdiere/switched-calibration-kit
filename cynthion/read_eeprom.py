#!/usr/bin/env python3

import argparse
import usb.core
import usb.util
import sys
from typing import cast


def find_ecal_device() -> usb.core.Device | None:
    """Find the USB ECal device with vendor ID 0x0957 and product ID 0x0001."""
    # device = usb.core.find(idVendor=0x0957, idProduct=0x0001)
    # device = usb.core.find(idVendor=0x2A8D, idProduct=0x3F01)
    device = usb.core.find(
        custom_match=lambda d: (d.idVendor == 0x0957 and d.idProduct == 0x0001)
        or (d.idVendor == 0x2A8D and d.idProduct == 0x3F01)
    )
    if device is None:
        print("USB ECal device not found. Please ensure it's connected.")
        return None

    print(f"Found device: {device}")
    return cast(usb.core.Device, device)


def set_eeprom_address(device: usb.core.Device, address: int) -> bool:
    """Set the EEPROM address using vendor request #4.

    For addresses > 0xFFFF, the upper 16 bits go in wValue and lower 16 bits in wIndex.
    """
    try:
        # Split 32-bit address into upper and lower 16-bit parts
        address_low = address & 0xFFFF  # Lower 16 bits
        address_high = (address >> 16) & 0xFFFF  # Upper 16 bits

        # Vendor request #4: OUT direction
        result = device.ctrl_transfer(
            bmRequestType=0x41,  # Vendor request, host to device
            bRequest=4,  # Vendor request number 4
            wValue=address_high,  # Upper 16 bits of address
            wIndex=address_low,  # Lower 16 bits of address
            data_or_wLength=0,  # No data payload
        )
        return True
    except usb.core.USBError as e:
        print(f"Error setting EEPROM address 0x{address:08X}: {e}")
        return False


def set_bytes_to_read(device: usb.core.Device, num_bytes: int) -> bool:
    """Set the number of bytes to read using vendor request #2.

    Limited to 16 bits (max 65535 bytes).
    """
    try:
        # Ensure we don't exceed 16-bit limit
        if num_bytes > 0xFFFF:
            print(
                f"Warning: Requested bytes ({num_bytes}) exceeds 16-bit limit, clamping to 65535"
            )
            num_bytes = 0xFFFF

        # Vendor request #2: OUT direction, set byte count in wValue
        result = device.ctrl_transfer(
            bmRequestType=0x41,  # Vendor request, host to device
            bRequest=2,  # Vendor request number 2
            wValue=num_bytes,  # Number of bytes to read (max 0xFFFF)
            wIndex=0,  # Not used for byte count
            data_or_wLength=0,  # No data payload
        )
        return True
    except usb.core.USBError as e:
        print(f"Error setting bytes to read: {e}")
        return False


def set_state(device: usb.core.Device, state: int) -> bool:
    """Set the state using vendor request #1."""
    try:
        # Vendor request #1: OUT direction, set state in wValue
        result = device.ctrl_transfer(
            bmRequestType=0x41,  # Vendor request, host to device
            bRequest=1,  # Vendor request number 1
            wValue=state,  # State to set
            wIndex=0,  # Not used
            data_or_wLength=0,  # No data payload
        )
        return True
    except usb.core.USBError as e:
        print(f"Error setting state: {e}")
        return False


def read_eeprom_chunk(
    device: usb.core.Device, address: int, chunk_size: int
) -> bytes | None:
    """Read a single chunk of EEPROM data at the specified address.

    Handles 16-bit limitations of USB control transfers.
    """
    try:
        # Ensure chunk size doesn't exceed 16-bit limit
        if chunk_size > 0xFFFF:
            print(
                f"Warning: Chunk size {chunk_size} exceeds 16-bit limit, clamping to 65535"
            )
            chunk_size = 0xFFFF

        # Set EEPROM address for this chunk
        if not set_eeprom_address(device, address):
            return None

        # Set number of bytes to read for this chunk
        if not set_bytes_to_read(device, chunk_size):
            return None

        # Read the chunk data
        data = bytearray()
        bytes_remaining = chunk_size
        packet_size = 64  # Max packet size

        while bytes_remaining > 0:
            # Read up to packet_size bytes at a time
            bytes_to_read = min(packet_size, bytes_remaining)
            try:
                chunk = device.read(0x81, bytes_to_read, timeout=1000)
                data.extend(chunk)
                bytes_remaining -= len(chunk)

                # If we got less than requested, we might be at the end
                if len(chunk) < bytes_to_read:
                    break

            except (usb.core.USBTimeoutError, usb.core.USBError) as e:
                if "Operation timed out" in str(e) or isinstance(
                    e, usb.core.USBTimeoutError
                ):
                    # Timeout likely means we've reached the end of valid data
                    break
                else:
                    raise

        return bytes(data)
    except usb.core.USBError as e:
        print(f"Error reading EEPROM chunk at address 0x{address:08X}: {e}")
        return None


def read_eeprom_chunked(
    max_size: int = 262 * 1024, chunk_size: int = 512
) -> bytes | None:
    """Read EEPROM data in chunks, making separate requests for each chunk."""
    device = find_ecal_device()
    if device is None:
        return None

    try:
        # Detach kernel driver if necessary
        if device.is_kernel_driver_active(0):
            device.detach_kernel_driver(0)

        # Set configuration
        device.set_configuration()

        all_data = bytearray()
        current_address = 0
        expected_address = 0  # Track expected next address for gap detection
        chunk_count = 0
        consecutive_empty_chunks = 0
        max_empty_chunks = 5  # Stop after 5 consecutive empty/failed chunks

        print(f"Reading EEPROM in {chunk_size}-byte chunks...")

        while (
            len(all_data) < max_size
            and consecutive_empty_chunks < max_empty_chunks
        ):
            # Calculate how much we still need to read
            bytes_remaining = max_size - len(all_data)
            current_chunk_size = min(chunk_size, bytes_remaining)

            # Check for address gap (assert no gaps are present)
            if chunk_count > 0:  # Skip check for first chunk
                assert current_address == expected_address, (
                    f"Address gap detected! Expected address 0x{expected_address:08X}, "
                    f"but current address is 0x{current_address:08X}. "
                    f"Gap of {current_address - expected_address} bytes found."
                )

            # Read this chunk
            chunk_data = read_eeprom_chunk(
                device, current_address, current_chunk_size
            )

            if chunk_data is None or len(chunk_data) == 0:
                consecutive_empty_chunks += 1
                current_address += current_chunk_size
                expected_address = current_address  # Update expected address even for failed chunks
                continue

            # Reset empty chunk counter if we got data
            consecutive_empty_chunks = 0

            # Only take the data we need (in case we got more than requested)
            needed_bytes = min(len(chunk_data), bytes_remaining)
            all_data.extend(chunk_data[:needed_bytes])
            chunk_count += 1

            # Progress indicator every 16 chunks
            if chunk_count % 16 == 0:
                print(
                    f"Progress: Read {chunk_count} chunks, {len(all_data)} bytes total (address: 0x{current_address:08X})"
                )

            current_address += current_chunk_size
            expected_address = current_address  # Update expected next address

        print(
            f"\nRead completed: {len(all_data)} bytes total from {chunk_count} successful chunks"
        )
        return bytes(all_data)

    except usb.core.USBError as e:
        print(f"USB error: {e}")
        return None
    finally:
        # Release the device
        usb.util.dispose_resources(device)


def main() -> None:
    """Main function to demonstrate EEPROM reading."""
    parser = argparse.ArgumentParser(
        description="Read EEPROM data from Agilent USB ECal Module"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="eeprom_dump.bin",
        help="Output filename for the EEPROM data (default: eeprom_dump.bin)",
    )
    parser.add_argument(
        "-s",
        "--size",
        type=str,
        default="64k",
        help="Total size to read (e.g., 64k, 1M, 4M). Default: 64k",
    )

    args = parser.parse_args()

    # Parse size argument
    size_str = args.size.lower()
    if size_str.endswith("k"):
        total_size = int(size_str[:-1]) * 1024
    elif size_str.endswith("m"):
        total_size = int(size_str[:-1]) * 1024 * 1024
    else:
        total_size = int(size_str)

    # Automatically determine optimal chunk size that doesn't exceed 0xFFFF
    # Use 4KB chunks for efficiency while staying well under the 64KB limit
    chunk_size = min(4 * 1024, 0xFFFF, total_size)  # 4KB or smaller

    print(f"Reading {total_size // 1024} KB total in {chunk_size}-byte chunks")
    if total_size > 0xFFFF:
        print(
            "Note: Using extended addressing (wValue for upper 16 bits) for addresses > 65535"
        )
    print(
        "Will stop automatically when device stops responding or at end of data"
    )

    data = read_eeprom_chunked(total_size, chunk_size)

    if data:
        print(f"Successfully read {len(data)} bytes:")
        # Print first 256 bytes as hex dump for verification
        print("First 256 bytes:")
        for i in range(0, min(256, len(data)), 16):
            hex_part = " ".join(f"{b:02x}" for b in data[i : i + 16])
            ascii_part = "".join(
                chr(b) if 32 <= b < 127 else "." for b in data[i : i + 16]
            )
            print(f"{i:04x}: {hex_part:<48} {ascii_part}")

        if len(data) > 256:
            print(f"... ({len(data) - 256} more bytes)")

        # Save to specified output file
        with open(args.output, "wb") as f:
            f.write(data)
        print(f"Data saved to {args.output}")
    else:
        print("Failed to read EEPROM data")
        sys.exit(1)


if __name__ == "__main__":
    main()
