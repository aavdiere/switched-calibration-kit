/*
 * This file is part of the libopencm3 project.
 *
 * Copyright (C) 2009 Uwe Hermann <uwe@hermann-uwe.de>
 * Copyright (C) 2011 Stephen Caudle <scaudle@doceme.com>
 *
 * This library is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this library.  If not, see <http://www.gnu.org/licenses/>.
 */

/* Linker script for STM32F413ZH, 1.5M flash, 320K RAM. */

/* Define memory regions. */
MEMORY
{
	rom 	 (rx)  : ORIGIN = 0x08000000, LENGTH = 1536K
	ram 	 (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
	ram2	 (rwx) : ORIGIN = 0x10000000, LENGTH = 64K
}

INCLUDE cortex-m-generic.ld

SECTIONS
{
  .sram2 (NOLOAD) :
  {
    . = ALIGN(4);
    *(.sram2*)
  } > ram2
}
