#include "usb.h"
#include "eeprom.h"

#include <libopencm3/stm32/gpio.h>
#include <libopencm3/stm32/rcc.h>
#include <libopencm3/usb/dwc/otg_fs.h>
#include <libopencm3/usb/usbd.h>

/* libopencm3 internals, needed for the setup workaround in usb_poll() */
#include "usb_private.h"

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

/* Force the B-session valid signal so the device connects whether or not
 * VBUS is wired to PA9 */
#define USB_VBUS_OVERRIDE (1)
#define OTG_GOTGCTL_BVALOEN (1 << 6)
#define OTG_GOTGCTL_BVALOVAL (1 << 7)
/* Setup packet received, only on newer OTG cores */
#define OTG_DOEPINTX_STPKTRX (1 << 15)

static const struct usb_device_descriptor device_desc = {
    .bLength = USB_DT_DEVICE_SIZE,
    .bDescriptorType = USB_DT_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = 0,
    .bDeviceSubClass = 0,
    .bDeviceProtocol = 0,
    .bMaxPacketSize0 = 64,
    .idVendor = USB_VID,
    .idProduct = USB_PID,
    .bcdDevice = 0x0000,
    .iManufacturer = 1,
    .iProduct = 2,
    .iSerialNumber = 3,
    .bNumConfigurations = 1,
};

static const struct usb_endpoint_descriptor endpoints[] = {
    {
        .bLength = USB_DT_ENDPOINT_SIZE,
        .bDescriptorType = USB_DT_ENDPOINT,
        .bEndpointAddress = EP_BULK_IN,
        .bmAttributes = USB_ENDPOINT_ATTR_BULK,
        .wMaxPacketSize = EP_BULK_SIZE,
        .bInterval = 0,
    },
    {
        .bLength = USB_DT_ENDPOINT_SIZE,
        .bDescriptorType = USB_DT_ENDPOINT,
        .bEndpointAddress = EP_BULK_OUT,
        .bmAttributes = USB_ENDPOINT_ATTR_BULK,
        .wMaxPacketSize = EP_BULK_SIZE,
        .bInterval = 0,
    },
};

static const struct usb_interface_descriptor iface = {
    .bLength = USB_DT_INTERFACE_SIZE,
    .bDescriptorType = USB_DT_INTERFACE,
    .bInterfaceNumber = 0,
    .bAlternateSetting = 0,
    .bNumEndpoints = 2,
    .bInterfaceClass = 0,
    .bInterfaceSubClass = 0,
    .bInterfaceProtocol = 0,
    .iInterface = 0,
    .endpoint = endpoints,
};

static const struct usb_interface interfaces[] = {
    {
        .num_altsetting = 1,
        .altsetting = &iface,
    },
};

static const struct usb_config_descriptor config_desc = {
    .bLength = USB_DT_CONFIGURATION_SIZE,
    .bDescriptorType = USB_DT_CONFIGURATION,
    .wTotalLength = 0,
    .bNumInterfaces = 1,
    .bConfigurationValue = 1,
    .iConfiguration = 0,
    .bmAttributes = USB_CONFIG_ATTR_DEFAULT | USB_CONFIG_ATTR_SELF_POWERED,
    .bMaxPower = 250, /* 500 mA */
    .interface = interfaces,
};

static const char *usb_strings[] = {
    "Achim Technologies, Uninc.",
    "SCal Module",
    "S/N AV42069",
};

static usbd_device *usbd_dev;
static uint8_t usbd_control_buffer[128];

/* Read state, set by the vendor requests and consumed by the bulk IN endpoint */
static uint32_t read_address = 0;
static uint16_t read_remaining = 0;
static uint32_t config = 0;
/* Length of the packet sitting in the EP1 IN FIFO, 0 if none */
static uint16_t in_pending = 0;

/* Word aligned, the OTG FIFO is written 32 bits at a time */
static uint32_t in_packet[EP_BULK_SIZE / sizeof(uint32_t)];

uint32_t usb_get_config(void) {
    return config;
}

/* Wait for an OTG interrupt flag, giving up after a while so a missing
 * flag cannot hang the device */
static bool wait_flag(volatile uint32_t *reg, uint32_t flag) {
    for (uint32_t i = 0; i < 100000; i++) {
        if (*reg & flag) {
            return true;
        }
    }
    return false;
}

/* Drop a packet that is still waiting in the EP1 IN FIFO, so a new
 * address/length from the host is not answered with stale data */
static void bulk_in_abort(void) {
    if (!(OTG_FS_DIEPCTL(1) & OTG_DIEPCTL0_EPENA)) {
        return;
    }

    OTG_FS_DIEPCTL(1) |= OTG_DIEPCTL0_SNAK;
    wait_flag(&OTG_FS_DIEPINT(1), OTG_DIEPINTX_INEPNE);

    /* The packet may have gone out while waiting for the NAK */
    if (OTG_FS_DIEPCTL(1) & OTG_DIEPCTL0_EPENA) {
        OTG_FS_DIEPCTL(1) |= OTG_DIEPCTL0_EPDIS;
        wait_flag(&OTG_FS_DIEPINT(1), OTG_DIEPINTX_EPDISD);

        /* Flush TX FIFO 1 */
        OTG_FS_GRSTCTL = OTG_GRSTCTL_TXFFLSH | (1 << 6);
        while (OTG_FS_GRSTCTL & OTG_GRSTCTL_TXFFLSH)
            ;
        OTG_FS_DIEPTSIZ(1) = 0;

        /* Undo the dropped packet, the host never saw it */
        read_address -= in_pending;
        read_remaining += in_pending;
        in_pending = 0;
    }
    OTG_FS_DIEPINT(1) = OTG_DIEPINTX_EPDISD | OTG_DIEPINTX_INEPNE;
}

