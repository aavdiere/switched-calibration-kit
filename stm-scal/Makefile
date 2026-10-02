BINARY			?= stm-scal
DEVICE			?= STM32F042K6
BUILD_TYPE 		?= Release
BUILD_DIR		?= build
ifeq ($(BUILD_TYPE), Release)  # change to build-release for release builds
	BUILD_DIR := $(BUILD_DIR)-release
endif
FIRMWARE		?= $(BUILD_DIR)/$(BINARY).elf

# Derived from DEVICE, e.g. STM32L476RG -> stm32l476rg (linker script) and stm32l4 (family)
# Automatically adapts to the device name above
DEVICE_LC		:= $(shell echo $(DEVICE) | tr '[:upper:]' '[:lower:]')
FAMILY			:= $(shell echo $(DEVICE_LC) | cut -c1-7)
FAMILY_CMAKE	:= cmake/$(FAMILY).cmake
LINKER_SCRIPT	:= cmake/$(DEVICE_LC).ld
DEVICE_STAMP	:= $(BUILD_DIR)/.device-$(DEVICE_LC)

# Change build directory depending on the build type

PLATFORM 		= $(if $(OS),$(OS),$(shell uname -s))

.PHONY: all format build cmake clean flash-jlink flash-stlink monitor

# Verify platform
ifeq ($(PLATFORM),Windows_NT)
	@echo "Unsuported platform"
	exit 1
else
    ifeq ($(PLATFORM),Linux)
        BUILD_SYSTEM ?= Unix Makefiles
    else
        @echo "Unsuported platform"
        exit 1
    endif
endif

all: build
build: $(FIRMWARE)

# Formats all user modified source files (add ones that are missing)
SRCS := $(shell find src -name '*.[ch]' -or -name '*.[ch]pp')
format: $(addsuffix .format, $(SRCS))

%.format: %
	clang-format -i $<

$(FIRMWARE): cmake
	$(MAKE) -C $(BUILD_DIR) -j8 --no-print-directory

cmake: $(BUILD_DIR)/Makefile

$(BUILD_DIR)/Makefile: cmake/CMakeLists.txt $(FAMILY_CMAKE) $(LINKER_SCRIPT) cmake/toolchain-arm-none-eabi.cmake $(DEVICE_STAMP)
	cmake \
		-G "$(BUILD_SYSTEM)" \
		-B$(BUILD_DIR) \
		-DBINARY=$(BINARY) \
		-DDEVICE=$(DEVICE) \
		-DCMAKE_BUILD_TYPE=$(BUILD_TYPE) \
		cmake/

# Start from a clean build directory whenever DEVICE changes
$(DEVICE_STAMP):
	rm -rf $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)
	touch $@

$(FAMILY_CMAKE) $(LINKER_SCRIPT):
	$(error $@ not found for DEVICE=$(DEVICE))

clean:
	rm -rf $(patsubst %-release,%,$(BUILD_DIR)) $(patsubst %-release,%,$(BUILD_DIR))-release
 
flash-jlink: $(FIRMWARE) | $(BUILD_DIR)/jlink-script
	JLinkExe -commanderScript $(BUILD_DIR)/jlink-script
 
flash-stlink: $(FIRMWARE)
	st-flash write $(FIRMWARE:.elf=.bin) 0x08000000
	st-flash reset

$(BUILD_DIR)/jlink-script: $(DEVICE_STAMP)
	touch $@
	@echo device $(DEVICE) > $@
	@echo si 1 >> $@
	@echo speed 4000 >> $@
	@echo loadfile $(FIRMWARE),0x08000000 >> $@
	@echo -e "r\ng\nqc" >> $@

monitor:
	JLinkSWOViewer -device $(DEVICE) -cpufreq 16000000 -itmport 0
