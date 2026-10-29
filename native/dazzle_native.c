/*
 * C helpers for the Python Dazzle DVC 170 driver:
 *  - builds the GO7007 encoder init image with Linux's go7007-fw.c
 *  - strips the GO7007 side-channel chunks (timestamps, VBI, motion maps)
 *    from the raw video pipe, like go7007_parse_video_stream()
 */
#include "go7007-priv.h"

static char fw_path[1024];

int request_firmware(const struct firmware **out, const char *name, struct device *dev)
{
	struct firmware *fw;
	FILE *f = fopen(fw_path, "rb");
	long n;
	u8 *data;

	(void)name;
	(void)dev;
	if (!f)
		return -1;
	fseek(f, 0, SEEK_END);
	n = ftell(f);
	fseek(f, 0, SEEK_SET);
	data = malloc(n);
	fw = malloc(sizeof(*fw));
	if (!data || !fw || fread(data, 1, n, f) != (size_t)n) {
		fclose(f);
		free(data);
		free(fw);
		return -1;
	}
	fclose(f);
	fw->size = n;
	fw->data = data;
	*out = fw;
	return 0;
}

void release_firmware(const struct firmware *fw)
{
	if (!fw)
		return;
	free((void *)fw->data);
	free((void *)fw);
}

struct dz_params {
	const char *tv_fw_path;
	u32 format;		/* V4L2 fourcc */
	int pal;
	int width, height;
	int bitrate;
	int gop_size;
	int closed_gop;
	int ipb;
	int aspect_ratio;
	int fps_scale;
	unsigned int sensor_flags;
	unsigned int audio_flags;
	int audio_rate, audio_bclk_div, audio_main_div;
	int hpi_buffer_cap;
	int h_offset, v_offset;
};

int dz_build_fw(const struct dz_params *p, u8 **out, int *len)
{
	static struct go7007_board_info board;
	struct go7007 *go;
	int full_w = 720, full_h = p->pal ? 576 : 480, r;

	snprintf(fw_path, sizeof(fw_path), "%s", p->tv_fw_path);
	board.hpi_buffer_cap = p->hpi_buffer_cap;
	board.sensor_flags = p->sensor_flags;
	board.audio_flags = p->audio_flags;
	board.audio_rate = p->audio_rate;
	board.audio_bclk_div = p->audio_bclk_div;
	board.audio_main_div = p->audio_main_div;

	go = calloc(1, sizeof(*go));
	if (!go)
		return -1;
	go->board_info = &board;
	go->standard = p->pal ? GO7007_STD_PAL : GO7007_STD_NTSC;
	go->sensor_framerate = p->pal ? 25025 : 30000;
	go->fps_scale = p->fps_scale > 0 ? p->fps_scale : 1;
	go->format = p->format;
	go->width = p->width;
	go->height = p->height;
	go->encoder_h_offset = p->h_offset;
	go->encoder_v_offset = p->v_offset;
	/* set_capture_size() for boards without a scaling sensor */
	if (p->width <= full_w / 4) {
		go->encoder_h_halve = go->encoder_v_halve = go->encoder_subsample = 1;
	} else if (p->width <= full_w / 2) {
		go->encoder_h_halve = go->encoder_v_halve = 1;
	}
	(void)full_h;
	/* set_formatting() */
	if (p->format == V4L2_PIX_FMT_MJPEG) {
		go->aspect_ratio = GO7007_RATIO_1_1;
	} else {
		go->pali = p->format == V4L2_PIX_FMT_MPEG1 ? 0 :
			   p->format == V4L2_PIX_FMT_MPEG4 ? 0xf5 : 0x48;
		go->gop_size = p->gop_size;
		go->closed_gop = !!p->closed_gop;
		go->ipb = !!p->ipb;
		go->bitrate = p->bitrate;
		go->repeat_seqhead = 1;
		go->gop_header_enable = 1;
		go->aspect_ratio = p->aspect_ratio;
		go->dvd_mode = p->format == V4L2_PIX_FMT_MPEG2 &&
			       p->bitrate == 9800000 && p->gop_size == 15 &&
			       !p->ipb && p->closed_gop;
	}
	r = go7007_construct_fw_image(go, out, len);
	free(go);
	return r;
}

void dz_free(void *p)
{
	free(p);
}

/* ---- video pipe parser ---- */

enum { ST_DATA, ST_00, ST_00_00, ST_00_00_01, ST_FF, ST_VBI_A, ST_VBI_B, ST_SKIP };

struct dz_parser {
	int state;
	int skip;
};

struct dz_parser *dz_parser_new(void)
{
	return calloc(1, sizeof(struct dz_parser));
}

/* out must hold at least len + 4 bytes; returns number of bytes written */
int dz_parser_feed(struct dz_parser *ps, const u8 *buf, int len, u8 *out)
{
	int i, o = 0;

	for (i = 0; i < len; i++) {
		u8 c = buf[i];

		switch (ps->state) {
		case ST_DATA:
			if (c == 0x00)
				ps->state = ST_00;
			else if (c == 0xFF)
				ps->state = ST_FF;
			else
				out[o++] = c;
			break;
		case ST_00:
			if (c == 0x00) {
				ps->state = ST_00_00;
			} else if (c == 0xFF) {
				out[o++] = 0x00;
				ps->state = ST_FF;
			} else {
				out[o++] = 0x00;
				out[o++] = c;
				ps->state = ST_DATA;
			}
			break;
		case ST_00_00:
			if (c == 0x00) {
				out[o++] = 0x00;
			} else if (c == 0x01) {
				ps->state = ST_00_00_01;
			} else if (c == 0xFF) {
				out[o++] = 0x00;
				out[o++] = 0x00;
				ps->state = ST_FF;
			} else {
				out[o++] = 0x00;
				out[o++] = 0x00;
				out[o++] = c;
				ps->state = ST_DATA;
			}
			break;
		case ST_00_00_01:
			switch (c) {
			case 0xF5:	/* timestamp */
				ps->skip = 12;
				ps->state = ST_SKIP;
				break;
			case 0xF6:	/* vbi */
				ps->state = ST_VBI_A;
				break;
			case 0xF8:	/* motion detection map (modet is off, so pass through) */
				out[o++] = 0x00;
				out[o++] = 0x00;
				out[o++] = 0x01;
				out[o++] = c;
				ps->state = ST_DATA;
				break;
			case 0xFF:
				out[o++] = 0x00;
				out[o++] = 0x00;
				out[o++] = 0x01;
				ps->state = ST_FF;
				break;
			default:
				out[o++] = 0x00;
				out[o++] = 0x00;
				out[o++] = 0x01;
				out[o++] = c;
				ps->state = ST_DATA;
				break;
			}
			break;
		case ST_FF:
			if (c == 0x00) {
				out[o++] = 0xFF;
				ps->state = ST_00;
			} else if (c == 0xFF) {
				out[o++] = 0xFF;
			} else {
				out[o++] = 0xFF;
				out[o++] = c;
				ps->state = ST_DATA;
			}
			break;
		case ST_VBI_A:
			ps->skip = c << 8;
			ps->state = ST_VBI_B;
			break;
		case ST_VBI_B:
			ps->skip |= c;
			ps->state = ps->skip > 0 ? ST_SKIP : ST_DATA;
			break;
		case ST_SKIP:
			if (--ps->skip == 0)
				ps->state = ST_DATA;
			break;
		}
	}
	return o;
}

void dz_parser_free(struct dz_parser *ps)
{
	free(ps);
}
