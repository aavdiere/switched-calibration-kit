import time
import math
import skrf

import matplotlib as mpl
import numpy as np
from cycler import cycler
from enum import IntEnum

from idpy.instruments.keysight.fieldfox import KeysightN9917A

# Plotting settings
mpl.rcParams["pdf.fonttype"] = 42  # TrueType
mpl.rcParams["ps.fonttype"] = 42  # TrueType

mpl.rcParams["font.family"] = "Helvetica Neue"
mpl.rcParams["font.size"] = 10

mpl.rcParams["text.color"] = "#333"

mpl.rcParams["figure.figsize"] = (6.3, 3.6)

mpl.rcParams["axes.edgecolor"] = "#333"
mpl.rcParams["axes.labelcolor"] = "#333"
mpl.rcParams["axes.titlecolor"] = "#333"
mpl.rcParams["axes.prop_cycle"] = cycler(
    "color", ["#333", "#ccc", "#a6cee3", "#1f78b4", "#b2df8a", "#33a02c"]
)
mpl.rcParams["axes.spines.top"] = False
mpl.rcParams["axes.spines.bottom"] = False
mpl.rcParams["axes.spines.left"] = False
mpl.rcParams["axes.spines.right"] = False

mpl.rcParams["xtick.color"] = "#333"
mpl.rcParams["ytick.color"] = "#333"

mpl.rcParams["legend.edgecolor"] = "#fff"
mpl.rcParams["legend.frameon"] = True
mpl.rcParams["legend.facecolor"] = "#fff"
mpl.rcParams["legend.framealpha"] = 0.8
mpl.rcParams["legend.labelcolor"] = "#333"


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


class ProgressBar:
    def __init__(
        self,
        total: int,
        decay: float = 1e-5,
        prefix: str = "",
        suffix: str = "",
        decimals: int = 1,
        length: int = 50,
        fill: str = "█",
        print_end: str = "\r",
    ) -> None:
        """
        Call in a loop to create terminal progress bar
        @params:
            iteration   - Required  : current iteration (Int)
            total       - Required  : total iterations (Int)
            prefix      - Optional  : prefix string (Str)
            suffix      - Optional  : suffix string (Str)
            timedelta   - Optional  : timedelta (Float)
            decimals    - Optional  : positive number of decimals in percent
                                    complete (Int)
            length      - Optional  : character length of bar (Int)
            fill        - Optional  : bar fill character (Str)
            printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
        """
        self.total: int = total
        self.__prefix = prefix
        self.__suffix = suffix
        self.__decimals = decimals
        self.__length = length
        self.__fill = fill
        self.__print_end = print_end

        self.iteration = 0
        self.__timedelta = -1.0
        self.__remaining = -1.0
        self.__done = 0.0
        self.__starttime = time.time()
        self.__abstime = time.time()

        self.decay = decay

        self.print()

    def print(self) -> None:
        percent = ("{0:." + str(self.__decimals) + "f}").format(
            100 * (self.iteration / float(self.total))
        )
        filled_length = int(self.__length * self.iteration // self.total)
        bar = self.__fill * filled_length + "-" * (
            self.__length - filled_length
        )

        done_h = math.floor(self.__done / 3600)
        done_m = math.floor((self.__done - done_h * 3600) / 60)
        done_s = math.floor(self.__done - done_h * 3600 - done_m * 60)

        if self.__remaining < 0:
            print(
                f"\r{self.__prefix} |{bar}| {percent}% {self.__suffix}"
                f" ({done_h:02d}:{done_m:02d}:{done_s:02d} done"
                # f" / XX:XX:XX remaining"
                ")",
                end=self.__print_end,
            )
        else:
            remaining_h = math.floor(self.__remaining / 3600)
            remaining_m = math.floor(
                (self.__remaining - remaining_h * 3600) / 60
            )
            remaining_s = math.floor(
                self.__remaining - remaining_h * 3600 - remaining_m * 60
            )

            print(
                f"\r{self.__prefix} |{bar}| {percent}% {self.__suffix}"
                f" ({done_h:02d}:{done_m:02d}:{done_s:02d} done"
                f" / {remaining_h:02d}:{remaining_m:02d}:{remaining_s:02d}"
                f" remaining)",
                end=self.__print_end,
            )

        if self.iteration == self.total:
            print(
                f"\r{self.__prefix} |{bar}| {percent}% {self.__suffix}"
                f" ({done_h:02d}:{done_m:02d}:{done_s:02d} done)"
                f"                      "
            )

    def tick(self) -> None:
        self.iteration += 1

        endtime = time.time()

        dt = endtime - self.__starttime

        if self.iteration == 1:
            self.__timedelta = -1.0
        elif self.iteration < 0.2 * self.total:
            if self.__timedelta < 0:
                self.__timedelta = 0

            self.__timedelta = (
                dt + ((self.iteration - 2) * self.__timedelta)
            ) / (self.iteration - 1)
        else:
            self.__timedelta = (
                self.decay * dt + (1 - self.decay) * self.__timedelta
            )

        self.__done = endtime - self.__abstime

        self.__remaining = (self.total - self.iteration) * self.__timedelta
        self.print()
        self.__starttime = endtime


# get S parameters in scikit-rf format
def perform_sweep(
    vna: KeysightN9917A, progress_bar: ProgressBar | None = None
) -> None:
    # Single sweep
    vna.write("SENSe:AVERage:CLEar")
    vna.write("INITiate:CONTinuous 0")

    num_avg = int(vna.query("SENSe:AVERage:COUNt?"))

    if vna.average.mode != vna.average.AVERAGE_MODE.SWEEP:
        num_avg = 1

    if progress_bar is None:
        progress_bar = ProgressBar(num_avg)

    # Repeat sweep for the amount of averaging we have
    for _ in range(num_avg):
        # Clear Event Status Register
        vna.clear()

        # Perform single sweep
        # Signal to instrument to set the OPC flag if the queue up until now
        # has been processed
        vna.write("INITiate:IMMediate;*OPC")

        done = False

        # Wait for the operation to complete
        # The instrument will signal that the operation is complete
        # by setting the LSB of the ESR register high
        # print("Sweep busy", end="")
        while not done:
            time.sleep(0.5)
            # print(".", end="")
            done = vna.esr() & 1 == 1

        progress_bar.tick()

        # print("\rSweep done")


def get_s1p(vna: KeysightN9917A) -> skrf.Network:
    # Set format
    vna.write("FORM REAL,64")

    frequency: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        vna.query_binary_values(
            # "SENS1:X:VALUES?",  # PNA-X
            "SENS:FREQ:DATA?",  # FieldFox
            datatype="d",
            # is_big_endian=True,  # PNA-X
            is_big_endian=False,  # FieldFox
            container=np.array,  # type: ignore[reportAssignmentType]
        )
    )

    vna.network_analyzer.window.windows[0].select()
    s11: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        vna.query_binary_values(
            # "CALC1:MEAS1:DATA:SDATA?",  # PNA-X
            "CALC:DATA:SDAT?",  # FieldFox
            datatype="d",
            # is_big_endian=True,  # PNA-X
            is_big_endian=False,  # FieldFox
            container=np.array,  # type: ignore[reportAssignmentType]
        )
    )

    s = np.zeros((len(frequency), 1, 1), dtype=complex)

    s[:, 0, 0] = s11[::2] + 1j * s11[1::2]

    return skrf.Network(f=frequency, s=s, f_unit="Hz")