/* Queue the next packet of the current read, if any is left */
static void bulk_in_send(void) {
    if (read_remaining == 0) {
        return;
    }

    uint16_t len = read_remaining < EP_BULK_SIZE ? read_remaining : EP_BULK_SIZE;
    eeprom_read(read_address, (uint8_t *)in_packet, len);

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

static enum usbd_request_return_codes vendor_request(usbd_device *dev,
                                                     struct usb_setup_data *req,
                                                     uint8_t **buf,
                                                     uint16_t *len,
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
        *complete = vendor_request_complete;
        return USBD_REQ_HANDLED;

    case VENDOR_REQ_SET_ADDRESS:
        bulk_in_abort();
        read_address = ((uint32_t)req->wValue << 16) | req->wIndex;
        *complete = vendor_request_complete;
        return USBD_REQ_HANDLED;

    default:
        return USBD_REQ_NOTSUPP;
    }
}

static void set_config_cb(usbd_device *dev, uint16_t wValue) {
    (void)wValue;

    read_address = 0;
    read_remaining = 0;
    in_pending = 0;

    usbd_ep_setup(dev, EP_BULK_IN, USB_ENDPOINT_ATTR_BULK, EP_BULK_SIZE, bulk_in_cb);
    usbd_ep_setup(dev, EP_BULK_OUT, USB_ENDPOINT_ATTR_BULK, EP_BULK_SIZE, bulk_out_cb);

    usbd_register_control_callback(dev,
                                   USB_REQ_TYPE_VENDOR,
                                   USB_REQ_TYPE_TYPE,
                                   vendor_request);
}

/* libopencm3 starts handling a control request when the "setup done" status
 * word pops out of the RX FIFO. The OTG core of the F412/F413 (core ID 0x2000,
 * Synopsys 3.20a) only pushes that word some of the time, but always raises
 * STUP in DOEPINT0. Dispatch from STUP in usb_poll() instead and ignore the
 * status word, otherwise a request is either never handled or handled twice. */
static bool stup_workaround = false;

static void setup_done_ignore(usbd_device *dev, uint8_t ep) {
    (void)dev;
    (void)ep;
}

void usb_setup(void) {
    /* OTG FS on PA11 (DM) and PA12 (DP) */
    rcc_periph_clock_enable(RCC_GPIOA);
    gpio_mode_setup(GPIOA, GPIO_MODE_AF, GPIO_PUPD_NONE, GPIO11 | GPIO12);
    gpio_set_output_options(GPIOA, GPIO_OTYPE_PP, GPIO_OSPEED_100MHZ, GPIO11 | GPIO12);
    gpio_set_af(GPIOA, GPIO_AF10, GPIO11 | GPIO12);

    usbd_dev = usbd_init(&otgfs_usb_driver,
                         &device_desc,
                         &config_desc,
                         usb_strings,
                         sizeof(usb_strings) / sizeof(usb_strings[0]),
                         usbd_control_buffer,
                         sizeof(usbd_control_buffer));

#if USB_VBUS_OVERRIDE
    OTG_FS_GCCFG &= ~OTG_GCCFG_VBDEN;
    OTG_FS_GOTGCTL |= OTG_GOTGCTL_BVALOEN | OTG_GOTGCTL_BVALOVAL;
#endif

    if (OTG_FS_CID >= OTG_CID_HAS_VBDEN) {
        stup_workaround = true;
        usbd_dev->user_callback_ctr[0][USB_TRANSACTION_SETUP] = setup_done_ignore;
    }

    usbd_register_set_config_callback(usbd_dev, set_config_cb);
}

void usb_poll(void) {
    usbd_poll(usbd_dev);

    /* See setup_done_ignore(): once the setup data has been read out of the
     * FIFO, STUP marks the end of the setup stage on this core */
    if (stup_workaround && (OTG_FS_DOEPINT(0) & OTG_DOEPINTX_STUP) &&
        !(OTG_FS_GINTSTS & OTG_GINTSTS_RXFLVL)) {
        OTG_FS_DOEPINT(0) = OTG_DOEPINTX_STUP | OTG_DOEPINTX_STPKTRX;

        _usbd_control_setup(usbd_dev, 0);

        /* Re-arm EP0 OUT unless libopencm3 already did for a "setup done" word */
        if (!(OTG_FS_DOEPCTL(0) & OTG_DOEPCTL0_EPENA)) {
            OTG_FS_DOEPTSIZ(0) = usbd_dev->doeptsiz[0];
            OTG_FS_DOEPCTL(0) |= OTG_DOEPCTL0_EPENA |
                                 (usbd_dev->force_nak[0] ? OTG_DOEPCTL0_SNAK : OTG_DOEPCTL0_CNAK);
        }
    }
}
