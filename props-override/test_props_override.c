// Host-side test of props_override.c against a fake property area.
// tools/build-android-libs.sh builds and runs it before cross-compiling.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define WGAPPS_PROPS_TEST
static char test_dir[256];
#define PROPS_DIR test_dir
#include "props_override.c"

static int failures;
#define CHECK(cond) \
	do { \
		if (!(cond)) { \
			printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
			failures++; \
		} \
	} while (0)
#define CHECK_STR(actual, expected) \
	do { \
		if (strcmp((actual), (expected)) != 0) { \
			printf("FAIL %s:%d: \"%s\" != \"%s\"\n", __FILE__, __LINE__, (actual), (expected)); \
			failures++; \
		} \
	} while (0)

int __android_log_print(int priority, const char *tag, const char *format, ...) {
	(void)priority, (void)tag, (void)format;
	return 0;
}

// --- a fake property area: two pages, as Android maps them (read-only) -----------

struct prop {
	uint32_t serial;
	char value[92];
	char name[32];
};
#define PROP_SIZE sizeof(struct prop)
static char *area;
static size_t page;
static int prop_count;

// Where a new property goes: `at` bytes into the area.
static struct prop *put(size_t at, const char *name, const char *value, int long_flag) {
	struct prop *p = (struct prop *)(area + at);
	memset(p, 0, PROP_SIZE);
	strcpy(p->value, value);
	strcpy(p->name, name);
	p->serial = ((uint32_t)strlen(value) << 24) | (long_flag ? 1u << 16 : 0) | 4; // 4: some counter.
	prop_count++;
	return p;
}

static struct prop *props[16];
static const void *find_in_area(const char *name) {
	for (int i = 0; i < prop_count; i++)
		if (props[i] && !strcmp(props[i]->name, name)) return props[i];
	return NULL;
}
const void *__system_property_find(const char *name) { return find_in_area(name); }

