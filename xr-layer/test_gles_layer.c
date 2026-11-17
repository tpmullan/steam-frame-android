// Host-side test of gles_layer.c against a fake runtime and fake GL.
// tools/build-android-libs.sh builds and runs it before cross-compiling.
#include "gles_layer.c"

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

// --- fake Android/GL ---------------------------------------------------------

int __android_log_print(int priority, const char *tag, const char *format, ...) {
	(void)priority, (void)tag, (void)format;
	return 0;
}

static char blend_property[92];
static char drop_property[92];
static char scale_property[92];
int __system_property_get(const char *name, char *value) {
	const char *source = !strcmp(name, "debug.xr.blend_mode") ? blend_property
			     : !strcmp(name, "debug.xr.drop_layers") ? drop_property
			     : !strcmp(name, "debug.xr.render_scale") ? scale_property
								       : "";
	size_t length = strlen(source);

	if (length == 0) return 0;
	memcpy(value, source, length + 1);
	return (int)length;
}

static void *gl_context;
static const char *gl_extensions;
static unsigned gl_disabled[8];
static int gl_disable_calls;

void *eglGetCurrentContext(void) { return gl_context; }
const unsigned char *glGetString(unsigned name) {
	return name == 0x1F03 && gl_context ? (const unsigned char *)gl_extensions : NULL;
}
void glDisable(unsigned cap) { gl_disabled[gl_disable_calls++ % 8] = cap; }

// --- fake runtime -------------------------------------------------------------

#define SESSION ((XrSession)0x5e55)
static int64_t rt_formats[8];
static uint32_t rt_format_count;
static int64_t rt_created_format;
static XrResult rt_create_result;
static int rt_create_calls;
// Like SteamVR on Mesa: lists these depth formats but cannot create them.
static int rt_small_depth_fails;
static int rt_begin_frames;

static XRAPI_ATTR XrResult XRAPI_CALL rt_enumerate(XrSession session, uint32_t capacity,
						    uint32_t *count, int64_t *formats) {
	CHECK(session == SESSION);
	*count = rt_format_count;
	if (capacity == 0) return XR_SUCCESS;
	if (capacity < rt_format_count) return XR_ERROR_SIZE_INSUFFICIENT;
	memcpy(formats, rt_formats, rt_format_count * sizeof *formats);
	return XR_SUCCESS;
}

static XRAPI_ATTR XrResult XRAPI_CALL rt_create(XrSession session, const XrSwapchainCreateInfo *info,
						 XrSwapchain *swapchain) {
	CHECK(session == SESSION);
	rt_create_calls++;
	rt_created_format = info->format;
	if (rt_small_depth_fails &&
	    (info->format == GL_DEPTH_COMPONENT16 || info->format == GL_DEPTH_COMPONENT24))
		return XR_ERROR_RUNTIME_FAILURE;
	if (XR_SUCCEEDED(rt_create_result)) *swapchain = (XrSwapchain)0x5c;
	return rt_create_result;
}

static XRAPI_ATTR XrResult XRAPI_CALL rt_begin_frame(XrSession session, const XrFrameBeginInfo *info) {
	(void)session, (void)info;
	rt_begin_frames++;
	return XR_SUCCESS;
}

static XrEnvironmentBlendMode rt_blend_seen;
static uint32_t rt_layers_seen;
static int rt_end_frames;
static XRAPI_ATTR XrResult XRAPI_CALL rt_end_frame(XrSession session, const XrFrameEndInfo *info) {
	(void)session;
	rt_blend_seen = info->environmentBlendMode;
	rt_layers_seen = info->layerCount;
	rt_end_frames++;
	return XR_SUCCESS;
}

