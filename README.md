# Dazzle DVC 170 on macOS

Userspace driver for the Pinnacle Dazzle Video Creator Platinum (DVC 170, USB `2304:021e`) using libusb.
No kernel extension and no Windows needed. Captures PAL/NTSC video as hardware-encoded MPEG-2, plus 48 kHz stereo audio.

Tested on an Apple M2 MacBook Air with a PAL VCR over composite + L/R audio (SCART adapter switched to OUT).

## Setup

```sh
brew install libusb ffmpeg p7zip
pip install pyusb
make -C native          # builds dazzle/libdazzle.dylib
```

The encoder boot firmware is Pinnacle's and isn't included. Extract it from their driver installer once:

```sh
curl -LO http://cdn.pinnaclesys.com/SupportFiles/Hardware_Installer/PCLEUSB2x32.exe
7z x PCLEUSB2x32.exe -o/tmp/dz/out
python3 tools/isx.py '/tmp/dz/out/[0]' /tmp/dz/is
7z x '/tmp/dz/is/Pinnacle Systems USB-2 Device Drivers.msi' -o/tmp/dz/msi
7z x '/tmp/dz/msi/*.cab' -o/tmp/dz/cab
7z e /tmp/dz/cab/dvc_130_170.cab go7007fw.bin -odazzle
```

## Capture

```sh
python3 -m dazzle.capture tape1.mpg                     # PAL, composite, MPEG-2 8 Mbit/s, until Ctrl-C
python3 -m dazzle.capture tape1.mpg --duration 3600 --bitrate 9800000
python3 -m dazzle.capture tape1.mpg --ntsc
```

Output: `tape1.mpg` (MPEG-2 elementary stream), `tape1.mpg.wav` (PCM), and `tape1.mkv` with both muxed (FLAC audio).
QuickTime can't play MKV or MPEG-2; use IINA/VLC, or convert:
`ffmpeg -i tape1.mkv -vf yadif -c:v libx264 -crf 18 -c:a aac -b:a 192k tape1.mp4`.

The first line printed says whether the decoder has locked onto a video signal. If it says `NO SIGNAL`, check that the VCR is playing and the SCART adapter is set to OUT.

A live preview window (ffplay) opens while recording, so you can see when the tape ends; close it any time, the recording continues. `--no-preview` turns it off.

Options: `--input composite|svideo`, `--insel 0xNN` (raw ADV7180 input/standard byte), `--format mpeg2|mpeg1|mpeg4|mjpeg`, `--gop`, `--no-audio`.

## Status

| | |
|---|---|
| Composite video, PAL | works: 25 fps, full colour, no dropped frames |
| Audio | works: 48 kHz 16-bit stereo |
| NTSC | untested (`--ntsc` forces NTSC-M) |
| S-Video | untested (`0x06` = ADV7180 Y/C on AIN1/AIN2 is a guess; composite turned out to be on AIN5) |
| MPEG-1 / MPEG-4 / MJPEG | untested; built by the Linux code, so should work |
| A/V sync over long tapes | unverified: audio and video are recorded as separate streams and muxed afterwards |

## How it works

| File | |
|---|---|
| `dazzle/hpi.py` | USB transport, encoder boot, I2C via the GO7007 (port of Linux `go7007-usb.c`, `go7007-driver.c`, `go7007-i2c.c`) |
| `native/go7007-fw.c` | Linux encoder-config generator, unmodified (GPL-2.0), built against a small kernel shim (`native/include/`, `native/go7007-priv.h`) |
| `native/dazzle_native.c` | C entry point for the firmware builder, plus the video pipe parser (strips GO7007 timestamp/VBI chunks) |
| `dazzle/native.py` | ctypes bindings |
| `dazzle/capture.py` | capture CLI: decoder, codec and encoder setup, USB reader threads, muxing |
| `tools/isx.py` | unpacker for the InstallShield installer the Windows driver came in |

Startup sequence:
1. Reset the GO7007 over the FX2 HPI bridge; it answers `0x55aa`.
2. Upload `go7007fw.bin` (minus its 16-byte header) to EP 0x02; it answers `0x5a5a`.
3. Over the GO7007's I2C: set up the ADV7180 (input, forced standard), then the audio codec.
4. Enable the I2S master clock (`0x1000` ← `0x0811`, `0x0c11`).
5. Build the encoder setup package from `go7007tv.bin` for the chosen format/bitrate, upload it, and stream.

## Hardware notes (what we found)

Board: Cypress CY7C68013A (FX2), WIS/Micronas GO7007SB, Hynix HY57V643220DTP-6 SDRAM, ADV7180 decoder, a 24-pin audio codec between the red/white jacks, and an 8-pin EEPROM.

USB: one vendor-specific interface. EP 0x02 bulk OUT (firmware/config), 0x84 bulk IN (interrupt words), 0x86 bulk IN (video), 0x88 bulk IN (audio). Same layout as the Linux go7007 "EZ-USB" boards (Plextor/Matrix), so the Linux protocol applies as-is.

