from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
from numpy import float64 as double
from numpy import float32 as float
from numpy import complex64 as complex

from struct import unpack_from, pack_into

from skrf import Network


# This function Converts Byte block to Hex
# data type of byte_block parameter is bytes -> b'text_here'
def convert_to_hex(byte_block: bytearray) -> str:
    hex = [f"{x:02x}" for x in byte_block]  # Get each byte and convert to hex
    hex_out = []
    for x in range(0, len(hex), 2):
        hex_out.append(
            "".join(hex[x : x + 2])
        )  # Converted Hex chars like ['1a12', '23ab',....]
    return " ".join(hex_out)  # convert hex_out list to string


# This function checks whether the character printable or not
def hex_checker(data: bytearray) -> str:
    str_array = ""
    for x in data:
        if (
            x > 31 and x < 127
        ):  # 0-32 characters are allocated as device control characters
            str_array = str_array + chr(x)
        else:
            str_array = str_array + "."
    return str_array


@dataclass
class EEPROM:
    nports: int

    serial: str
    connector_info: str
    model: str

    mfg_date: date
    mfg_location: str
    lot_code: str

    configs: list[list[Network]]

    # of these values I am still unsure of, they don't seem to be used
    freq_break: double | None = None

    default_config: int | None = None
    confidence_config: int | None = None

    options: str = "None"

    @staticmethod
    def _extract_string(data: bytes, offset: int, max_length: int) -> str:
        length = 0
        for i in range(max_length):
            if data[offset + i] == 0x00:
                break
            else:
                length += 1

        if length != 0:
            return str(
                unpack_from(f"<{length}s", data, offset)[0].decode("utf-8")
            )
        else:
            return ""

    @staticmethod
    def _insert_string(
        data: bytearray, offset: int, max_length: int, value: str
    ) -> None:
        if len(value) + 1 > max_length:
            raise ValueError(
                f"String '{value}' exceeds maximum length of {max_length}"
            )

        # Insert the string into the data
        pack_into(f"<{len(value) + 1}s", data, offset, value.encode("utf-8"))

        # Fill the remaining space with 0xFF
        for i in range(len(value) + 1, max_length):
            data[offset + i] = 0xFF

    @staticmethod
    def from_file(file: str) -> "EEPROM":
        nports: int
        serial: str = ""
        connector_info: str = ""
        mfg_date: date = date(2024, 1, 1)
        mfg_location: str = ""
        lot_code: str = ""
        model: str = ""
        options: str = "None"
        freq_start: double = double(-1)
        freq_stop: double = double(-1)
        freq_break: double | None = None
        default_config: int | None = None
        confidence_config: int | None = None

        with open(file, "rb") as f:
            data = f.read()

        nports = unpack_from("<h", data, 0x36)[0]

        serial = EEPROM._extract_string(data, 0x64, 12)
        connector_info = EEPROM._extract_string(data, 0x70, 20)
        mfg_date_raw = EEPROM._extract_string(data, 0x84, 12)
        if mfg_date_raw != "":
            mfg_date = datetime.strptime(mfg_date_raw, "%d/%b/%Y").date()

        mfg_location = EEPROM._extract_string(data, 0x90, 40)
        lot_code = EEPROM._extract_string(data, 0xB8, 20)

        freq_start = unpack_from("<d", data, 0xCC)[0]
        freq_stop = unpack_from("<d", data, 0xD4)[0]

        npoints = unpack_from("<H", data, 0xDC)[0]

        if data[0xE0] != 0xFF:
            freq_break = unpack_from("<d", data, 0xE0)[0]

        model = EEPROM._extract_string(data, 0xF0, 20)

        if data[0x104] != 0xFF:
            default_config = unpack_from("<H", data, 0x104)[0]

        if data[0x106] != 0xFF:
            confidence_config = unpack_from("<H", data, 0x106)[0]

        options = EEPROM._extract_string(data, 0x108, 40)

        nfreq = unpack_from("<H", data, 0x190)[0]
        freq_addr = unpack_from("<I", data, 0x192)[0]

        assert (
            nfreq == npoints
        ), f"Number of frequencies in EEPROM ({nfreq}) does not match number of points ({npoints})"

        freqs = np.frombuffer(
            data, dtype=double, count=nfreq, offset=freq_addr
        )

        assert (
            freqs[0] == freq_start
        ), f"Start frequency in EEPROM ({freqs[0]}) does not match start frequency ({freq_start})"
        assert (
            freqs[-1] == freq_stop
        ), f"Stop frequency in EEPROM ({freqs[-1]}) does not match stop frequency ({freq_stop})"

        configs: list[list[Network]] = []

        offset = 0x196
        while data[offset] != 0xFF and offset < 0x258:
            config_nstds = unpack_from("<H", data, offset)[0]
            config_npoints = unpack_from("<H", data, offset + 2)[0]
            config_nentries = unpack_from("<H", data, offset + 4)[0]
            config_header_addr = unpack_from("<I", data, offset + 6)[0]
            config_data_addr = unpack_from("<I", data, offset + 10)[0]

            assert (
                config_npoints == npoints
            ), f"Number of points in config {offset} ({config_npoints}) does not match number of points ({npoints})"

            config: list[Network] = [] * config_nstds

            dimen = int(np.sqrt(config_nentries // config_nstds))

            for std in range(config_nstds):
                id = unpack_from("<H", data, config_header_addr + std * 2)[0]
                config_s = np.zeros(
                    (config_npoints, dimen, dimen), dtype=complex
                )
                for l in range(dimen):
                    for m in range(dimen):
                        config_s[:, l, m] = np.frombuffer(
                            data,
                            dtype=complex,
                            count=config_npoints,
                            offset=config_data_addr
                            + (std * dimen * dimen + l * dimen + m)
                            * config_npoints
                            * 8,
                        )

                config.append(
                    Network(frequency=freqs, s=config_s, name=str(id))
                )

            assert (
                len(config) == config_nstds
            ), f"Number of configs in config {offset} ({len(config)}) does not match number of stds ({config_nstds})"

            configs.append(config)
            offset += 14

        return EEPROM(
            nports=nports,
            serial=serial,
            connector_info=connector_info,
            model=model,
            mfg_date=mfg_date,
            mfg_location=mfg_location,
            lot_code=lot_code,
            configs=configs,
            freq_break=freq_break,
            default_config=default_config,
            confidence_config=confidence_config,
            options=options,
        )

    def get_raw(self) -> bytearray:
        # calculate size
        npoints = self.configs[0][0].frequency.npoints
        eeprom_size = 0x258 + npoints * 8

        for idx in range(len(self.configs)):
            for ntwk in self.configs[idx]:
                eeprom_size += 1 + ntwk.s.size * 8

        # weird roundup
        eeprom_size = ((eeprom_size - 8 + 500) // 1000) * 1000 + 8 + 1000

        data = bytearray(b"\xff" * eeprom_size)

        # fixed header
        data[0:0x64] = (
            b"HP85060C ECAL\x00\xff\xff\xff\xff\xff\xffd\x00Nov 28 1994\x00d\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x02\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
        )

        pack_into("<h", data, 0x36, self.nports)

        EEPROM._insert_string(data, 0x64, 12, self.serial)
        EEPROM._insert_string(data, 0x70, 20, self.connector_info)
        EEPROM._insert_string(
            data,
            0x84,
            12,
            self.mfg_date.strftime("%d/%b/%Y"),
        )
        EEPROM._insert_string(data, 0x90, 40, self.mfg_location)
        EEPROM._insert_string(data, 0xB8, 20, self.lot_code)
        pack_into("<d", data, 0xCC, self.configs[0][0].frequency.f[0])
        pack_into("<d", data, 0xD4, self.configs[0][0].frequency.f[-1])
        pack_into("<H", data, 0xDC, npoints)
        # pack_into(
        #     "<H", data, 0xDE, 0x2BC
        # )  # 700 decimal, not sure what this is

        if self.freq_break is not None:
            pack_into("<d", data, 0xE0, self.freq_break)

        # pack_into("<H", data, 0xE8, 0x0028)  # not sure why
        # pack_into("<H", data, 0xEA, 0x0003)  # not sure why
        # pack_into("<H", data, 0xEC, 0x0021)  # not sure why
        # pack_into("<H", data, 0xEE, 0x0000)  # not sure why

        EEPROM._insert_string(data, 0xF0, 20, self.model)

        if self.default_config is not None:
            pack_into("<H", data, 0x104, self.default_config)

        if self.confidence_config is not None:
            pack_into("<H", data, 0x106, self.confidence_config)

        EEPROM._insert_string(data, 0x108, 40, self.options)

        pack_into("<I", data, 0x130, eeprom_size - 1000)
        pack_into("<I", data, 0x134, eeprom_size)

        freqs = self.configs[0][0].frequency.f
        assert (
            len(freqs) == npoints
        ), f"Number of frequencies ({len(freqs)}) does not match number of points ({npoints})"

        freq_addr = 0x258
        pack_into("<H", data, 0x190, npoints)
        pack_into("<I", data, 0x192, freq_addr)
        np.copyto(
            np.frombuffer(data, dtype=double, count=npoints, offset=freq_addr),
            freqs,
        )

        header_addr = 0x196
        config_addr = freq_addr + npoints * 8

        for config in self.configs:
            if header_addr >= 0x258:
                raise ValueError(
                    f"Config header address ({header_addr}) exceeds maximum header size"
                )

            config_nstds = len(config)
            config_npoints = npoints
            config_nentries = config_nstds * (config[0].nports ** 2)

            config_data_addr = config_addr + config_nstds * 2

            pack_into("<H", data, header_addr, config_nstds)
            header_addr += 2
            pack_into("<H", data, header_addr, config_npoints)
            header_addr += 2
            pack_into("<H", data, header_addr, config_nentries)
            header_addr += 2
            pack_into("<I", data, header_addr, config_addr)
            header_addr += 4
            pack_into("<I", data, header_addr, config_data_addr)
            header_addr += 4

            for std_idx in range(config_nstds):
                ntwk = config[std_idx]

                assert (
                    ntwk.frequency.npoints == npoints
                ), f"Number of points in network {ntwk.name} ({ntwk.frequency.npoints}) does not match number of points ({npoints})"

                pack_into(
                    "<H",
                    data,
                    config_addr + std_idx * 2,
                    int(ntwk.name),
                )

                np.copyto(
                    np.frombuffer(
                        data,
                        dtype=complex,
                        count=npoints * ntwk.nports * ntwk.nports,
                        offset=config_data_addr
                        + (std_idx * ntwk.nports * ntwk.nports) * npoints * 8,
                    ).reshape((npoints, ntwk.nports, ntwk.nports)),
                    ntwk.s,
                )

            config_addr = config_data_addr + config_nstds * npoints * 8 * (
                config[0].nports ** 2
            )

        return data

    def to_file(self, file: str) -> None:
        data = self.get_raw()

        with open(file, "wb") as f:
            f.write(data)

    def __str__(self) -> str:
        result = ""

        data = self.get_raw()

        for idx in range(0, len(data), 16):
            if idx + 16 >= len(data):
                block = data[idx:] + (idx + 16 - len(data)) * b"\xff"
            else:
                block = data[idx : idx + 16]

            result += (
                f"{idx:08x}: {convert_to_hex(block)}  {hex_checker(block)}\r\n"
            )

        return result