// Like SteamVR on the Frame: recommends 1728x1728 for a 2160x2160 panel and allows far more.
static uint32_t rt_max_size = 4320;
static uint32_t rt_view_calls;
static XRAPI_ATTR XrResult XRAPI_CALL rt_enumerate_views(XrInstance instance, XrSystemId system,
							  XrViewConfigurationType type, uint32_t capacity,
							  uint32_t *count, XrViewConfigurationView *views) {
	uint32_t i;

	(void)instance, (void)system, (void)type;
	rt_view_calls++;
	*count = 2;
	if (capacity == 0) return XR_SUCCESS;
	if (capacity < 2) return XR_ERROR_SIZE_INSUFFICIENT;
	for (i = 0; i < 2; i++) {
		views[i].recommendedImageRectWidth = views[i].recommendedImageRectHeight = 1728;
		views[i].maxImageRectWidth = views[i].maxImageRectHeight = rt_max_size;
	}
	return XR_SUCCESS;
}

static XRAPI_ATTR XrResult XRAPI_CALL rt_gipa(XrInstance instance, const char *name,
					       PFN_xrVoidFunction *function) {
	(void)instance;
	*function = NULL;
	if (!strcmp(name, "xrEnumerateSwapchainFormats")) *function = (PFN_xrVoidFunction)rt_enumerate;
	if (!strcmp(name, "xrCreateSwapchain")) *function = (PFN_xrVoidFunction)rt_create;
	if (!strcmp(name, "xrEnumerateViewConfigurationViews"))
		*function = (PFN_xrVoidFunction)rt_enumerate_views;
	if (!strcmp(name, "xrBeginFrame")) *function = (PFN_xrVoidFunction)rt_begin_frame;
	if (!strcmp(name, "xrEndFrame")) *function = (PFN_xrVoidFunction)rt_end_frame;
	return *function ? XR_SUCCESS : XR_ERROR_FUNCTION_UNSUPPORTED;
}

static XrApiLayerNextInfo below = {XR_LOADER_INTERFACE_STRUCT_API_LAYER_NEXT_INFO,
				   XR_API_LAYER_NEXT_INFO_STRUCT_VERSION, sizeof below};
static const XrApiLayerNextInfo *rt_seen_next_info;

static XRAPI_ATTR XrResult XRAPI_CALL rt_create_instance(const XrInstanceCreateInfo *info,
							  const XrApiLayerCreateInfo *layer_info,
							  XrInstance *instance) {
	(void)info;
	rt_seen_next_info = layer_info->nextInfo;
	*instance = (XrInstance)0x1157;
	return XR_SUCCESS;
}

// --- the layer as the loader and an app drive it -------------------------------

static XrNegotiateApiLayerRequest request = {XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST,
					     XR_API_LAYER_INFO_STRUCT_VERSION, sizeof request};
static XrResult (XRAPI_PTR *app_enumerate)(XrSession, uint32_t, uint32_t *, int64_t *);
static XrResult (XRAPI_PTR *app_create)(XrSession, const XrSwapchainCreateInfo *, XrSwapchain *);
static XrResult (XRAPI_PTR *app_enumerate_views)(XrInstance, XrSystemId, XrViewConfigurationType,
						  uint32_t, uint32_t *, XrViewConfigurationView *);
static XrResult (XRAPI_PTR *app_begin_frame)(XrSession, const XrFrameBeginInfo *);
static XrResult (XRAPI_PTR *app_end_frame)(XrSession, const XrFrameEndInfo *);

static void set_runtime_formats(uint32_t count, const int64_t *formats) {
	rt_format_count = count;
	memcpy(rt_formats, formats, count * sizeof *formats);
}

