#include "eeprom.h"

/* Placeholder until the real EEPROM interface is implemented: each byte
 * holds the low byte of its own address, which makes misaligned reads easy
 * to spot on the host side. */
void eeprom_read(uint32_t address, uint8_t *buf, uint16_t len) {
    for (uint16_t i = 0; i < len; i++, address++) {
        buf[i] = (address < EEPROM_SIZE) ? (uint8_t)address : 0xff;
    }
}
