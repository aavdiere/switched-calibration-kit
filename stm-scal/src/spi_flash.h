#ifndef __SPI_FLASH_H
#define __SPI_FLASH_H

#include "common.h"

/* AT25EU0021A: 2 Mbit */
#define SPI_FLASH_SIZE (256 * 1024)
#define SPI_FLASH_PAGE_SIZE (256)
#define SPI_FLASH_SECTOR_SIZE (4096)

void spi_flash_setup(void);

/* JEDEC manufacturer ID followed by two device ID bytes */
void spi_flash_read_id(uint8_t id[3]);

void spi_flash_read(uint32_t address, uint8_t *buf, uint32_t len);

/* Target area must be erased, returns false on timeout */
bool spi_flash_write(uint32_t address, const uint8_t *buf, uint32_t len);

/* Erase the 4 KiB sector containing address, returns false on timeout */
bool spi_flash_erase_sector(uint32_t address);

#endif /* __SPI_FLASH_H */