static void test_negotiation(void) {
	XrNegotiateLoaderInfo loader = {XR_LOADER_INTERFACE_STRUCT_LOADER_INFO,
					XR_LOADER_INFO_STRUCT_VERSION,
					sizeof loader,
					1,
					XR_CURRENT_LOADER_API_LAYER_VERSION,
					XR_MAKE_VERSION(1, 0, 0),
					XR_MAKE_VERSION(1, 0x3ff, 0xfff)};
	CHECK(xrNegotiateLoaderApiLayerInterface(NULL, LAYER_NAME, &request) ==
	      XR_ERROR_INITIALIZATION_FAILED);
	CHECK(xrNegotiateLoaderApiLayerInterface(&loader, "XR_APILAYER_other", &request) ==
	      XR_ERROR_INITIALIZATION_FAILED);
	loader.minInterfaceVersion = 2;
	loader.maxInterfaceVersion = 2;
	CHECK(xrNegotiateLoaderApiLayerInterface(&loader, LAYER_NAME, &request) ==
	      XR_ERROR_INITIALIZATION_FAILED);
	loader.minInterfaceVersion = 1;
	CHECK(xrNegotiateLoaderApiLayerInterface(&loader, LAYER_NAME, &request) == XR_SUCCESS);
	CHECK(request.layerInterfaceVersion == 1);
	CHECK(XR_VERSION_MAJOR(request.layerApiVersion) == 1);
	CHECK(request.getInstanceProcAddr && request.createApiLayerInstance);
}

static void test_nothing_to_offer_before_an_instance_exists(void) {
	// Android loaders ask each layer for this right after negotiating.
	PFN_xrVoidFunction function = (PFN_xrVoidFunction)rt_end_frame;

	CHECK(request.getInstanceProcAddr(XR_NULL_HANDLE, "xrInitializeLoaderKHR", &function) ==
	      XR_ERROR_FUNCTION_UNSUPPORTED);
	CHECK(function == NULL);
}

static void test_instance_creation_goes_down_the_chain(void) {
	XrApiLayerNextInfo ours = {XR_LOADER_INTERFACE_STRUCT_API_LAYER_NEXT_INFO,
				   XR_API_LAYER_NEXT_INFO_STRUCT_VERSION, sizeof ours};
	XrApiLayerCreateInfo layer_info = {XR_LOADER_INTERFACE_STRUCT_API_LAYER_CREATE_INFO,
					   XR_API_LAYER_CREATE_INFO_STRUCT_VERSION,
					   sizeof layer_info};
	XrInstanceCreateInfo info = {XR_TYPE_INSTANCE_CREATE_INFO};
	XrInstance instance = XR_NULL_HANDLE;
	PFN_xrVoidFunction function;

	ours.nextGetInstanceProcAddr = rt_gipa;
	ours.nextCreateApiLayerInstance = rt_create_instance;
	ours.next = &below;
	layer_info.nextInfo = &ours;
	CHECK(request.createApiLayerInstance(&info, &layer_info, &instance) == XR_SUCCESS);
	CHECK(instance == (XrInstance)0x1157);
	CHECK(rt_seen_next_info == &below);
	CHECK(layer_info.nextInfo == &ours);

	CHECK(request.getInstanceProcAddr(instance, "xrEndFrame", &function) == XR_SUCCESS);
	CHECK(function && function != (PFN_xrVoidFunction)rt_end_frame); // hooked for the blend mode
	CHECK(request.getInstanceProcAddr(instance, "xrNoSuchFunction", &function) ==
	      XR_ERROR_FUNCTION_UNSUPPORTED);
	CHECK(request.getInstanceProcAddr(instance, "xrEnumerateSwapchainFormats", &function) ==
	      XR_SUCCESS);
	CHECK(function && function != (PFN_xrVoidFunction)rt_enumerate);
	app_enumerate = (XrResult(XRAPI_PTR *)(XrSession, uint32_t, uint32_t *, int64_t *))function;
	CHECK(request.getInstanceProcAddr(instance, "xrCreateSwapchain", &function) == XR_SUCCESS);
	CHECK(function && function != (PFN_xrVoidFunction)rt_create);
	app_create = (XrResult(XRAPI_PTR *)(XrSession, const XrSwapchainCreateInfo *, XrSwapchain *))function;
	CHECK(request.getInstanceProcAddr(instance, "xrEnumerateViewConfigurationViews", &function) ==
	      XR_SUCCESS);
	CHECK(function && function != (PFN_xrVoidFunction)rt_enumerate_views);
	app_enumerate_views = (XrResult(XRAPI_PTR *)(XrInstance, XrSystemId, XrViewConfigurationType,
						     uint32_t, uint32_t *,
						     XrViewConfigurationView *))function;
	CHECK(request.getInstanceProcAddr(instance, "xrBeginFrame", &function) == XR_SUCCESS);
	CHECK(function && function != (PFN_xrVoidFunction)rt_begin_frame);
	app_begin_frame = (XrResult(XRAPI_PTR *)(XrSession, const XrFrameBeginInfo *))function;
	CHECK(request.getInstanceProcAddr(instance, "xrEndFrame", &function) == XR_SUCCESS);
	CHECK(function && function != (PFN_xrVoidFunction)rt_end_frame);
	app_end_frame = (XrResult(XRAPI_PTR *)(XrSession, const XrFrameEndInfo *))function;
}

