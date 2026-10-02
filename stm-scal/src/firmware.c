#include "common.h"
#include "spi_flash.h"
#include "usb.h"

#include <libopencm3/cm3/systick.h>
#include <libopencm3/stm32/crs.h>
#include <libopencm3/stm32/gpio.h>
#include <libopencm3/stm32/rcc.h>

#define LED_RCC (RCC_GPIOA)
#define LED_PORT (GPIOA)
#define LED_RED (GPIO9)
#define LED_GREEN (GPIO10)

#define SYSTICK_FREQ (1000)

volatile uint64_t ticks = 0;

void sys_tick_handler(void) {
    ticks++;
}

static uint64_t get_ticks(void) {
    return ticks;
}

static void rcc_setup(void) {
    /* Crystal-less: HSI48 for core and USB, trimmed to the USB SOF by the CRS */
    rcc_clock_setup_in_hsi48_out_48mhz();
    rcc_set_usbclk_source(RCC_HSI48);
    crs_autotrim_usb_enable();
}

static void gpio_setup(void) {
    rcc_periph_clock_enable(LED_RCC);
    gpio_mode_setup(LED_PORT, GPIO_MODE_OUTPUT, GPIO_PUPD_NONE, LED_RED | LED_GREEN);
}

static void systick_setup(void) {
    systick_set_frequency(SYSTICK_FREQ, rcc_ahb_frequency);
    systick_counter_enable();
    systick_interrupt_enable();
}

static bool flash_test(void) {
    uint8_t id[3];
    spi_flash_read_id(id);

    return id[0] == 0x1f;
}

int main(void) {
    rcc_setup();
    gpio_setup();

    systick_setup();

    spi_flash_setup();
    const uint16_t led = flash_test() ? LED_GREEN : LED_RED;

    usb_setup();

    uint64_t start_time = get_ticks();

    /* Infinte loop */
    for (;;) {
        usb_poll();

        if (get_ticks() - start_time >= 500) {
            gpio_toggle(LED_PORT, led);
            start_time = get_ticks();
        }
    }

    // Never return
    return 0;
}
