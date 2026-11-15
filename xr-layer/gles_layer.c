// OpenXR API layer: swapchain formats OpenGL ES apps ask SteamVR for and
// do not get.
//
// Color. SteamVR's OpenGL ES swapchains are GL_SRGB8_ALPHA8; it does not
// list GL_RGBA8. Apps that insist on GL_RGBA8 (Wolvic's generic build) give
// up before drawing anything. This layer adds GL_RGBA8 to the list such a
// runtime reports and creates those swapchains as GL_SRGB8_ALPHA8.
//
// An app that asks for RGBA8 writes colors that are already sRGB-encoded,
// and GL would encode them a second time on the way into an sRGB texture.
// So once a swapchain has been swapped, the layer turns GL's encoding off
// (GL_EXT_sRGB_write_control) at the start of every frame; the bytes the app
// writes then reach the compositor unchanged and are read as sRGB, which is
// what the app meant.
//
// Depth. SteamVR lists GL_DEPTH_COMPONENT16 and 24 but cannot create them:
// its compositor refuses to share a depth image with an OpenGL app, and the
// textures vrclient then makes itself are all filled as GL_FLOAT, which
// OpenGL ES only allows for GL_DEPTH_COMPONENT32F. Apps that pick the first
// depth format listed (Khronos hello_xr) fail to start. When that happens
// the layer creates the swapchain as GL_DEPTH_COMPONENT32F.
//
// Built without the NDK (tools/build-android-libs.sh), so the few functions it
// needs from Android are declared here instead of included.
#define XR_NO_PROTOTYPES
#include <openxr/openxr.h>
#include <openxr/openxr_loader_negotiation.h>

#define LAYER_NAME "XR_APILAYER_WGAPPS_gles_formats"

#define GL_RGBA8 0x8058
#define GL_SRGB8_ALPHA8 0x8C43
#define GL_DEPTH_COMPONENT16 0x81A5
#define GL_DEPTH_COMPONENT24 0x81A6
#define GL_DEPTH_COMPONENT32F 0x8CAC
#define GL_EXTENSIONS 0x1F03
#define GL_FRAMEBUFFER_SRGB_EXT 0x8DB9
#define ANDROID_LOG_INFO 4

int __android_log_print(int priority, const char *tag, const char *format, ...)
	__attribute__((format(printf, 3, 4)));
void *eglGetCurrentContext(void);
const unsigned char *glGetString(unsigned name);
void glDisable(unsigned cap);
int strcmp(const char *a, const char *b);
char *strstr(const char *haystack, const char *needle);
int snprintf(char *buffer, size_t size, const char *format, ...)
	__attribute__((format(printf, 3, 4)));

#define LOG(...) __android_log_print(ANDROID_LOG_INFO, "wgapps-xr-gles", __VA_ARGS__)

// An app has one instance, so the functions below this layer are kept once.
static PFN_xrGetInstanceProcAddr next_get_instance_proc_addr;
static XrResult (XRAPI_PTR *next_enumerate_swapchain_formats)(XrSession, uint32_t, uint32_t *,
							      int64_t *);
static XrResult (XRAPI_PTR *next_create_swapchain)(XrSession, const XrSwapchainCreateInfo *,
						   XrSwapchain *);
static XrResult (XRAPI_PTR *next_begin_frame)(XrSession, const XrFrameBeginInfo *);

// Set once a swapchain the app thinks is RGBA8 exists.
static int swapped;
// Set once the runtime failed to create a 16- or 24-bit depth swapchain and
// created a float one in its place.
static int float_depth;

// What the runtime's format list means for this layer. Only an OpenGL (ES)
// session can have either: no Vulkan format has these values.
enum {
	LACKS_RGBA8 = 1, // Has GL_SRGB8_ALPHA8 but not GL_RGBA8.
	HAS_FLOAT_DEPTH = 2, // Has GL_DEPTH_COMPONENT32F.
};