static void test_rgba8_is_offered_when_the_runtime_only_has_srgb(void) {
	int64_t formats[4] = {-1, -1, -1, -1};
	uint32_t count = 99;

	set_runtime_formats(2, (int64_t[]){GL_SRGB8_ALPHA8, 0x881A});
	CHECK(app_enumerate(SESSION, 0, &count, NULL) == XR_SUCCESS);
	CHECK(count == 3);
	CHECK(app_enumerate(SESSION, 4, &count, formats) == XR_SUCCESS);
	CHECK(count == 3);
	CHECK(formats[0] == GL_SRGB8_ALPHA8 && formats[1] == 0x881A);
	CHECK(formats[2] == GL_RGBA8 && formats[3] == -1);
	count = 99;
	CHECK(app_enumerate(SESSION, 3, &count, formats) == XR_SUCCESS && count == 3);
	// The two-call idiom: a buffer the extra format does not fit in is an
	// error that reports the size needed, also when it would fit the
	// runtime's own list or is a single entry.
	count = 99;
	CHECK(app_enumerate(SESSION, 2, &count, formats) == XR_ERROR_SIZE_INSUFFICIENT && count == 3);
	count = 99;
	CHECK(app_enumerate(SESSION, 1, &count, formats) == XR_ERROR_SIZE_INSUFFICIENT && count == 3);
}

static void test_other_format_lists_are_left_alone(void) {
	int64_t formats[4] = {-1, -1, -1, -1};
	uint32_t count = 99;

	// A runtime that has GL_RGBA8 itself.
	set_runtime_formats(2, (int64_t[]){GL_SRGB8_ALPHA8, GL_RGBA8});
	CHECK(app_enumerate(SESSION, 0, &count, NULL) == XR_SUCCESS && count == 2);
	CHECK(app_enumerate(SESSION, 4, &count, formats) == XR_SUCCESS && count == 2);
	CHECK(formats[1] == GL_RGBA8 && formats[2] == -1);
	// A Vulkan session: VK_FORMAT_R8G8B8A8_SRGB, VK_FORMAT_B8G8R8A8_SRGB.
	set_runtime_formats(2, (int64_t[]){43, 50});
	CHECK(app_enumerate(SESSION, 0, &count, NULL) == XR_SUCCESS && count == 2);
	CHECK(app_enumerate(SESSION, 4, &count, formats) == XR_SUCCESS && count == 2);
	CHECK(formats[0] == 43 && formats[1] == 50 && formats[2] == -1);
}

static XrResult create_with(int64_t format) {
	XrSwapchainCreateInfo info = {XR_TYPE_SWAPCHAIN_CREATE_INFO};
	XrSwapchain swapchain = XR_NULL_HANDLE;
	XrResult result;

	info.format = format;
	info.width = info.height = 64;
	rt_created_format = -1;
	rt_create_calls = 0;
	result = app_create(SESSION, &info, &swapchain);
	CHECK(info.format == format);
	CHECK(XR_FAILED(result) || swapchain == (XrSwapchain)0x5c);
	return result;
}

static void begin(void) {
	int before = rt_begin_frames;
	CHECK(app_begin_frame(SESSION, NULL) == XR_SUCCESS);
	CHECK(rt_begin_frames == before + 1);
}