FX2 vendor requests:
- `0x10`: reset the FX2 buffers.
- `0x12`/`0x14`: HPI register write/read (`0xfff4` status, `0xfff6` param, `0xfff8` index).
- `0x24`/`0x25`: FX2 I2C. Nothing is on that bus.
- `0x41`: GPIO read, returns `[value, direction]`.
- `0x40`: GPIO write, `wValue = direction << 8 | value`.

FX2 GPIO (power-on value `0x7f`, direction `0xe0`):
- pin 5: GO7007 reset. Must stay high, or the encoder hangs.
- pin 6: audio clock. Must stay high, or no audio data arrives.
- pin 7: no visible effect.
- Leave all of these alone.

I2C (on the GO7007's bus, register window `0x1400`; only usable after the encoder firmware has booted):
- `0x21` — **ADV7180** video decoder (IDENT reg 0x11 = `0x1b`).
  - **Composite is on AIN5** (INSEL `0x04`), not AIN1.
  - **The standard must be forced** (reg 0x00 high nibble `0x8` = PAL-B/G/H/I/D, `0x5` = NTSC-M). Autodetect misreads VHS as "PAL-Combination N": no colour, tearing, dropped frames.
  - Reg 0x04 = `0xc5` (BT.656-4), reg 0xE6 = `0x4f`, as in Linux `adv7180.c`.
- `0x1a` — **audio codec**, WM8731/TLV320AIC23-style: 7-bit register + 9-bit value, **write-only**. It doesn't answer reads, so read-based I2C scans never find it.
  - It powers up with its digital interface inactive and outputs exact zeros until it's set up.
  - Our init (`CODEC_INIT` in `capture.py`): reset, line-in 0 dB, line → ADC, power up line/ADC, I2S 16-bit **slave**, 48 kHz, activate.

GO7007 audio: I2S master (`AUDIO_I2S_MASTER`), mode 1, 16-bit, `bclk_div=4`, `main_div=1` gives 48 kHz stereo. The Linux default of 8/2 gives half the rate. Slave mode gives no data.

The GO7007's SPI master (`0x1400`–`0x1405`) and GPIO (`0x3c80`/`0x3c82`) exist, but the Windows driver only touches them on request from user programs, and this board doesn't need them.

## Firmware

| File | Source | Notes |
|---|---|---|
| `dazzle/go7007fw.bin` | Pinnacle driver package [`PCLEUSB2x32.exe`](http://cdn.pinnaclesys.com/SupportFiles/Hardware_Installer/PCLEUSB2x32.exe) (driver 2.5.8.2, `dvc_130_170.cab`) | encoder boot firmware, 30,800 bytes, `WISGO7007FW` header. Pinnacle's copyright, so don't redistribute. linux-firmware ships a different build of this file (about half the bytes differ); only the Pinnacle one has been tested here. |
| `dazzle/go7007tv.bin` | [linux-firmware](https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/tree/go7007) | encoder setup templates in the chunk format `go7007-fw.c` expects. Redistributable (`LICENCE.go7007`). The Windows `go7007sb.bin` holds similar data in a different container format that the Linux code can't read. |

See **Setup** for how to extract `go7007fw.bin`. `tools/isx.py` undoes the InstallShield obfuscation; the rest of the installer is plain MSI/CAB.

## Background / references

- The Windows driver (`WisGoStrm.sys`, WIS SDK 2.5, from [PCLEUSB2x32.exe](http://cdn.pinnaclesys.com/SupportFiles/Hardware_Installer/PCLEUSB2x32.exe), listed on [Pinnacle's hardware driver page](https://cdn.pinnaclesys.com/SupportFiles/Hardware_Installer/readmeHW10.htm)) and Pinnacle's capture module (`pclecapturewischip.dll`, from the [Pinnacle Instant DVD Recorder CD on archive.org](https://archive.org/details/img-0319_202602)) were decompiled with [Ghidra](https://ghidra-sre.org/). Neither contains a DVC 170-specific audio step that we could find. The codec setup above was found by testing the hardware directly.
- [Linux go7007 driver](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/media/usb/go7007), [Linux adv7180 driver](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/media/i2c/adv7180.c)
- [LinuxTV wiki: DVC170](https://www.linuxtv.org/wiki/index.php/Pinnacle_Dazzle_Video_Creator_(DVC170)): chip list and USB IDs; support status "??" (2011).
- [videohelp thread with a DVC 130 board photo](https://forum.videohelp.com/threads/402642-capturing-video-using-dazzle-dvc-130). The DVC 130 and 170 share the board design.

## License

GPL-2.0 (see `LICENSE`), because `native/go7007-fw.c` and the code ported from the Linux go7007 driver are GPL-2.0.
`dazzle/go7007tv.bin` is from linux-firmware and is redistributable under `dazzle/LICENCE.go7007`.
`go7007fw.bin` is Pinnacle's and is not part of this repository.

Not affiliated with Pinnacle, Corel or Micronas.
