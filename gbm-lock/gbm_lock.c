// Preloaded into Android's graphics allocator: one buffer mapping at a time.
//
// The allocator (minigbm's gbm_mesa backend) serves requests on four threads.
// Every buffer the CPU will touch it maps and unmaps once to learn its
// stride, and Mesa does all of a GBM device's mapping through one context,
// which only one thread may use at a time. Two such requests arriving
// together crash the service inside Mesa, and Android restarts its whole UI
// after it. Apps starting up do that now and then; a few `screencap`s run
// side by side do it within seconds.
//
// This library stands in front of Mesa's gbm_bo_map and gbm_bo_unmap and
// holds a lock from the one to the other. bin/wgapps preloads it into that
// one service.
//
// Built without the NDK (tools/build-android-libs.sh), so what it needs from
// Android is declared here instead of included.
#include <stddef.h>
#include <stdint.h>

#ifdef __ANDROID__
typedef struct {
	int32_t opaque[10];
} pthread_mutex_t; // 64-bit Android's.
#define PTHREAD_MUTEX_INITIALIZER {{0}}
#define RTLD_NOW 2
int pthread_mutex_lock(pthread_mutex_t *mutex);
int pthread_mutex_unlock(pthread_mutex_t *mutex);
void *dlopen(const char *name, int flags);
void *dlsym(void *handle, const char *symbol);
#else // The test, on the build host.
#include <dlfcn.h>
#include <pthread.h>
#endif

#define ANDROID_LOG_INFO 4
#define ANDROID_LOG_ERROR 6
#define LOG_TAG "wgapps-gbm-lock"
int __android_log_print(int priority, const char *tag, const char *format, ...)
	__attribute__((format(printf, 3, 4)));

#define EXPORT __attribute__((visibility("default")))

struct gbm_bo;
typedef void *map_fn(struct gbm_bo *bo, uint32_t x, uint32_t y, uint32_t width, uint32_t height,
		     uint32_t flags, uint32_t *stride, void **map_data);
typedef void unmap_fn(struct gbm_bo *bo, void *map_data);

static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
// Mesa's own functions, looked up with the lock held.
static map_fn *mesa_map;
static unmap_fn *mesa_unmap;

static void find_mesa(void) {
	void *gbm = dlopen("libgbm_mesa.so", RTLD_NOW);

	if (gbm) {
		mesa_map = (map_fn *)dlsym(gbm, "gbm_bo_map");
		mesa_unmap = (unmap_fn *)dlsym(gbm, "gbm_bo_unmap");
	}
	if (!mesa_map || !mesa_unmap) {
		mesa_map = NULL;
		__android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
				    "no gbm_bo_map and gbm_bo_unmap in libgbm_mesa.so");
		return;
	}
	// Once, at the first mapping: shows in logcat that the lock is in use.
	__android_log_print(ANDROID_LOG_INFO, LOG_TAG, "one buffer mapping at a time");
}

EXPORT void *gbm_bo_map(struct gbm_bo *bo, uint32_t x, uint32_t y, uint32_t width, uint32_t height,
			uint32_t flags, uint32_t *stride, void **map_data) {
	void *address = NULL;

	pthread_mutex_lock(&lock);
	if (!mesa_map) find_mesa();
	if (mesa_map) address = mesa_map(bo, x, y, width, height, flags, stride, map_data);
	// Nothing unmaps a mapping that failed.
	if (!address) pthread_mutex_unlock(&lock);
	return address;
}

// Only ever follows a gbm_bo_map that worked, on the same thread.
EXPORT void gbm_bo_unmap(struct gbm_bo *bo, void *map_data) {
	mesa_unmap(bo, map_data);
	pthread_mutex_unlock(&lock);
}
