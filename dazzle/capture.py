"""Capture video (and audio) from a Pinnacle Dazzle DVC 170 on macOS.

    python -m dazzle.capture tape1.mpg --duration 60
"""
import argparse, os, queue, shutil, signal, subprocess, sys, threading, time, wave
import usb.core

from . import native
from .hpi import Go7007, HPIError, EP_VIDEO, EP_AUDIO

ADV7180 = 0x21
INPUTS = {'composite': 0x04, 'svideo': 0x06}  # composite is on AIN5 on this board
FORMATS = {'mpeg2': native.FMT_MPEG2, 'mpeg1': native.FMT_MPEG1, 'mpeg4': native.FMT_MPEG4, 'mjpeg': native.FMT_MJPEG}


def adv7180_setup(go, insel):
    go.i2c_write(ADV7180, 0x00, insel)  # video standard (high nibble) + input (low nibble)
    go.i2c_write(ADV7180, 0x04, 0xC5)  # ITU-R BT.656-4 compatible output
    go.i2c_write(ADV7180, 0xE6, 0x4F)  # manual NTSC V bit end


AUDIO_CODEC = 0x1A  # write-only WM8731/TLV320AIC23-style codec (7-bit register, 9-bit value)
CODEC_INIT = (
    (15, 0x000),  # reset
    (0, 0x017), (1, 0x017),  # line in L/R: 0 dB, unmuted
    (4, 0x002),  # analog path: line in -> ADC, mic muted
    (5, 0x000),  # digital path: ADC high-pass on
    (6, 0x01A),  # power: line in, ADC, oscillator, clock out on
    (7, 0x002),  # I2S, 16 bit, slave (GO7007 drives the clocks)
    (8, 0x000),  # 48 kHz, normal mode
    (9, 0x001),  # activate digital interface
)


def codec_setup(go):
    for reg, val in CODEC_INIT:
        go.i2c_write(AUDIO_CODEC, (reg << 1) | (val >> 8), val & 0xFF)


def adv7180_status(go):
    s1 = go.i2c_read(ADV7180, 0x10)
    std = ['NTSC-M/J', 'NTSC-4.43', 'PAL-M', 'PAL-60', 'PAL-B/G/H/I/D', 'SECAM', 'PAL-Combination N', 'SECAM 525'][(s1 >> 4) & 7]
    return bool(s1 & 1), std


def reader(go, ep, size, q, stop):
    while not stop.is_set():
        try:
            q.put(bytes(go.dev.read(ep, size, timeout=5000)))
        except usb.core.USBTimeoutError:
            continue
        except usb.core.USBError as e:
            print(f'\nUSB error on {ep:#x}: {e}', file=sys.stderr)
            break
    q.put(None)


