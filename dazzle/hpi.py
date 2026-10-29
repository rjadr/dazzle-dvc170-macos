"""Userspace port of the Linux go7007-usb EZ-USB HPI transport for the Pinnacle Dazzle DVC 170."""
import os, struct, time
import usb.core, usb.util, usb.backend.libusb1

VID, PID = 0x2304, 0x021E
HPI_STATUS_ADDR, INT_PARAM_ADDR, INT_INDEX_ADDR = 0xFFF4, 0xFFF6, 0xFFF8
VIN, VOUT = 0xC0, 0x40
EP_FW, EP_INT, EP_VIDEO, EP_AUDIO = 0x02, 0x84, 0x86, 0x88
FW_DIR = os.path.dirname(os.path.abspath(__file__))

I2C_BASE = 0x1400
I2C_STATUS, I2C_CTRL, I2C_DEV_UP, I2C_LO, I2C_DATA = (I2C_BASE + o for o in (0x2, 0x6, 0x7, 0x8, 0x9))


def _backend():
    for p in ('/opt/homebrew/lib/libusb-1.0.dylib', '/usr/local/lib/libusb-1.0.dylib'):
        if os.path.exists(p):
            return usb.backend.libusb1.get_backend(find_library=lambda _: p)
    return None


class HPIError(Exception):
    pass


class Go7007:
    def __init__(self):
        self.dev = usb.core.find(idVendor=VID, idProduct=PID, backend=_backend())
        if self.dev is None:
            raise HPIError('Dazzle DVC 170 not found on USB')
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, 0)

    def close(self):
        usb.util.dispose_resources(self.dev)

    # --- HPI primitives (go7007-usb.c) ---
    def hpi_status(self):
        return struct.unpack('<H', bytes(self.dev.ctrl_transfer(VIN, 0x14, 0, HPI_STATUS_ADDR, 2, timeout=500)))[0]

    def write_interrupt(self, addr, data):
        for _ in range(100):
            st = self.hpi_status()
            if not st & 0x0010:
                break
            time.sleep(0.01)
        else:
            raise HPIError('device is hung, status reg = %#06x' % st)
        self.dev.ctrl_transfer(VOUT, 0x12, data, INT_PARAM_ADDR, None, timeout=500)
        self.dev.ctrl_transfer(VOUT, 0x12, addr, INT_INDEX_ADDR, None, timeout=500)

    def read_interrupt(self, timeout=5000):
        data, value = struct.unpack('<HH', bytes(self.dev.read(EP_INT, 4, timeout=timeout)))
        return value & 0xFFFE, data

    def write_addr(self, addr, data):
        self.write_interrupt(addr | 0x8000, data)

    def read_addr(self, addr):
        self.write_interrupt(0x0010, addr)
        for _ in range(100):
            value, data = self.read_interrupt()
            if value == 0xA000:
                return data
        raise HPIError('read_addr %#06x failed' % addr)

    def send_firmware(self, data):
        self.dev.write(EP_FW, data, timeout=2000)

    # --- boot (go7007-driver.c) ---
    def interface_reset(self):
        self.write_interrupt(0x0001, 0x0001)
        time.sleep(0.1)
        self.dev.ctrl_transfer(VOUT, 0x10, 0, 0, None)
        self.dev.ctrl_transfer(VOUT, 0x10, 0, 0, None)
        self.write_interrupt(0x0001, 0x0001)
        time.sleep(0.1)
        value, _ = self.read_interrupt()
        if value != 0x55AA:
            raise HPIError('unable to reset the USB interface (%#06x)' % value)

    def boot_encoder(self):
        path = os.path.join(FW_DIR, 'go7007fw.bin')
        if not os.path.exists(path):
            raise HPIError(f'{path} is missing: extract it from Pinnacle\'s PCLEUSB2x32.exe (see README, "Setup")')
        fw = open(path, 'rb').read()
        if not fw.startswith(b'WISGO7007FW'):
            raise HPIError('bad go7007fw.bin')
        self.interface_reset()
        self.send_firmware(fw[16:])
        value, _ = self.read_interrupt()
        if value != 0x5A5A:
            raise HPIError('error transferring firmware (%#06x)' % value)

    # --- on-board I2C (go7007-i2c.c) ---
    def _i2c_wait(self, mask, want_clear):
        for _ in range(10):
            v = self.read_addr(I2C_STATUS)
            if (not v & mask) if want_clear else (v & mask):
                return
            time.sleep(0.1)
        raise HPIError('I2C adapter is hung')

    def i2c_write(self, addr, reg, val, flags=0):
        self._i2c_wait(0x7, True)
        self.write_addr(I2C_CTRL, flags)
        self.write_addr(I2C_LO, reg)
        self.write_addr(I2C_DATA, val)
        self.write_addr(I2C_DEV_UP, (addr << 9) | (reg >> 8))

    def i2c_read(self, addr, reg, flags=0):
        self._i2c_wait(0x7, True)
        self.write_addr(I2C_CTRL, flags)
        self.write_addr(I2C_LO, reg)
        self.read_addr(I2C_DATA)
        self.write_addr(I2C_DEV_UP, (addr << 9) | 0x0100 | (reg >> 8))
        self._i2c_wait(0x8, False)
        return self.read_addr(I2C_DATA) & 0xFF
