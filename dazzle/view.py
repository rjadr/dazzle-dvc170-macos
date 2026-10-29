"""Watch the live picture (and sound) from a Pinnacle Dazzle DVC 170 without recording.

    python -m dazzle.view              # picture and sound
    python -m dazzle.view --no-audio   # picture only

Stop with Ctrl-C, or by closing the window.
"""
import argparse, queue, shutil, signal, sys, threading

from . import native
from .capture import FFplay, add_device_args, start_device, start_readers
from .hpi import HPIError


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_device_args(ap)
    args = ap.parse_args()
    if not shutil.which('ffplay'):
        sys.exit('error: ffplay not found (brew install ffmpeg)')

    go = start_device(args)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    vq, aq, threads = start_readers(go, args, stop)
    window = FFplay.video(args.format, not args.ntsc, title='Dazzle live')
    speaker = None if args.no_audio else FFplay.audio()
    print('playing; Ctrl-C or close the window to stop')

    parser = native.Parser()
    while not stop.is_set():
        try:
            chunk = vq.get(timeout=0.1)
        except queue.Empty:
            chunk = b''
        if chunk is None:
            break
        if chunk:
            window.feed(parser.feed(chunk))
        while speaker and not aq.empty():
            if a := aq.get():
                speaker.feed(a)
        if not window.alive():  # window closed
            stop.set()

    stop.set()
    for t in threads:
        t.join()
    window.close()
    if speaker:
        speaker.close()
    go.write_interrupt(0x0001, 0x0001)  # reset encoder so it stops streaming
    go.close()


if __name__ == '__main__':
    try:
        main()
    except HPIError as e:
        sys.exit(f'error: {e}')
