CFLAGS = -O2 -fPIC -Iinclude -I. -Wno-unused-function -Wno-implicit-fallthrough
../dazzle/libdazzle.dylib: go7007-fw.c dazzle_native.c go7007-priv.h include/kshim.h
	$(CC) $(CFLAGS) -dynamiclib -o $@ go7007-fw.c dazzle_native.c
