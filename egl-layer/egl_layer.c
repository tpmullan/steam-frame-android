// An Android GLES layer that answers eglQuerySurface(EGL_BUFFER_AGE_EXT) itself.
//
// Mesa's Android EGL runs that query with the display lock held and, to learn the buffer's age, dequeues
// the next back buffer, which blocks until a buffer is free. The thread that would free it (a SurfaceTexture
// consumer, in updateTexImage > eglCreateSyncKHR) needs the same lock, so the two wait for each other and
// the app's frames stop. Wolvic froze like that a few seconds after leaving fullscreen video (stack dump in
// docs/superpowers/spikes/S3-S4-S5-partial.md). Upstream Mesa still has the pattern (droid_query_buffer_age);
// a 2018 patch series on mesa-dev proposed dropping the display mutex around the dequeue.
//
// Answering 0 is what EGL_EXT_buffer_age defines for "the contents are undefined": the app redraws the whole
// buffer, as it does when the extension is absent. Every other query goes to the driver unchanged.
//
// Loaded by Android's libEGL from /data/local/debug/gles when debug.gles.layers names it (bin/wgapps).
// Built without the NDK (tools/build-android-libs.sh), so what it needs from Android is declared here.
#include <stddef.h>

#define ANDROID_LOG_INFO 4
#define LOG_TAG "wgapps-egl-layer"
int __android_log_print(int priority, const char *tag, const char *format, ...)
	__attribute__((format(printf, 3, 4)));
int strcmp(const char *a, const char *b);

#define EXPORT __attribute__((visibility("default")))
#define EGL_BUFFER_AGE_EXT 0x313D
#define EGL_TRUE 1

typedef void (*egl_func)(void);
typedef void *egl_get_next(void *layer_id, const char *name);
typedef unsigned query_surface_fn(void *display, void *surface, int attribute, int *value);

static query_surface_fn *next_query_surface;
static volatile int answered; // Logged once (a racing second line is harmless), so the log shows use.

static unsigned query_surface(void *display, void *surface, int attribute, int *value) {
	if (attribute == EGL_BUFFER_AGE_EXT && value) {
		if (!answered) {
			answered = 1;
			__android_log_print(ANDROID_LOG_INFO, LOG_TAG,
					    "answering EGL_BUFFER_AGE_EXT with 0 (Mesa would block with the display lock held)");
		}
		*value = 0;
		return EGL_TRUE;
	}
	return next_query_surface(display, surface, attribute, value);
}

// Called once per layer by libEGL; nothing to remember.
EXPORT egl_func AndroidGLESLayer_Initialize(void *layer_id, egl_get_next *get_next) {
	(void)layer_id, (void)get_next;
	return NULL;
}

// Called for every EGL and GLES entry point (and for eglGetProcAddress lookups): `next` is what the layer
// below would run. Anything but eglQuerySurface passes through.
EXPORT egl_func AndroidGLESLayer_GetProcAddress(const char *name, egl_func next) {
	if (!strcmp(name, "eglQuerySurface") && next) {
		next_query_surface = (query_surface_fn *)next;
		return (egl_func)query_surface;
	}
	return next;
}
