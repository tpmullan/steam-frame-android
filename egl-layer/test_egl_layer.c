// Host-side test of egl_layer.c. tools/build-android-libs.sh builds and runs it before cross-compiling.
#include "egl_layer.c"

#include <stdio.h>
#include <string.h>

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

static int driver_calls;
static int last_attribute;
static unsigned fake_driver(void *display, void *surface, int attribute, int *value) {
	(void)display, (void)surface;
	driver_calls++;
	last_attribute = attribute;
	if (value) *value = 1234;
	return value != NULL;
}
static void other(void) {}

int main(void) {
	// Other entry points pass through untouched.
	CHECK(AndroidGLESLayer_GetProcAddress("eglSwapBuffers", other) == other);
	CHECK(AndroidGLESLayer_GetProcAddress("glDrawArrays", other) == other);
	CHECK(AndroidGLESLayer_Initialize(NULL, NULL) == NULL);

	// eglQuerySurface is replaced; a missing next is left alone.
	CHECK(AndroidGLESLayer_GetProcAddress("eglQuerySurface", NULL) == NULL);
	egl_func hooked = AndroidGLESLayer_GetProcAddress("eglQuerySurface", (egl_func)fake_driver);
	CHECK(hooked != (egl_func)fake_driver);
	query_surface_fn *query = (query_surface_fn *)hooked;

	// The buffer age is answered here: 0, and the driver is not entered.
	int value = 77;
	CHECK(query((void *)1, (void *)2, 0x313D, &value) == 1);
	CHECK(value == 0);
	CHECK(driver_calls == 0);

	// Every other attribute goes to the driver with its arguments.
	value = 0;
	CHECK(query((void *)1, (void *)2, 0x3057 /* EGL_WIDTH */, &value) == 1);
	CHECK(value == 1234);
	CHECK(driver_calls == 1 && last_attribute == 0x3057);

	// A null value pointer is the driver's to reject.
	CHECK(query((void *)1, (void *)2, 0x313D, NULL) == 0);
	CHECK(driver_calls == 2);

	if (failures) return 1;
	puts("test_egl_layer: all checks passed");
	return 0;
}
