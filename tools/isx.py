"""Unpack an InstallShield "streamed" setup payload (the overlay of PCLEUSB2x32.exe).

    7z x PCLEUSB2x32.exe -oout        # the payload is out/[0]
    python3 isx.py 'out/[0]' extracted/
"""
import struct, sys, os
src, dst = sys.argv[1], sys.argv[2]
d = open(src,'rb').read()
n = struct.unpack_from('<H', d, 14)[0]
off = 0x2e
M = [0x13,0x35,0x86,0x07]
def dec(buf, key, start):
    out = bytearray(len(buf)); kl=len(key)
    for i,c in enumerate(buf):
        out[i] = (~(key[(i+start)%kl] ^ (((c<<4)|(c>>4))&0xff)))&0xff
    return out
os.makedirs(dst, exist_ok=True)
for _ in range(n):
    name = d[off:off+260].split(b'\0')[0]
    flags, unk, flen = struct.unpack_from('<III', d, off+260)
    hdr = 260+12+8+2+30
    data = d[off+hdr:off+hdr+flen]
    key = bytes(b ^ M[i%4] for i,b in enumerate(name))
    if flags & 6:
        out = bytearray()
        for i in range(0, len(data), 1024):
            out += dec(data[i:i+1024], key, 0)
    else:
        out = data
    open(os.path.join(dst, os.path.basename(name.decode('latin1'))),'wb').write(out)
    print(f'{flags:#x} {flen:9d} {name.decode("latin1")}')
    off += hdr+flen
