#ifndef __USB_H
#define __USB_H

#include "common.h"

void usb_setup(void);
void usb_poll(void);

/* Last state selected by the host through vendor request 1 */
uint32_t usb_get_config(void);

#endif /* __USB_H */