static void test_swapchains_and_srgb_encoding(void) {
	gl_context = &gl_context;
	gl_extensions = "GL_EXT_sRGB GL_EXT_sRGB_write_control GL_OES_depth24";
	rt_create_result = XR_SUCCESS;

	// Nothing of ours in play: the app's GL state is not touched.
	set_runtime_formats(2, (int64_t[]){GL_SRGB8_ALPHA8, GL_RGBA8});
	CHECK(create_with(GL_RGBA8) == XR_SUCCESS && rt_created_format == GL_RGBA8);
	set_runtime_formats(2, (int64_t[]){GL_SRGB8_ALPHA8, 0x881A});
	CHECK(create_with(0x881A) == XR_SUCCESS && rt_created_format == 0x881A);
	CHECK(create_with(GL_SRGB8_ALPHA8) == XR_SUCCESS && rt_created_format == GL_SRGB8_ALPHA8);
	rt_create_result = XR_ERROR_RUNTIME_FAILURE;
	CHECK(create_with(GL_RGBA8) == XR_ERROR_RUNTIME_FAILURE);
	begin();
	CHECK(gl_disable_calls == 0);

	// An RGBA8 swapchain becomes an sRGB one, and from then on GL must not
	// encode what the app writes, which it already encoded itself.
	rt_create_result = XR_SUCCESS;
	CHECK(create_with(GL_RGBA8) == XR_SUCCESS && rt_created_format == GL_SRGB8_ALPHA8);
	begin();
	CHECK(gl_disable_calls == 1 && gl_disabled[0] == GL_FRAMEBUFFER_SRGB_EXT);
	begin();
	CHECK(gl_disable_calls == 2);

	// Without a context, or without the extension, glDisable would only
	// raise a GL error in the app.
	gl_context = NULL;
	begin();
	CHECK(gl_disable_calls == 2);
	gl_context = &gl_extensions;
	gl_extensions = "GL_EXT_sRGB GL_OES_depth24";
	begin();
	CHECK(gl_disable_calls == 2);
	gl_context = &gl_context;
	gl_extensions = "GL_EXT_sRGB_write_control";
	begin();
	CHECK(gl_disable_calls == 3);
}

static void test_depth_swapchains_the_runtime_cannot_create(void) {
	const int64_t steamvr[] = {0x8C41, GL_SRGB8_ALPHA8, GL_DEPTH_COMPONENT16,
				   GL_DEPTH_COMPONENT24, GL_DEPTH_COMPONENT32F};
	int disables = gl_disable_calls;

	rt_create_result = XR_SUCCESS;
	set_runtime_formats(5, steamvr);

	// A runtime that can create them is asked once and gets what the app chose.
	CHECK(create_with(GL_DEPTH_COMPONENT16) == XR_SUCCESS);
	CHECK(rt_created_format == GL_DEPTH_COMPONENT16 && rt_create_calls == 1);
	CHECK(create_with(GL_DEPTH_COMPONENT24) == XR_SUCCESS);
	CHECK(rt_created_format == GL_DEPTH_COMPONENT24 && rt_create_calls == 1);

	// Other failures, and other formats' failures, are the app's to see.
	rt_create_result = XR_ERROR_LIMIT_REACHED;
	CHECK(create_with(GL_DEPTH_COMPONENT16) == XR_ERROR_LIMIT_REACHED && rt_create_calls == 1);
	rt_create_result = XR_ERROR_RUNTIME_FAILURE;
	CHECK(create_with(GL_SRGB8_ALPHA8) == XR_ERROR_RUNTIME_FAILURE && rt_create_calls == 1);
	CHECK(create_with(GL_DEPTH_COMPONENT32F) == XR_ERROR_RUNTIME_FAILURE && rt_create_calls == 1);
	rt_create_result = XR_SUCCESS;

	// Nothing to fall back on without a float depth format.
	rt_small_depth_fails = 1;
	set_runtime_formats(4, steamvr);
	CHECK(create_with(GL_DEPTH_COMPONENT16) == XR_ERROR_RUNTIME_FAILURE);
	CHECK(rt_created_format == GL_DEPTH_COMPONENT16 && rt_create_calls == 1);

	// SteamVR on Mesa: the float format is created in its place...
	set_runtime_formats(5, steamvr);
	CHECK(create_with(GL_DEPTH_COMPONENT16) == XR_SUCCESS);
	CHECK(rt_created_format == GL_DEPTH_COMPONENT32F && rt_create_calls == 2);
	// ...and from then on without failing first.
	CHECK(create_with(GL_DEPTH_COMPONENT24) == XR_SUCCESS);
	CHECK(rt_created_format == GL_DEPTH_COMPONENT32F && rt_create_calls == 1);
	CHECK(create_with(GL_DEPTH_COMPONENT16) == XR_SUCCESS);
	CHECK(rt_created_format == GL_DEPTH_COMPONENT32F && rt_create_calls == 1);
	CHECK(create_with(GL_DEPTH_COMPONENT32F) == XR_SUCCESS && rt_create_calls == 1);
	CHECK(create_with(GL_SRGB8_ALPHA8) == XR_SUCCESS && rt_created_format == GL_SRGB8_ALPHA8);
	rt_small_depth_fails = 0;

	// Depth has nothing to do with sRGB encoding.
	CHECK(gl_disable_calls == disables);
}

