#ifndef __EEPROM_H
#define __EEPROM_H

#include "common.h"

/* Size of the emulated EEPROM, reads past the end return 0xff */
#define EEPROM_SIZE (0x10000)

/* Read len bytes starting at address into buf */
void eeprom_read(uint32_t address, uint8_t *buf, uint16_t len);

#endif /* __EEPROM_H */