def get_s2p(vna: KeysightN9917A) -> skrf.Network:
    # Set format
    vna.write("FORM REAL,64")

    frequency: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        vna.query_binary_values(
            # "SENS1:X:VALUES?",  # PNA-X
            "SENS:FREQ:DATA?",  # FieldFox
            datatype="d",
            # is_big_endian=True,  # PNA-X
            is_big_endian=False,  # FieldFox
            container=np.array,  # type: ignore
        )
    )

    vna.network_analyzer.window.windows[0].select()
    s11: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        vna.query_binary_values(
            # "CALC1:MEAS1:DATA:SDATA?",  # PNA-X
            "CALC:DATA:SDAT?",  # FieldFox
            datatype="d",
            # is_big_endian=True,  # PNA-X
            is_big_endian=False,  # FieldFox
            container=np.array,  # type: ignore
        )
    )

    vna.network_analyzer.window.windows[1].select()
    s21: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        vna.query_binary_values(
            # "CALC1:MEAS2:DATA:SDATA?",  # PNA-X
            "CALC:DATA:SDAT?",  # FieldFox
            datatype="d",
            # is_big_endian=True,  # PNA-X
            is_big_endian=False,  # FieldFox
            container=np.array,  # type: ignore
        )
    )

    vna.network_analyzer.window.windows[2].select()
    s12: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        vna.query_binary_values(
            # "CALC1:MEAS3:DATA:SDATA?",  # PNA-X
            "CALC:DATA:SDAT?",  # FieldFox
            datatype="d",
            # is_big_endian=True,  # PNA-X
            is_big_endian=False,  # FieldFox
            container=np.array,  # type: ignore
        )
    )

    vna.network_analyzer.window.windows[3].select()
    s22: np.ndarray[tuple[int], np.dtype[np.float64]] = (
        vna.query_binary_values(
            # "CALC1:MEAS4:DATA:SDATA?",  # PNA-X
            "CALC:DATA:SDAT?",  # FieldFox
            datatype="d",
            # is_big_endian=True,  # PNA-X
            is_big_endian=False,  # FieldFox
            container=np.array,  # type: ignore
        )
    )

    s = np.zeros((len(frequency), 2, 2), dtype=complex)

    s[:, 0, 0] = s11[::2] + 1j * s11[1::2]
    s[:, 1, 0] = s21[::2] + 1j * s21[1::2]
    s[:, 0, 1] = s12[::2] + 1j * s12[1::2]
    s[:, 1, 1] = s22[::2] + 1j * s22[1::2]

    return skrf.Network(f=frequency, s=s, f_unit="Hz")


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