static void test_blend_mode_override(void) {
	XrFrameEndInfo info = {XR_TYPE_FRAME_END_INFO};
	const struct {
		const char *property;
		XrEnvironmentBlendMode sent, seen;
	} cases[] = {
		{"", XR_ENVIRONMENT_BLEND_MODE_OPAQUE, XR_ENVIRONMENT_BLEND_MODE_OPAQUE},
		{"alpha_blend", XR_ENVIRONMENT_BLEND_MODE_OPAQUE, XR_ENVIRONMENT_BLEND_MODE_ALPHA_BLEND},
		{"additive", XR_ENVIRONMENT_BLEND_MODE_OPAQUE, XR_ENVIRONMENT_BLEND_MODE_ADDITIVE},
		{"opaque", XR_ENVIRONMENT_BLEND_MODE_ALPHA_BLEND, XR_ENVIRONMENT_BLEND_MODE_OPAQUE},
		{"nonsense", XR_ENVIRONMENT_BLEND_MODE_ALPHA_BLEND, XR_ENVIRONMENT_BLEND_MODE_ALPHA_BLEND},
	};
	size_t i;

	for (i = 0; i < sizeof cases / sizeof *cases; i++) {
		strcpy(blend_property, cases[i].property);
		info.environmentBlendMode = cases[i].sent;
		CHECK(app_end_frame(SESSION, &info) == XR_SUCCESS);
		CHECK(rt_blend_seen == cases[i].seen);
		// The app's own struct is never modified.
		CHECK(info.environmentBlendMode == cases[i].sent);
	}
	blend_property[0] = 0;
	CHECK(rt_end_frames == (int)(sizeof cases / sizeof *cases));
}

static void test_drop_layers(void) {
	XrCompositionLayerBaseHeader layer = {XR_TYPE_COMPOSITION_LAYER_PROJECTION};
	const XrCompositionLayerBaseHeader *layers[1] = {&layer};
	XrFrameEndInfo info = {XR_TYPE_FRAME_END_INFO};

	info.layerCount = 1;
	info.layers = layers;
	info.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
	blend_property[0] = 0;
	strcpy(drop_property, "0");
	CHECK(app_end_frame(SESSION, &info) == XR_SUCCESS && rt_layers_seen == 1);
	strcpy(drop_property, "1");
	CHECK(app_end_frame(SESSION, &info) == XR_SUCCESS && rt_layers_seen == 0);
	CHECK(rt_blend_seen == XR_ENVIRONMENT_BLEND_MODE_OPAQUE);
	strcpy(blend_property, "alpha_blend");
	CHECK(app_end_frame(SESSION, &info) == XR_SUCCESS && rt_layers_seen == 0);
	CHECK(rt_blend_seen == XR_ENVIRONMENT_BLEND_MODE_ALPHA_BLEND);
	CHECK(info.layerCount == 1 && info.layers == layers); // The app's own struct is untouched.
	drop_property[0] = 0;
	blend_property[0] = 0;
}