static int runtime_formats(XrSession session) {
	static int logged;
	int64_t formats[64];
	uint32_t count = 0, i;
	int rgba8 = 0, srgb = 0, float_depth_listed = 0;

	if (XR_FAILED(next_enumerate_swapchain_formats(session, 0, &count, NULL)) || count == 0 ||
	    count > 64 ||
	    XR_FAILED(next_enumerate_swapchain_formats(session, count, &count, formats)))
		return 0;
	for (i = 0; i < count; i++) {
		rgba8 |= formats[i] == GL_RGBA8;
		srgb |= formats[i] == GL_SRGB8_ALPHA8;
		float_depth_listed |= formats[i] == GL_DEPTH_COMPONENT32F;
	}
	if (!logged) {
		// " 0x" and at most 16 digits each.
		char list[64 * 19 + 1] = "";
		size_t used = 0;

		logged = 1;
		for (i = 0; i < count; i++)
			used += (size_t)snprintf(list + used, sizeof list - used, " 0x%llX",
						 (unsigned long long)formats[i]);
		LOG("runtime swapchain formats:%s%s", list,
		    srgb && !rgba8 ? "; offering GL_RGBA8 as GL_SRGB8_ALPHA8" : "");
	}
	return (srgb && !rgba8 ? LACKS_RGBA8 : 0) | (float_depth_listed ? HAS_FLOAT_DEPTH : 0);
}

static XRAPI_ATTR XrResult XRAPI_CALL enumerate_swapchain_formats(XrSession session,
								   uint32_t capacity,
								   uint32_t *count,
								   int64_t *formats) {
	XrResult result;

	if (!count || !(runtime_formats(session) & LACKS_RGBA8))
		return next_enumerate_swapchain_formats(session, capacity, count, formats);
	// GL_RGBA8 goes last: the list is in the runtime's order of preference.
	result = next_enumerate_swapchain_formats(session, capacity ? capacity - 1 : 0, count,
						  formats);
	if (result != XR_SUCCESS && result != XR_ERROR_SIZE_INSUFFICIENT) return result;
	*count += 1;
	if (capacity == 0) return result;
	if (capacity < *count) return XR_ERROR_SIZE_INSUFFICIENT;
	formats[*count - 1] = GL_RGBA8;
	return result;
}

static XRAPI_ATTR XrResult XRAPI_CALL create_swapchain(XrSession session,
							const XrSwapchainCreateInfo *info,
							XrSwapchain *swapchain) {
	XrSwapchainCreateInfo other;
	XrResult result;

	if (!info) return next_create_swapchain(session, info, swapchain);
	other = *info;
	if (info->format == GL_RGBA8 && (runtime_formats(session) & LACKS_RGBA8)) {
		other.format = GL_SRGB8_ALPHA8;
		result = next_create_swapchain(session, &other, swapchain);
		if (XR_SUCCEEDED(result)) {
			swapped = 1;
			LOG("GL_RGBA8 swapchain %ux%u created as GL_SRGB8_ALPHA8", info->width,
			    info->height);
		}
		return result;
	}
	if (info->format != GL_DEPTH_COMPONENT16 && info->format != GL_DEPTH_COMPONENT24)
		return next_create_swapchain(session, info, swapchain);
	// The app attaches whatever texture it gets, so where the runtime cannot
	// create these (see the top of the file) a float one serves as well.
	if (!float_depth) {
		result = next_create_swapchain(session, info, swapchain);
		if (result != XR_ERROR_RUNTIME_FAILURE ||
		    !(runtime_formats(session) & HAS_FLOAT_DEPTH))
			return result;
	}
	other.format = GL_DEPTH_COMPONENT32F;
	result = next_create_swapchain(session, &other, swapchain);
	if (XR_SUCCEEDED(result)) {
		float_depth = 1;
		LOG("depth swapchain 0x%llX %ux%u created as GL_DEPTH_COMPONENT32F",
		    (unsigned long long)info->format, info->width, info->height);
	}
	return result;
}

static void stop_srgb_encoding(void) {
	static void *checked;
	static int can;
	void *context = eglGetCurrentContext();

	if (!context) return;
	if (context != checked) {
		const char *extensions = (const char *)glGetString(GL_EXTENSIONS);

		can = extensions && strstr(extensions, "GL_EXT_sRGB_write_control");
		checked = context;
		LOG("GL_EXT_sRGB_write_control %s", can ? "present: sRGB encoding off"
							: "missing: colors will be too bright");
	}
	// Without the extension the enum is an error the app would find.
	if (can) glDisable(GL_FRAMEBUFFER_SRGB_EXT);
}

