// Preloaded into one app: its device properties, as the user set them.
//
// Some apps pick their controllers or features by the device model Android
// reports (ro.product.model), and a headset they have never heard of gets the
// bare minimum. Android runs an app through a preload named by the property
// `wrap.<package>`, for that one app's main process only. bin/wgapps sets that
// property when the user runs `wgapps app set <package> model "Quest 3"`, to
// this library plus WGP=<package>.
//
// At load, before any of the app's code runs, the library reads
// /data/wgapps/props.d/<package> (one name=value per line) and writes each
// value into the app's own copy of Android's property area. That area is
// mapped read-only and shared by every process; here the page holding the
// property is replaced, in this process alone, by a private copy with the new
// value. Everything that reads the property then sees it: native code, Java's
// Build.MODEL, and libraries that call libc directly. (Intercepting the read
// functions does not: an app's own libraries live in a linker namespace the
// preload does not reach.)
//
// A page is copied whole, so the properties stored next to an overridden one
// stop updating in this process. Overrides are meant for read-only
// ro.product.* properties, which never change after boot.
//
// Built without the NDK (tools/build-android-libs.sh), so what it needs from
// Android is declared here instead of included.
#include <stddef.h>
#include <stdint.h>

#ifdef __ANDROID__
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_PRIVATE 2
#define MAP_FIXED 0x10
#define MAP_ANONYMOUS 0x20
#define MAP_FAILED ((void *)-1)
#define O_RDONLY 0
#define O_CLOEXEC 02000000
typedef long ssize_t;
void *mmap(void *address, size_t length, int protection, int flags, int fd, long offset);
int mprotect(void *address, size_t length, int protection);
int getpagesize(void);
void *memcpy(void *to, const void *from, size_t count);
void *memset(void *to, int byte, size_t count);
size_t strlen(const char *string);
char *getenv(const char *name);
int open(const char *path, int flags, ...);
ssize_t read(int fd, void *buffer, size_t count);
int close(int fd);
#else // The test, on the build host.
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#endif

#define ANDROID_LOG_INFO 4
#define ANDROID_LOG_WARN 5
#define LOG_TAG "wgapps-props"
int __android_log_print(int priority, const char *tag, const char *format, ...)
	__attribute__((format(printf, 3, 4)));
const void *__system_property_find(const char *name);

#ifndef PROPS_DIR
#define PROPS_DIR "/data/wgapps/props.d"
#endif

#define NAME_MAX_LEN 31 // Android's property names for the legacy API.
#define VALUE_MAX_LEN 91 // Android's longest inline property value, 92 bytes with the terminator.
#define PACKAGE_MAX_LEN 54 // The longest package a `wrap.` property can carry.
#define FILE_MAX 4096
#define MAX_PAGE 16384

// Android's prop_info, which starts with a serial: bit 0 means "being written", bit 16 "the value is
// stored elsewhere", bits 24 to 31 are the value's length; then the value; then the name.
struct prop_info {
	uint32_t serial;
	char value[VALUE_MAX_LEN + 1];
};
#define LONG_FLAG (1u << 16)

static char saved[2 * MAX_PAGE];
static char text[FILE_MAX];

static void set_property(const char *name, size_t name_length, const char *value, size_t value_length) {
	char key[NAME_MAX_LEN + 1];
	struct prop_info *pi;
	uintptr_t first, last;
	size_t size, i, page = (size_t)getpagesize();

	if (name_length == 0 || name_length > NAME_MAX_LEN) return;
	for (i = 0; i < name_length; i++) key[i] = name[i];
	key[name_length] = 0;
	if (value_length > VALUE_MAX_LEN) value_length = VALUE_MAX_LEN;

	pi = (struct prop_info *)__system_property_find(key);
	if (!pi) return; // Overriding a property that exists; nothing is made up.
	if (pi->serial & LONG_FLAG) {
		__android_log_print(ANDROID_LOG_WARN, LOG_TAG, "%s is a long property, left alone", key);
		return;
	}

	// The pages the property's 96 bytes lie on, in one run.
	first = (uintptr_t)pi & ~(uintptr_t)(page - 1);
	last = ((uintptr_t)pi + sizeof *pi - 1) & ~(uintptr_t)(page - 1);
	size = last - first + page;
	if (size > sizeof saved) {
		__android_log_print(ANDROID_LOG_WARN, LOG_TAG, "page size %zu not supported", page);
		return;
	}
	memcpy(saved, (void *)first, size);
	if (mmap((void *)first, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) ==
	    MAP_FAILED) {
		__android_log_print(ANDROID_LOG_WARN, LOG_TAG, "cannot replace the page of %s", key);
		return;
	}
	memcpy((void *)first, saved, size);
	memset(pi->value, 0, sizeof pi->value);
	memcpy(pi->value, value, value_length);
	pi->serial = (pi->serial & 0x00fffffeu) | ((uint32_t)value_length << 24);
	mprotect((void *)first, size, PROT_READ);
	__android_log_print(ANDROID_LOG_INFO, LOG_TAG, "%s overridden", key);
}

static int package_ok(const char *package) {
	size_t i, length = strlen(package);
	if (length == 0 || length > PACKAGE_MAX_LEN) return 0;
	for (i = 0; i < length; i++) {
		char c = package[i];
		int word = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
		// No slash, so no way out of the directory; no leading dot, so no hidden file.
		if (!word && c != '.') return 0;
		if (c == '.' && i == 0) return 0;
	}
	return 1;
}

static void apply_text(size_t length) {
	size_t start = 0;
	while (start < length) {
		size_t end = start, equals = 0;
		int found = 0;
		while (end < length && text[end] != '\n') {
			if (!found && text[end] == '=') equals = end, found = 1;
			end++;
		}
		if (found) {
			size_t value_end = end;
			if (value_end > equals + 1 && text[value_end - 1] == '\r') value_end--;
			set_property(text + start, equals - start, text + equals + 1, value_end - (equals + 1));
		}
		start = end + 1;
	}
}

static void apply_overrides(void) {
	char path[sizeof PROPS_DIR + PACKAGE_MAX_LEN + 2];
	const char *package = getenv("WGP");
	size_t dir_length = strlen(PROPS_DIR), length = 0;
	ssize_t got;
	int fd;

	if (!package || !package_ok(package)) return;
	memcpy(path, PROPS_DIR, dir_length);
	path[dir_length] = '/';
	memcpy(path + dir_length + 1, package, strlen(package) + 1);
	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0) return;
	while (length < FILE_MAX && (got = read(fd, text + length, FILE_MAX - length)) > 0) length += (size_t)got;
	close(fd);
	apply_text(length);
}

#ifndef WGAPPS_PROPS_TEST
__attribute__((constructor)) static void props_override_init(void) { apply_overrides(); }
#endif
