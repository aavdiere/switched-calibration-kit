#include "usb.h"
#include "eeprom.h"

#include <libopencm3/stm32/st_usbfs.h>
#include <libopencm3/usb/usbd.h>

/* Keysight ECal module IDs, see cynthion/emulate/scal.py */
#define USB_VID (0x2a8d)
#define USB_PID (0x3f01)

#define EP_BULK_IN (0x81)
#define EP_BULK_OUT (0x01)
#define EP_BULK_SIZE (64)

/* Vendor requests used by the VNA */
#define VENDOR_REQ_SET_CONFIG (1)
#define VENDOR_REQ_SET_LENGTH (2)
#define VENDOR_REQ_SET_ADDRESS (4)

static const struct usb_device_descriptor device_desc = {
    .bLength            = USB_DT_DEVICE_SIZE,
    .bDescriptorType    = USB_DT_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = 0,
    .bDeviceSubClass    = 0,
    .bDeviceProtocol    = 0,
    .bMaxPacketSize0    = 64,
    .idVendor           = USB_VID,
    .idProduct          = USB_PID,
    .bcdDevice          = 0x0000,
    .iManufacturer      = 1,
    .iProduct           = 2,
    .iSerialNumber      = 3,
    .bNumConfigurations = 1,
};

static const struct usb_endpoint_descriptor endpoints[] = {
    {
        .bLength          = USB_DT_ENDPOINT_SIZE,
        .bDescriptorType  = USB_DT_ENDPOINT,
        .bEndpointAddress = EP_BULK_IN,
        .bmAttributes     = USB_ENDPOINT_ATTR_BULK,
        .wMaxPacketSize   = EP_BULK_SIZE,
        .bInterval        = 0,
    },
    {
        .bLength          = USB_DT_ENDPOINT_SIZE,
        .bDescriptorType  = USB_DT_ENDPOINT,
        .bEndpointAddress = EP_BULK_OUT,
        .bmAttributes     = USB_ENDPOINT_ATTR_BULK,
        .wMaxPacketSize   = EP_BULK_SIZE,
        .bInterval        = 0,
    },
};

static const struct usb_interface_descriptor iface = {
    .bLength            = USB_DT_INTERFACE_SIZE,
    .bDescriptorType    = USB_DT_INTERFACE,
    .bInterfaceNumber   = 0,
    .bAlternateSetting  = 0,
    .bNumEndpoints      = 2,
    .bInterfaceClass    = 0,
    .bInterfaceSubClass = 0,
    .bInterfaceProtocol = 0,
    .iInterface         = 0,
    .endpoint           = endpoints,
};

static const struct usb_interface interfaces[] = {
    {
        .num_altsetting = 1,
        .altsetting     = &iface,
    },
};

static const struct usb_config_descriptor config_desc = {
    .bLength             = USB_DT_CONFIGURATION_SIZE,
    .bDescriptorType     = USB_DT_CONFIGURATION,
    .wTotalLength        = 0,
    .bNumInterfaces      = 1,
    .bConfigurationValue = 1,
    .iConfiguration      = 0,
    .bmAttributes        = USB_CONFIG_ATTR_DEFAULT | USB_CONFIG_ATTR_SELF_POWERED,
    .bMaxPower           = 250, /* 500 mA */
    .interface           = interfaces,
};

static const char *usb_strings[] = {
    "Achim Technologies, Uninc.",
    "SCal Module",
    "S/N AV42069",
};

static usbd_device *usbd_dev;
static uint8_t      usbd_control_buffer[128];

/* Read state, set by the vendor requests and consumed by the bulk IN endpoint */
static uint32_t read_address   = 0;
static uint16_t read_remaining = 0;
static uint32_t config         = 0;
/* Length of the packet sitting in the EP1 IN buffer, 0 if none */
static uint16_t in_pending = 0;

static uint8_t in_packet[EP_BULK_SIZE];

uint32_t usb_get_config(void) {
    return config;
}

/* Drop a packet that is still waiting in the EP1 IN buffer, so a new
 * address/length from the host is not answered with stale data */