static XRAPI_ATTR XrResult XRAPI_CALL begin_frame(XrSession session, const XrFrameBeginInfo *info) {
	if (swapped) stop_srgb_encoding();
	return next_begin_frame(session, info);
}

static XRAPI_ATTR XrResult XRAPI_CALL get_instance_proc_addr(XrInstance instance, const char *name,
							      PFN_xrVoidFunction *function) {
	XrResult result;

	// Android loaders ask every layer for xrInitializeLoaderKHR before any
	// instance exists. This layer has nothing that works without one.
	if (!next_get_instance_proc_addr) {
		if (function) *function = NULL;
		return XR_ERROR_FUNCTION_UNSUPPORTED;
	}
	result = next_get_instance_proc_addr(instance, name, function);
	if (XR_FAILED(result) || !name) return result;
	if (!strcmp(name, "xrEnumerateSwapchainFormats"))
		*function = (PFN_xrVoidFunction)enumerate_swapchain_formats;
	else if (!strcmp(name, "xrCreateSwapchain"))
		*function = (PFN_xrVoidFunction)create_swapchain;
	else if (!strcmp(name, "xrBeginFrame"))
		*function = (PFN_xrVoidFunction)begin_frame;
	return result;
}

static XRAPI_ATTR XrResult XRAPI_CALL create_api_layer_instance(const XrInstanceCreateInfo *info,
								 const XrApiLayerCreateInfo *layer_info,
								 XrInstance *instance) {
	XrApiLayerCreateInfo below;
	PFN_xrGetInstanceProcAddr get;
	XrResult result;

	if (!layer_info || !layer_info->nextInfo || !layer_info->nextInfo->nextGetInstanceProcAddr ||
	    !layer_info->nextInfo->nextCreateApiLayerInstance)
		return XR_ERROR_INITIALIZATION_FAILED;
	below = *layer_info;
	below.nextInfo = layer_info->nextInfo->next;
	result = layer_info->nextInfo->nextCreateApiLayerInstance(info, &below, instance);
	if (XR_FAILED(result)) return result;

	get = layer_info->nextInfo->nextGetInstanceProcAddr;
	if (XR_FAILED(get(*instance, "xrEnumerateSwapchainFormats",
			  (PFN_xrVoidFunction *)&next_enumerate_swapchain_formats)) ||
	    XR_FAILED(get(*instance, "xrCreateSwapchain",
			  (PFN_xrVoidFunction *)&next_create_swapchain)) ||
	    XR_FAILED(get(*instance, "xrBeginFrame", (PFN_xrVoidFunction *)&next_begin_frame)))
		return XR_ERROR_INITIALIZATION_FAILED;
	next_get_instance_proc_addr = get;
	return result;
}

__attribute__((visibility("default"))) XRAPI_ATTR XrResult XRAPI_CALL
xrNegotiateLoaderApiLayerInterface(const XrNegotiateLoaderInfo *loader, const char *layer_name,
				   XrNegotiateApiLayerRequest *request) {
	if (!loader || !request || !layer_name || strcmp(layer_name, LAYER_NAME) ||
	    loader->structType != XR_LOADER_INTERFACE_STRUCT_LOADER_INFO ||
	    loader->structVersion != XR_LOADER_INFO_STRUCT_VERSION ||
	    loader->structSize != sizeof *loader ||
	    request->structType != XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST ||
	    request->structVersion != XR_API_LAYER_INFO_STRUCT_VERSION ||
	    request->structSize != sizeof *request ||
	    loader->minInterfaceVersion > XR_CURRENT_LOADER_API_LAYER_VERSION ||
	    loader->maxInterfaceVersion < XR_CURRENT_LOADER_API_LAYER_VERSION ||
	    loader->minApiVersion > XR_API_VERSION_1_0 || loader->maxApiVersion < XR_API_VERSION_1_0)
		return XR_ERROR_INITIALIZATION_FAILED;
	request->layerInterfaceVersion = XR_CURRENT_LOADER_API_LAYER_VERSION;
	// The hooked functions have not changed since 1.0.
	request->layerApiVersion = XR_API_VERSION_1_0;
	request->getInstanceProcAddr = get_instance_proc_addr;
	request->createApiLayerInstance = create_api_layer_instance;
	return XR_SUCCESS;
}
