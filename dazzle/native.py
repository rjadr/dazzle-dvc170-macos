"""ctypes bindings for libdazzle.dylib (encoder image builder + video pipe parser)."""
import ctypes, os

HERE = os.path.dirname(os.path.abspath(__file__))
_LIB_PATH = os.path.join(HERE, 'libdazzle.dylib')
if not os.path.exists(_LIB_PATH):
    raise SystemExit(f'error: {_LIB_PATH} is missing: run "make -C native" first')
_lib = ctypes.CDLL(_LIB_PATH)


def fourcc(s):
    return ord(s[0]) | ord(s[1]) << 8 | ord(s[2]) << 16 | ord(s[3]) << 24


FMT_MJPEG, FMT_MPEG1, FMT_MPEG2, FMT_MPEG4 = (fourcc(s) for s in ('MJPG', 'MPG1', 'MPG2', 'MPG4'))

SENSOR_VALID_ENABLE = 1 << 5
SENSOR_656 = 1 << 6
SENSOR_TV = 1 << 7
AUDIO_I2S_MODE_1 = 1
AUDIO_WORD_16 = 16 << 4
AUDIO_I2S_MASTER = 1 << 16
RATIO_1_1, RATIO_4_3, RATIO_16_9 = 0, 1, 2


class Params(ctypes.Structure):
    _fields_ = [(n, ctypes.c_char_p if n == 'tv_fw_path' else ctypes.c_uint if n in ('format', 'sensor_flags', 'audio_flags') else ctypes.c_int)
                for n in ('tv_fw_path', 'format', 'pal', 'width', 'height', 'bitrate', 'gop_size', 'closed_gop', 'ipb',
                          'aspect_ratio', 'fps_scale', 'sensor_flags', 'audio_flags', 'audio_rate', 'audio_bclk_div',
                          'audio_main_div', 'hpi_buffer_cap', 'h_offset', 'v_offset')]


_lib.dz_build_fw.argtypes = [ctypes.POINTER(Params), ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)), ctypes.POINTER(ctypes.c_int)]
_lib.dz_free.argtypes = [ctypes.c_void_p]
_lib.dz_parser_new.restype = ctypes.c_void_p
_lib.dz_parser_feed.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
_lib.dz_parser_free.argtypes = [ctypes.c_void_p]


def build_fw(**kw):
    p = Params(tv_fw_path=os.path.join(HERE, 'go7007tv.bin').encode(), **kw)
    out = ctypes.POINTER(ctypes.c_uint8)()
    n = ctypes.c_int()
    if _lib.dz_build_fw(ctypes.byref(p), ctypes.byref(out), ctypes.byref(n)) < 0:
        raise RuntimeError('go7007_construct_fw_image failed')
    data = ctypes.string_at(out, n.value)
    _lib.dz_free(out)
    return data


class Parser:
    def __init__(self):
        self._p = _lib.dz_parser_new()

    def feed(self, buf):
        out = ctypes.create_string_buffer(len(buf) + 4)
        n = _lib.dz_parser_feed(self._p, buf, len(buf), out)
        return out.raw[:n]

    def __del__(self):
        if getattr(self, '_p', None):
            _lib.dz_parser_free(self._p)