// What the app sees as the recommended size of the first view for a property value.
static uint32_t recommended_with(const char *property, uint32_t runtime_max) {
	XrViewConfigurationView views[2] = {{XR_TYPE_VIEW_CONFIGURATION_VIEW},
					    {XR_TYPE_VIEW_CONFIGURATION_VIEW}};
	uint32_t count = 0;

	strcpy(scale_property, property);
	rt_max_size = runtime_max;
	CHECK(app_enumerate_views((XrInstance)0x1157, 1, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 2,
				  &count, views) == XR_SUCCESS);
	CHECK(count == 2);
	CHECK(views[0].recommendedImageRectWidth == views[1].recommendedImageRectWidth);
	CHECK(views[0].recommendedImageRectHeight == views[0].recommendedImageRectWidth);
	CHECK(views[0].maxImageRectWidth == runtime_max); // only the recommendation changes
	return views[0].recommendedImageRectWidth;
}

static void test_render_scale(void) {
	XrViewConfigurationView views[2] = {{XR_TYPE_VIEW_CONFIGURATION_VIEW},
					    {XR_TYPE_VIEW_CONFIGURATION_VIEW}};
	uint32_t count = 0, calls;

	CHECK(recommended_with("", 4320) == 1728); // unset: untouched
	CHECK(recommended_with("1.25", 4320) == 2160); // the Frame's panel
	CHECK(recommended_with("1.0", 4320) == 1728);
	CHECK(recommended_with("1", 4320) == 1728);
	CHECK(recommended_with("2", 4320) == 3456);
	CHECK(recommended_with("1.5", 4320) == 2592);
	CHECK(recommended_with("1.1", 4320) == 1901); // one decimal is a tenth, not a hundredth
	CHECK(recommended_with("1.25", 2000) == 2000); // never above the runtime's maximum
	CHECK(recommended_with("1.25", 1700) == 1728); // and never smaller than it recommended
	// Not a plain factor from 1.0 to 2.0: ignored.
	CHECK(recommended_with("abc", 4320) == 1728);
	CHECK(recommended_with("0.5", 4320) == 1728);
	CHECK(recommended_with("3", 4320) == 1728);
	CHECK(recommended_with("1.25x", 4320) == 1728);
	CHECK(recommended_with(".5", 4320) == 1728);
	CHECK(recommended_with("-1.25", 4320) == 1728);
	CHECK(recommended_with("100", 4320) == 1728);

	// Asking only for the count, or with too little room, is passed straight down.
	strcpy(scale_property, "1.25");
	rt_max_size = 4320;
	calls = rt_view_calls;
	CHECK(app_enumerate_views((XrInstance)0x1157, 1, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 0,
				  &count, NULL) == XR_SUCCESS);
	CHECK(count == 2 && rt_view_calls == calls + 1);
	CHECK(app_enumerate_views((XrInstance)0x1157, 1, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 1,
				  &count, views) == XR_ERROR_SIZE_INSUFFICIENT);
	scale_property[0] = 0;
}

int main(void) {
	test_negotiation();
	test_nothing_to_offer_before_an_instance_exists();
	test_instance_creation_goes_down_the_chain();
	if (!app_enumerate || !app_create || !app_begin_frame || !app_end_frame || !app_enumerate_views) {
		printf("FAIL: the layer does not hook what it must\n");
		return 1;
	}
	test_rgba8_is_offered_when_the_runtime_only_has_srgb();
	test_other_format_lists_are_left_alone();
	test_depth_swapchains_the_runtime_cannot_create();
	test_swapchains_and_srgb_encoding();
	test_blend_mode_override();
	test_drop_layers();
	test_render_scale();
	printf(failures ? "%d check(s) failed\n" : "gles_layer: all checks passed\n", failures);
	return failures != 0;
}
