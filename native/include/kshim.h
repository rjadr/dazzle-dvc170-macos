/* Minimal stand-ins for the kernel APIs used by go7007-fw.c */
#ifndef KSHIM_H
#define KSHIM_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int16_t s16;
typedef uint16_t __le16;

#define __cpu_to_le16(x) ((u16)(x))
#define __le16_to_cpu(x) ((u16)(x))
#define cpu_to_le16p(p) (*(p))
#define GFP_KERNEL 0
#define kzalloc(n, f) calloc(1, (n))
#define kcalloc(n, s, f) calloc((n), (s))
#define kfree(p) free(p)
#define dev_err(dev, ...) fprintf(stderr, "go7007-fw: " __VA_ARGS__)
#define MODULE_FIRMWARE(x)
#define EXPORT_SYMBOL(x)
#define noinline_for_stack __attribute__((noinline))
#define fallthrough __attribute__((fallthrough))

struct device;
struct firmware { size_t size; const u8 *data; };
int request_firmware(const struct firmware **fw, const char *name, struct device *dev);
void release_firmware(const struct firmware *fw);

#define V4L2_FOURCC(a, b, c, d) ((u32)(a) | ((u32)(b) << 8) | ((u32)(c) << 16) | ((u32)(d) << 24))
#define V4L2_PIX_FMT_MJPEG V4L2_FOURCC('M', 'J', 'P', 'G')
#define V4L2_PIX_FMT_MPEG1 V4L2_FOURCC('M', 'P', 'G', '1')
#define V4L2_PIX_FMT_MPEG2 V4L2_FOURCC('M', 'P', 'G', '2')
#define V4L2_PIX_FMT_MPEG4 V4L2_FOURCC('M', 'P', 'G', '4')
#define V4L2_PIX_FMT_H263 V4L2_FOURCC('H', '2', '6', '3')
#endif
