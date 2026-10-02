#include "spi_flash.h"

#include <libopencm3/stm32/gpio.h>
#include <libopencm3/stm32/rcc.h>
#include <libopencm3/stm32/spi.h>

#define FLASH_SPI (SPI1)

#define FLASH_PORT (GPIOA)
#define FLASH_HOLD (GPIO2)
#define FLASH_WP (GPIO3)
#define FLASH_CS (GPIO4)
#define FLASH_SCK (GPIO5)
#define FLASH_MISO (GPIO6)
#define FLASH_MOSI (GPIO7)

#define CMD_WRITE_ENABLE (0x06)
#define CMD_READ_STATUS (0x05)
#define CMD_READ (0x03)
#define CMD_PAGE_PROGRAM (0x02)
#define CMD_SECTOR_ERASE (0x20)
#define CMD_READ_ID (0x9f)

#define STATUS_BUSY (1 << 0)

/* Several seconds worth of status polls at 6 MHz */
#define BUSY_TIMEOUT (1000000)

static void cs_low(void) {
    gpio_clear(FLASH_PORT, FLASH_CS);
}

static void cs_high(void) {
    /* Let the last byte finish clocking out before releasing CS */
    while (SPI_SR(FLASH_SPI) & SPI_SR_BSY)
        ;
    gpio_set(FLASH_PORT, FLASH_CS);
}

static uint8_t xfer(uint8_t data) {
    spi_send8(FLASH_SPI, data);
    return spi_read8(FLASH_SPI);
}

static void send_cmd_addr(uint8_t cmd, uint32_t address) {
    xfer(cmd);
    xfer((uint8_t)(address >> 16));
    xfer((uint8_t)(address >> 8));
    xfer((uint8_t)address);
}

static void write_enable(void) {
    cs_low();
    xfer(CMD_WRITE_ENABLE);
    cs_high();
}

static bool wait_ready(void) {
    bool ready = false;

    cs_low();
    xfer(CMD_READ_STATUS);
    for (uint32_t i = 0; i < BUSY_TIMEOUT; i++) {
        if (!(xfer(0) & STATUS_BUSY)) {
            ready = true;
            break;
        }
    }
    cs_high();

    return ready;
}

void spi_flash_setup(void) {
    rcc_periph_clock_enable(RCC_GPIOA);
    rcc_periph_clock_enable(RCC_SPI1);

    /* Deassert HOLD and WP, software CS */
    gpio_set(FLASH_PORT, FLASH_HOLD | FLASH_WP | FLASH_CS);
    gpio_mode_setup(FLASH_PORT, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE, FLASH_HOLD | FLASH_WP | FLASH_CS);

    gpio_mode_setup(FLASH_PORT, GPIO_MODE_AF, GPIO_PUPD_NONE, FLASH_SCK | FLASH_MISO | FLASH_MOSI);
    gpio_set_output_options(FLASH_PORT, GPIO_OTYPE_PP, GPIO_OSPEED_HIGH, FLASH_SCK | FLASH_MOSI);
    gpio_set_af(FLASH_PORT, GPIO_AF0, FLASH_SCK | FLASH_MISO | FLASH_MOSI);

    /* Mode 0, 48 MHz / 8 = 6 MHz */
    spi_init_master(FLASH_SPI,
                    SPI_CR1_BAUDRATE_FPCLK_DIV_8,
                    SPI_CR1_CPOL_CLK_TO_0_WHEN_IDLE,
                    SPI_CR1_CPHA_CLK_TRANSITION_1,
                    SPI_CR1_MSBFIRST);
    spi_set_data_size(FLASH_SPI, SPI_CR2_DS_8BIT);
    spi_fifo_reception_threshold_8bit(FLASH_SPI);
    spi_enable_software_slave_management(FLASH_SPI);
    spi_set_nss_high(FLASH_SPI);
    spi_enable(FLASH_SPI);
}

void spi_flash_read_id(uint8_t id[3]) {
    cs_low();
    xfer(CMD_READ_ID);
    for (uint8_t i = 0; i < 3; i++) {
        id[i] = xfer(0);
    }
    cs_high();
}

void spi_flash_read(uint32_t address, uint8_t *buf, uint32_t len) {
    cs_low();
    send_cmd_addr(CMD_READ, address);
    for (uint32_t i = 0; i < len; i++) {
        buf[i] = xfer(0);
    }
    cs_high();
}

bool spi_flash_write(uint32_t address, const uint8_t *buf, uint32_t len) {
    while (len > 0) {
        /* A page program wraps around within the page, so split at boundaries */
        uint32_t chunk = SPI_FLASH_PAGE_SIZE - (address % SPI_FLASH_PAGE_SIZE);
        if (chunk > len) {
            chunk = len;
        }

        write_enable();
        cs_low();
        send_cmd_addr(CMD_PAGE_PROGRAM, address);
        for (uint32_t i = 0; i < chunk; i++) {
            xfer(buf[i]);
        }
        cs_high();

        if (!wait_ready()) {
            return false;
        }

        address += chunk;
        buf += chunk;
        len -= chunk;
    }

    return true;
}

bool spi_flash_erase_sector(uint32_t address) {
    write_enable();
    cs_low();
    send_cmd_addr(CMD_SECTOR_ERASE, address);
    cs_high();

    return wait_ready();
}