static void new_area(void) {
	if (area) munmap(area, 2 * page);
	area = mmap(NULL, 2 * page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	prop_count = 0;
	memset(props, 0, sizeof props);
	props[0] = put(64, "ro.product.model", "WayDroid arm64 only Device", 0);
	props[1] = put(64 + PROP_SIZE, "ro.product.brand", "waydroid", 0);
	props[2] = put(page - PROP_SIZE / 2, "ro.product.manufacturer", "Waydroid", 0); // Across the page boundary.
	props[3] = put(page + 512, "ro.product.device", "waydroid_arm64_only", 0);
	props[4] = put(page + 512 + PROP_SIZE, "ro.longone", "see long_property", 1);
	prop_count = 5;
	mprotect(area, 2 * page, PROT_READ); // Android maps them read-only.
}

// What a reader of the area sees, the way Android's own reader works out a value.
static void read_value(const struct prop *p, char *out) {
	size_t length = p->serial >> 24;
	memcpy(out, p->value, length);
	out[length] = 0;
}

static void use_file(const char *package, const char *content) {
	char path[300];
	snprintf(path, sizeof path, "%s/%s", test_dir, package);
	FILE *f = fopen(path, "w");
	fputs(content, f);
	fclose(f);
}

// A fresh app process: new area, the preload runs in it.
static void run_in(const char *package) {
	new_area();
	if (package) setenv("WGP", package, 1);
	else unsetenv("WGP");
	apply_overrides();
}

static void unchanged(int index, const char *value) {
	char seen[128];
	read_value(props[index], seen);
	CHECK_STR(seen, value);
}

// --- tests ----------------------------------------------------------------------

static void the_override_is_what_a_reader_of_the_area_sees(void) {
	char seen[128];
	use_file("com.x.y", "ro.product.model=Quest 3\n");
	run_in("com.x.y");
	read_value(props[0], seen);
	CHECK_STR(seen, "Quest 3");
	CHECK((props[0]->serial >> 24) == 7); // The length is part of what a reader goes by.
	CHECK((props[0]->serial & 1) == 0); // Not "being written".
	CHECK((props[0]->serial & 0xfffe) == 4); // The counter is kept.
	CHECK(strlen(props[0]->value) == 7 && props[0]->value[7] == 0 && props[0]->value[8] == 0);
	CHECK_STR(props[0]->name, "ro.product.model");
}

static void other_properties_are_untouched(void) {
	use_file("com.x.y", "ro.product.model=Quest 3\n");
	run_in("com.x.y");
	unchanged(1, "waydroid");
	unchanged(2, "Waydroid");
	unchanged(3, "waydroid_arm64_only");
	unchanged(4, "see long_property");
}

static void a_property_across_a_page_boundary_is_patched_whole(void) {
	use_file("com.x.y", "ro.product.manufacturer=Meta Platforms\nro.product.device=eureka\n");
	run_in("com.x.y");
	unchanged(2, "Meta Platforms");
	unchanged(3, "eureka");
	CHECK_STR(props[2]->name, "ro.product.manufacturer");
}

static void several_overrides_all_apply(void) {
	use_file("com.x.y", "ro.product.model=Quest 3\nro.product.brand=Meta\n"
			    "ro.product.manufacturer=Meta Platforms\nro.product.device=eureka\n");
	run_in("com.x.y");
	unchanged(0, "Quest 3");
	unchanged(1, "Meta");
	unchanged(2, "Meta Platforms");
	unchanged(3, "eureka");
}

static void the_area_stays_read_only(void) {
	use_file("com.x.y", "ro.product.model=Quest 3\n");
	run_in("com.x.y");
	{
		int fds[2];
		CHECK(pipe(fds) == 0);
		// The kernel refuses to read into a read-only page: EFAULT.
		CHECK(write(fds[1], "x", 1) == 1);
		CHECK(read(fds[0], (void *)props[0], 1) == -1);
		close(fds[0]);
		close(fds[1]);
	}
}

static void no_package_means_no_override(void) {
	use_file("com.x.y", "ro.product.model=Quest 3\n");
	run_in(NULL);
	unchanged(0, "WayDroid arm64 only Device");
}

static void another_package_sees_its_own_file_only(void) {
	char path[300];
	use_file("com.x.y", "ro.product.model=Quest 3\n");
	snprintf(path, sizeof path, "%s/com.other.app", test_dir);
	unlink(path);
	run_in("com.other.app");
	unchanged(0, "WayDroid arm64 only Device");
}

static void names_that_are_not_package_names_are_ignored(void) {
	const char *names[] = {"../x", "com.x.y/../com.x.y", "..", ".hidden", "com.x y", "com.x\ny", "a/b"};
	for (size_t i = 0; i < sizeof names / sizeof names[0]; i++) {
		char path[300];
		snprintf(path, sizeof path, "%s/%s", test_dir, ".hidden");
		use_file(".hidden", "ro.product.model=Quest 3\n");
		run_in(names[i]);
		unchanged(0, "WayDroid arm64 only Device");
	}
	{ // A slash would reach into a directory; this file exists there.
		char path[300];
		snprintf(path, sizeof path, "%s/sub", test_dir);
		mkdir(path, 0755);
		use_file("sub/x", "ro.product.model=Quest 3\n");
		run_in("sub/x");
		unchanged(0, "WayDroid arm64 only Device");
	}
	{ // Longer than a `wrap.` property can carry.
		char longest[80];
		memset(longest, 'a', sizeof longest - 1);
		longest[sizeof longest - 1] = 0;
		use_file(longest, "ro.product.model=Quest 3\n");
		run_in(longest);
		unchanged(0, "WayDroid arm64 only Device");
	}
}

// docs/bugs/2026-11-15-angle-composer-crash.md: the composer service got its override through a
// file named "wgapps-composer", the preload took the name for something that is not a package
// and did nothing, with no message. The name Wgapps uses now must work, and a hyphen must not.
static void the_composer_file_name_works_and_a_hyphen_is_silently_ignored(void) {
	use_file("wgapps.composer", "ro.product.model=composer\n");
	run_in("wgapps.composer");
	unchanged(0, "composer");
	use_file("wgapps-composer", "ro.product.model=composer\n");
	run_in("wgapps-composer");
	CHECK(strcmp(props[0]->value, "composer") != 0); // The reproduction of the bug.
}

static void garbled_lines_are_skipped(void) {
	char content[600];
	char name[400];
	memset(name, 'n', sizeof name - 1);
	name[sizeof name - 1] = 0;
	snprintf(content, sizeof content,
		 "no equals sign here\n\n=novalue\n%s=x\nro.product.manufacturer=Meta\r\nro.product.brand=\n"
		 "ro.product.model=Quest 3", // No final newline.
		 name);
	use_file("com.x.y", content);
	run_in("com.x.y");
	unchanged(2, "Meta"); // A carriage return is not part of the value.
	unchanged(0, "Quest 3");
	unchanged(1, ""); // An empty value overrides to empty.
}

static void a_property_that_does_not_exist_is_not_created(void) {
	use_file("com.x.y", "ro.no.such=1\nro.product.model=Quest 3\n");
	run_in("com.x.y");
	CHECK(find_in_area("ro.no.such") == NULL);
	unchanged(0, "Quest 3");
}

static void a_long_property_is_left_alone(void) {
	use_file("com.x.y", "ro.longone=short\n");
	run_in("com.x.y");
	unchanged(4, "see long_property");
	CHECK((props[4]->serial & (1u << 16)) != 0);
}

static void a_long_value_is_cut_to_the_most_a_property_holds(void) {
	char line[200];
	memset(line, 0, sizeof line);
	strcpy(line, "ro.product.model=");
	memset(line + strlen(line), 'v', 120);
	use_file("com.x.y", line);
	run_in("com.x.y");
	CHECK((props[0]->serial >> 24) == 91);
	CHECK(props[0]->value[90] == 'v' && props[0]->value[91] == 0);
}

static void a_later_line_wins(void) {
	use_file("com.x.y", "ro.product.model=First\nro.product.model=Second\n");
	run_in("com.x.y");
	unchanged(0, "Second");
}

static void more_lines_than_the_table_holds_do_not_overflow(void) {
	char content[1500] = "";
	for (int i = 0; i < 60; i++) {
		char line[40];
		snprintf(line, sizeof line, "p.n%d=v%d\n", i, i);
		strcat(content, line);
	}
	strcat(content, "ro.product.model=Quest 3\n");
	use_file("com.x.y", content);
	run_in("com.x.y"); // Must not crash; the line past the table may be dropped.
	CHECK(1);
}

int main(void) {
	page = (size_t)getpagesize();
	snprintf(test_dir, sizeof test_dir, "%s", "/tmp/props-override-test-XXXXXX");
	if (!mkdtemp(test_dir)) return 2;

	the_override_is_what_a_reader_of_the_area_sees();
	other_properties_are_untouched();
	a_property_across_a_page_boundary_is_patched_whole();
	several_overrides_all_apply();
	the_area_stays_read_only();
	no_package_means_no_override();
	another_package_sees_its_own_file_only();
	names_that_are_not_package_names_are_ignored();
	the_composer_file_name_works_and_a_hyphen_is_silently_ignored();
	garbled_lines_are_skipped();
	a_property_that_does_not_exist_is_not_created();
	a_long_property_is_left_alone();
	a_long_value_is_cut_to_the_most_a_property_holds();
	a_later_line_wins();
	more_lines_than_the_table_holds_do_not_overflow();

	{ // Clean up.
		char command[300];
		snprintf(command, sizeof command, "rm -rf '%s'", test_dir);
		if (system(command)) failures++;
	}
	if (failures) {
		printf("%d failure(s)\n", failures);
		return 1;
	}
	puts("props_override: all tests passed");
	return 0;
}
