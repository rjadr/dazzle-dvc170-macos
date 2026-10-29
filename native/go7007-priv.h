/* Reduced go7007-priv.h: only what go7007-fw.c needs (from Linux, GPL-2.0) */
#ifndef GO7007_PRIV_H
#define GO7007_PRIV_H
#include "kshim.h"

#define GO7007_SENSOR_VALID_POLAR	(1<<0)
#define GO7007_SENSOR_HREF_POLAR	(1<<1)
#define GO7007_SENSOR_VREF_POLAR	(1<<2)
#define GO7007_SENSOR_FIELD_ID_POLAR	(1<<3)
#define GO7007_SENSOR_BIT_WIDTH		(1<<4)
#define GO7007_SENSOR_VALID_ENABLE	(1<<5)
#define GO7007_SENSOR_656		(1<<6)
#define GO7007_SENSOR_CONFIG_MASK	0x7f
#define GO7007_SENSOR_TV		(1<<7)
#define GO7007_SENSOR_VBI		(1<<8)
#define GO7007_SENSOR_SCALING		(1<<9)
#define GO7007_SENSOR_SAA7115		(1<<10)

#define GO7007_AUDIO_I2S_MODE_1		(1)
#define GO7007_AUDIO_I2S_MODE_2		(2)
#define GO7007_AUDIO_I2S_MODE_3		(3)
#define GO7007_AUDIO_BCLK_POLAR		(1<<2)
#define GO7007_AUDIO_WORD_14		(14<<4)
#define GO7007_AUDIO_WORD_16		(16<<4)
#define GO7007_AUDIO_ONE_CHANNEL	(1<<11)
#define GO7007_AUDIO_I2S_MASTER		(1<<16)
#define GO7007_AUDIO_OKI_MODE		(1<<17)

#define GO7007_RATIO_1_1	0
#define GO7007_RATIO_4_3	1
#define GO7007_RATIO_16_9	2

struct go7007_board_info {
	int hpi_buffer_cap;
	unsigned int sensor_flags;
	unsigned int audio_flags;
	int audio_rate;
	int audio_bclk_div;
	int audio_main_div;
};

struct go7007 {
	struct device *dev;
	const struct go7007_board_info *board_info;
	enum { GO7007_STD_NTSC, GO7007_STD_PAL, GO7007_STD_OTHER } standard;
	int sensor_framerate;
	int width;
	int height;
	int encoder_h_offset;
	int encoder_v_offset;
	unsigned int encoder_h_halve:1;
	unsigned int encoder_v_halve:1;
	unsigned int encoder_subsample:1;
	u32 format;
	int bitrate;
	int fps_scale;
	int pali;
	int aspect_ratio;
	int gop_size;
	unsigned int ipb:1;
	unsigned int closed_gop:1;
	unsigned int repeat_seqhead:1;
	unsigned int seq_header_enable:1;
	unsigned int gop_header_enable:1;
	unsigned int dvd_mode:1;
	unsigned int interlace_coding:1;
	unsigned int modet_enable:1;
	struct {
		unsigned int enable:1;
		int pixel_threshold;
		int motion_threshold;
		int mb_threshold;
	} modet[4];
	unsigned char modet_map[1624];
};

int go7007_construct_fw_image(struct go7007 *go, u8 **fw, int *fwlen);
#endif
