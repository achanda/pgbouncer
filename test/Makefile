
PG_CPPFLAGS = -I$(shell pg_config --includedir)
PG_LIBS = -lpq
PG_LDFLAGS = -L$(shell pg_config --libdir)

USUAL_DIR = ../lib

SUBLOC = test
DIST_SUBDIRS = ssl


noinst_PROGRAMS = hba_test tls_ciphers_test
tls_ciphers_test_CPPFLAGS = -I../include $(LIBEVENT_CFLAGS) $(TLS_CPPFLAGS)
tls_ciphers_test_LDFLAGS = $(TLS_LDFLAGS)
tls_ciphers_test_LDADD = $(LIBEVENT_LIBS) $(TLS_LIBS)
tls_ciphers_test_SOURCES = tls_ciphers_test.c
tls_ciphers_test_EMBED_LIBUSUAL = 1

hba_test_CPPFLAGS = -I../include $(LIBEVENT_CFLAGS)
hba_test_LDADD = $(LIBEVENT_LIBS) $(TLS_LIBS)
hba_test_CFLAGS = -O0
hba_test_SOURCES = hba_test.c ../src/hba.c ../src/util.c
hba_test_EMBED_LIBUSUAL = 1

EXTRA_PROGRAMS = asynctest
asynctest_CPPFLAGS = -I../include $(PG_CPPFLAGS) $(LIBEVENT_CFLAGS)
asynctest_LDFLAGS = $(PG_LDFLAGS)
asynctest_LDADD = $(PG_LIBS) $(LIBEVENT_LIBS)
asynctest_SOURCES = asynctest.c
asynctest_EMBED_LIBUSUAL = 1

AM_FEATURES = libusual


include ../config.mak
include ../lib/mk/antimake.mk

check: all
	./hba_test
	./tls_ciphers_test