class FFplay:
    """Feeds a live stream to ffplay from a background thread. Never blocks or breaks the caller."""

    def __init__(self, input_args, title='Dazzle preview', video=True):
        opts = ['-vf', 'yadif', '-framedrop', '-window_title', title] if video else ['-nodisp']
        self.proc = subprocess.Popen(
            ['ffplay', '-hide_banner', '-loglevel', 'quiet', '-fflags', 'nobuffer', '-flags', 'low_delay',
             '-probesize', '65536', '-analyzeduration', '0', *opts, *input_args, '-i', '-'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.q = queue.Queue(maxsize=256)
        threading.Thread(target=self._pump, daemon=True).start()

    @classmethod
    def video(cls, fmt, pal, title='Dazzle preview'):
        demux = {'mjpeg': 'mjpeg', 'mpeg4': 'm4v'}.get(fmt, 'mpegvideo')
        return cls(['-f', demux, '-framerate', '25' if pal else '30000/1001'], title)

    @classmethod
    def audio(cls):
        return cls(['-f', 's16le', '-ar', '48000', '-ch_layout', 'stereo'], video=False)

    def _pump(self):
        while (data := self.q.get()) is not None:
            try:
                self.proc.stdin.write(data)
            except (BrokenPipeError, OSError):  # window closed: carry on without it
                return

    def feed(self, data):
        try:
            self.q.put_nowait(data)
        except queue.Full:  # player fell behind: drop data rather than stall the capture
            pass

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        self.q.put(None)
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.terminate()


def add_device_args(ap):
    ap.add_argument('--format', choices=FORMATS, default='mpeg2')
    ap.add_argument('--bitrate', type=int, default=8_000_000, help='bits/s for MPEG formats (default 8 Mbit/s)')
    ap.add_argument('--gop', type=int, default=15)
    ap.add_argument('--input', choices=INPUTS, default='composite')
    ap.add_argument('--insel', type=lambda v: int(v, 0), help='raw ADV7180 input select value (overrides --input)')
    ap.add_argument('--ntsc', action='store_true', help='NTSC instead of PAL')
    ap.add_argument('--no-audio', action='store_true')
    ap.add_argument('--no-audio-master', dest='audio_master', action='store_false',
                    help="don't let the GO7007 drive the I2S clock (on this board audio only flows when it does)")


def start_readers(go, args, stop):
    vq, aq = queue.Queue(), queue.Queue()
    threads = [threading.Thread(target=reader, args=(go, EP_VIDEO, 4096, vq, stop), daemon=True)]
    if not args.no_audio:
        threads.append(threading.Thread(target=reader, args=(go, EP_AUDIO, 4096, aq, stop), daemon=True))
    for t in threads:
        t.start()
    return vq, aq, threads


def start_device(args):
    """Boot the encoder, set up the decoder and codec, and start streaming."""
    pal = not args.ntsc
    go = Go7007()
    go.boot_encoder()
    # force the standard: autodetect misreads VHS colour as PAL-N (0x8 = PAL-B/G/H/I/D, 0x5 = NTSC-M)
    adv7180_setup(go, ((0x50 if args.ntsc else 0x80) | INPUTS[args.input]) if args.insel is None else args.insel)
    for _ in range(20):  # give the decoder up to 2 s to lock
        time.sleep(0.1)
        locked, std = adv7180_status(go)
        if locked:
            time.sleep(0.5)
            locked, std = adv7180_status(go)
            break
    print(f'video decoder: {"signal locked" if locked else "NO SIGNAL"}, detected {std}')

    audio_flags = native.AUDIO_I2S_MODE_1 | native.AUDIO_WORD_16 | (native.AUDIO_I2S_MASTER if args.audio_master else 0)
    if not args.no_audio:
        codec_setup(go)
    if args.audio_master:
        go.write_addr(0x1000, 0x0811)
        go.write_addr(0x1000, 0x0C11)
    image = native.build_fw(
        format=FORMATS[args.format], pal=pal, width=720, height=576 if pal else 480,
        bitrate=args.bitrate, gop_size=args.gop, closed_gop=1, ipb=0, aspect_ratio=native.RATIO_4_3, fps_scale=1,
        sensor_flags=native.SENSOR_656 | native.SENSOR_TV, audio_flags=audio_flags,
        audio_rate=48000, audio_bclk_div=4, audio_main_div=1, hpi_buffer_cap=7)  # gives 48 kHz stereo on this board
    go.send_firmware(image)
    go.read_interrupt()
    return go


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('output', help='output file (.mpg/.m4v/.mjpeg); audio goes to <output>.wav, muxed to .mkv if ffmpeg is present')
    add_device_args(ap)
    ap.add_argument('--duration', type=float, help='seconds to record (default: until Ctrl-C)')
    ap.add_argument('--no-preview', dest='preview', action='store_false', help="don't open a live ffplay preview window")
    args = ap.parse_args()

    pal = not args.ntsc
    go = start_device(args)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    vq, aq, threads = start_readers(go, args, stop)

    parser = native.Parser()
    preview = FFplay.video(args.format, pal) if args.preview and shutil.which('ffplay') else None
    wav_path = args.output + '.wav'
    vbytes = abytes = 0
    t0 = time.time()
    last_print = -1
    with open(args.output, 'wb') as vf:
        wf = None
        if not args.no_audio:
            wf = wave.open(wav_path, 'wb')
            wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(48000)
        done_v = False
        while not done_v:
            if args.duration and time.time() - t0 >= args.duration:
                stop.set()
            try:
                chunk = vq.get(timeout=0.05)
                if chunk is None:
                    done_v = True
                else:
                    data = parser.feed(chunk)
                    vf.write(data)
                    vbytes += len(data)
                    if preview:
                        preview.feed(data)
            except queue.Empty:
                pass
            while wf and not aq.empty():
                a = aq.get()
                if a:
                    wf.writeframes(a)
                    abytes += len(a)
            el = time.time() - t0
            if el - last_print >= 0.5:
                last_print = el
                print(f'\r{el:7.1f}s  video {vbytes / 1e6:8.1f} MB ({vbytes * 8 / max(el, 1e-3) / 1e6:4.1f} Mbit/s)  audio {abytes / 192000:6.1f}s',
                      end='', flush=True)
        for t in threads:
            t.join()
        while wf and not aq.empty():
            a = aq.get()
            if a:
                wf.writeframes(a)
                abytes += len(a)
        if wf:
            wf.close()
    print()
    if preview:
        preview.close()
    go.write_interrupt(0x0001, 0x0001)  # reset encoder so it stops streaming
    go.close()

    if not args.no_audio and abytes and shutil.which('ffmpeg'):
        mkv = os.path.splitext(args.output)[0] + '.mkv'
        r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-fflags', '+genpts', '-r', '25' if pal else '30000/1001',
                            '-i', args.output, '-i', wav_path, '-c:v', 'copy', '-c:a', 'flac', mkv])
        if r.returncode == 0:
            print('muxed ->', mkv)


if __name__ == '__main__':
    try:
        main()
    except HPIError as e:
        sys.exit(f'error: {e}')
