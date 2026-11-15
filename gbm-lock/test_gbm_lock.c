// Host-side test of gbm_lock.c against a fake Mesa.
// tools/build-android-libs.sh builds and runs it before cross-compiling.
#define _POSIX_C_SOURCE 200809L // alarm
#include "gbm_lock.c"

#include <sched.h>
#include <stdio.h>
#include <unistd.h>

static int failures;
#define CHECK(cond) \
	do { \
		if (!(cond)) { \
			printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
			failures++; \
		} \
	} while (0)

int __android_log_print(int priority, const char *tag, const char *format, ...) {
	(void)priority, (void)tag, (void)format;
	return 0;
}

// --- fake Mesa ----------------------------------------------------------------

#define BO ((struct gbm_bo *)0xb0)
static int open_maps; // Mapped and not yet unmapped.
static int overlaps; // Times a mapping began while another was open.
static int map_fails;
static uint32_t seen[5];

static void *fake_map(struct gbm_bo *bo, uint32_t x, uint32_t y, uint32_t width, uint32_t height,
		      uint32_t flags, uint32_t *stride, void **map_data) {
	if (map_fails) return NULL;
	if (__atomic_add_fetch(&open_maps, 1, __ATOMIC_SEQ_CST) != 1)
		__atomic_add_fetch(&overlaps, 1, __ATOMIC_SEQ_CST);
	// Give the other threads their chance.
	sched_yield();
	seen[0] = x, seen[1] = y, seen[2] = width, seen[3] = height, seen[4] = flags;
	*stride = width * 4;
	*map_data = bo;
	return &seen;
}

static void fake_unmap(struct gbm_bo *bo, void *map_data) {
	if (bo != BO || map_data != BO) __atomic_add_fetch(&overlaps, 1000000, __ATOMIC_SEQ_CST);
	sched_yield();
	__atomic_sub_fetch(&open_maps, 1, __ATOMIC_SEQ_CST);
}

// --- tests ---------------------------------------------------------------------

static void test_calls_reach_mesa(void) {
	uint32_t stride = 0;
	void *map_data = NULL;

	CHECK(gbm_bo_map(BO, 1, 2, 30, 40, 3, &stride, &map_data) == &seen);
	CHECK(seen[0] == 1 && seen[1] == 2 && seen[2] == 30 && seen[3] == 40 && seen[4] == 3);
	CHECK(stride == 120 && map_data == BO && open_maps == 1);
	gbm_bo_unmap(BO, map_data);
	CHECK(open_maps == 0 && overlaps == 0);
}

// Nothing unmaps a mapping that failed, so it must not keep the lock: the
// next one would wait for ever (the alarm in main ends that).
static void test_a_failed_mapping_does_not_block_the_next(void) {
	uint32_t stride;
	void *map_data;

	map_fails = 1;
	CHECK(gbm_bo_map(BO, 0, 0, 8, 8, 1, &stride, &map_data) == NULL);
	map_fails = 0;
	CHECK(gbm_bo_map(BO, 0, 0, 8, 8, 1, &stride, &map_data) == &seen);
	gbm_bo_unmap(BO, map_data);
	CHECK(open_maps == 0);
}

static void *map_and_unmap(void *unused) {
	uint32_t stride;
	void *map_data;
	int i;

	(void)unused;
	for (i = 0; i < 20000; i++)
		if (gbm_bo_map(BO, 0, 0, 8, 8, 1, &stride, &map_data)) gbm_bo_unmap(BO, map_data);
	return NULL;
}

// The allocator's four threads.
static void test_one_mapping_at_a_time(void) {
	pthread_t threads[4];
	int i;

	for (i = 0; i < 4; i++) CHECK(pthread_create(&threads[i], NULL, map_and_unmap, NULL) == 0);
	for (i = 0; i < 4; i++) pthread_join(threads[i], NULL);
	CHECK(overlaps == 0);
	CHECK(open_maps == 0);
}

int main(void) {
	alarm(60);
	mesa_map = fake_map;
	mesa_unmap = fake_unmap;
	test_calls_reach_mesa();
	test_a_failed_mapping_does_not_block_the_next();
	test_one_mapping_at_a_time();
	if (failures) return 1;
	printf("gbm_lock: all checks passed\n");
	return 0;
}