static void bulk_in_abort(void) {
    const uint8_t ep = EP_BULK_IN & 0x7f;

    if ((*USB_EP_REG(ep) & USB_EP_TX_STAT) == USB_EP_TX_STAT_VALID) {
        USB_SET_EP_TX_STAT(ep, USB_EP_TX_STAT_NAK);
    }

    if (*USB_EP_REG(ep) & USB_EP_TX_CTR) {
        /* The packet went out, swallow its completion so it does not trigger
         * another send. NAK again in case the toggle raced the hardware. */
        USB_CLR_EP_TX_CTR(ep);
        USB_SET_EP_TX_STAT(ep, USB_EP_TX_STAT_NAK);
    } else {
        /* Undo the dropped packet, the host never saw it */
        read_address -= in_pending;
        read_remaining += in_pending;
    }
    in_pending = 0;
}

/* Queue the next packet of the current read, if any is left */
static void bulk_in_send(void) {
    if (read_remaining == 0) {
        return;
    }

    uint16_t len = read_remaining < EP_BULK_SIZE ? read_remaining : EP_BULK_SIZE;
    eeprom_read(read_address, in_packet, len);

    if (usbd_ep_write_packet(usbd_dev, EP_BULK_IN, in_packet, len) == len) {
        read_address += len;
        read_remaining -= len;
        in_pending = len;
    }
}

static void bulk_in_cb(usbd_device *dev, uint8_t ep) {
    (void)dev;
    (void)ep;

    in_pending = 0;
    bulk_in_send();
}

static void bulk_out_cb(usbd_device *dev, uint8_t ep) {
    uint8_t buf[EP_BULK_SIZE];

    /* Not used by the VNA, discard */
    usbd_ep_read_packet(dev, ep, buf, sizeof(buf));
}

/* Start sending once the status stage of the vendor request is done */
static void vendor_request_complete(usbd_device *dev, struct usb_setup_data *req) {
    (void)dev;
    (void)req;

    bulk_in_send();
}

static enum usbd_request_return_codes vendor_request(usbd_device                    *dev,
                                                     struct usb_setup_data          *req,
                                                     uint8_t                       **buf,
                                                     uint16_t                       *len,
                                                     usbd_control_complete_callback *complete) {
    (void)dev;

    if (req->bmRequestType & USB_REQ_TYPE_IN) {
        return USBD_REQ_NOTSUPP;
    }

    switch (req->bRequest) {
        case VENDOR_REQ_SET_CONFIG:
            /* The state comes either in the data stage (little endian) or in wValue */
            if (*len > 0) {
                config = 0;
                for (uint16_t i = 0; i < *len && i < sizeof(config); i++) {
                    config |= (uint32_t)(*buf)[i] << (8 * i);
                }
            } else {
                config = req->wValue;
            }
            /* TODO: drive the switches */
            return USBD_REQ_HANDLED;

        case VENDOR_REQ_SET_LENGTH:
            bulk_in_abort();
            read_remaining = req->wValue;
            *complete      = vendor_request_complete;
            return USBD_REQ_HANDLED;

        case VENDOR_REQ_SET_ADDRESS:
            bulk_in_abort();
            read_address = ((uint32_t)req->wValue << 16) | req->wIndex;
            *complete    = vendor_request_complete;
            return USBD_REQ_HANDLED;

        default:
            return USBD_REQ_NOTSUPP;
    }
}

static void set_config_cb(usbd_device *dev, uint16_t wValue) {
    (void)wValue;

    read_address   = 0;
    read_remaining = 0;
    in_pending     = 0;

    usbd_ep_setup(dev, EP_BULK_IN, USB_ENDPOINT_ATTR_BULK, EP_BULK_SIZE, bulk_in_cb);
    usbd_ep_setup(dev, EP_BULK_OUT, USB_ENDPOINT_ATTR_BULK, EP_BULK_SIZE, bulk_out_cb);

    usbd_register_control_callback(dev, USB_REQ_TYPE_VENDOR, USB_REQ_TYPE_TYPE, vendor_request);
}

void usb_setup(void) {
    /* USB FS on PA11 (DM) and PA12 (DP), connected as soon as the peripheral
     * is enabled, no AF setup needed. Internal DP pull-up. */
    usbd_dev = usbd_init(&st_usbfs_v2_usb_driver,
                         &device_desc,
                         &config_desc,
                         usb_strings,
                         sizeof(usb_strings) / sizeof(usb_strings[0]),
                         usbd_control_buffer,
                         sizeof(usbd_control_buffer));

    usbd_register_set_config_callback(usbd_dev, set_config_cb);
}

void usb_poll(void) {
    usbd_poll(usbd_dev);
}
