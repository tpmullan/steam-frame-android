// The VR shell's scene (V1): an OpenXR session with a GLES swapchain, and the app grid on a quad
// in front of the user. The grid's pixels come from Java (VrShellActivity.gridPixels) because
// text drawing is already there; this file only owns the OpenXR session and the upload.
//
// Runs as the native thread of a NativeActivity (android_native_app_glue). Logs lines starting
// "WGSHELL" for `wgapps` and the tests on the Frame: session states, "quad shown", frames.
#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <android/log.h>
#include <android_native_app_glue.h>
#include <jni.h>
#include <string.h>

#define XR_USE_PLATFORM_ANDROID
#define XR_USE_GRAPHICS_API_OPENGL_ES
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>

#define TAG "WGSHELL"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

#define GRID_W 1920
#define GRID_H 1080
#define MAX_IMAGES 8
#define GL_SRGB8_ALPHA8_FMT 0x8C43
#define GL_RGBA8_FMT 0x8058

#define CHECK(call)                                                                  \
	do {                                                                         \
		XrResult r_ = (call);                                                \
		if (XR_FAILED(r_)) {                                                 \
			LOGE("%s failed: %d", #call, (int)r_);                       \
			return 0;                                                    \
		}                                                                    \
	} while (0)

struct shell {
	struct android_app *app;
	XrInstance instance;
	XrSystemId system;
	XrSession session;
	XrSpace space;
	XrSpace stage;
	XrSwapchain swapchain;
	XrSwapchainImageOpenGLESKHR images[MAX_IMAGES];
	int version[MAX_IMAGES]; // Content version uploaded to each image.
	uint32_t image_count;
	int running;
	int exit_requested;
	int content_version;
	EGLDisplay display;
	EGLContext context;
	EGLSurface surface;
	// Controllers: an aim pose and a select (trigger) click per hand.
	XrActionSet actions;
	XrAction aim, select;
	XrPath hand[2];
	XrSpace aim_space[2];
	int was_selecting[2];
	int hover; // 0 = nothing; changes bump content_version.
	// The environment: one colour swapchain per eye, cleared to the shell's background and
	// submitted as a projection layer. A scene app SteamVR gives input focus to submits one; a
	// quad alone looks like an overlay and the session stays VISIBLE.
	XrSwapchain eye_swapchain[2];
	XrSwapchainImageOpenGLESKHR eye_images[2][MAX_IMAGES];
	uint32_t eye_image_count[2];
	uint32_t eye_width[2], eye_height[2];
	GLuint fbo;
};

#define QUAD_Z -1.7f
#define QUAD_WIDTH 1.8f

static int has_extension(const char *name) {
	uint32_t count = 0, i;
	XrExtensionProperties props[64];

	if (XR_FAILED(xrEnumerateInstanceExtensionProperties(NULL, 0, &count, NULL)) || count > 64) return 0;
	for (i = 0; i < count; i++) props[i] = (XrExtensionProperties){XR_TYPE_EXTENSION_PROPERTIES};
	if (XR_FAILED(xrEnumerateInstanceExtensionProperties(NULL, count, &count, props))) return 0;
	for (i = 0; i < count; i++)
		if (!strcmp(props[i].extensionName, name)) return 1;
	return 0;
}

static int init_egl(struct shell *s) {
	const EGLint config_attribs[] = {EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_RED_SIZE, 8,
					 EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
					 EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_NONE};
	const EGLint context_attribs[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
	const EGLint pbuffer_attribs[] = {EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE};
	EGLConfig config;
	EGLint count = 0;

	s->display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
	if (!eglInitialize(s->display, NULL, NULL)) {
		LOGE("eglInitialize failed");
		return 0;
	}
	if (!eglChooseConfig(s->display, config_attribs, &config, 1, &count) || count < 1) {
		LOGE("no EGL config");
		return 0;
	}
	s->context = eglCreateContext(s->display, config, EGL_NO_CONTEXT, context_attribs);
	s->surface = eglCreatePbufferSurface(s->display, config, pbuffer_attribs);
	if (s->context == EGL_NO_CONTEXT || s->surface == EGL_NO_SURFACE ||
	    !eglMakeCurrent(s->display, s->surface, s->surface, s->context)) {
		LOGE("EGL context failed");
		return 0;
	}
	return 1;
}

static int create_session(struct shell *s) {
	JavaVM *vm = s->app->activity->vm;
	jobject activity = s->app->activity->clazz;
	PFN_xrInitializeLoaderKHR init_loader = NULL;
	const char *extensions[2];
	uint32_t extension_count = 0;
	XrInstanceCreateInfoAndroidKHR android_info = {XR_TYPE_INSTANCE_CREATE_INFO_ANDROID_KHR};
	XrInstanceCreateInfo create = {XR_TYPE_INSTANCE_CREATE_INFO};
	XrSystemGetInfo system_info = {XR_TYPE_SYSTEM_GET_INFO};
	XrGraphicsRequirementsOpenGLESKHR requirements = {XR_TYPE_GRAPHICS_REQUIREMENTS_OPENGL_ES_KHR};
	PFN_xrGetOpenGLESGraphicsRequirementsKHR get_requirements = NULL;
	XrGraphicsBindingOpenGLESAndroidKHR binding = {XR_TYPE_GRAPHICS_BINDING_OPENGL_ES_ANDROID_KHR};
	XrSessionCreateInfo session_info = {XR_TYPE_SESSION_CREATE_INFO};
	XrReferenceSpaceCreateInfo space_info = {XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
	EGLConfig config;
	EGLint count = 0;
	const EGLint config_attribs[] = {EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_RED_SIZE, 8,
					 EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
					 EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_NONE};

	if (XR_SUCCEEDED(xrGetInstanceProcAddr(XR_NULL_HANDLE, "xrInitializeLoaderKHR",
					      (PFN_xrVoidFunction *)&init_loader)) && init_loader) {
		XrLoaderInitInfoAndroidKHR info = {XR_TYPE_LOADER_INIT_INFO_ANDROID_KHR};
		info.applicationVM = vm;
		info.applicationContext = activity;
		CHECK(init_loader((XrLoaderInitInfoBaseHeaderKHR *)&info));
	}
	if (!has_extension(XR_KHR_OPENGL_ES_ENABLE_EXTENSION_NAME)) {
		LOGE("the runtime has no %s", XR_KHR_OPENGL_ES_ENABLE_EXTENSION_NAME);
		return 0;
	}
	extensions[extension_count++] = XR_KHR_OPENGL_ES_ENABLE_EXTENSION_NAME;
	if (has_extension(XR_KHR_ANDROID_CREATE_INSTANCE_EXTENSION_NAME)) {
		extensions[extension_count++] = XR_KHR_ANDROID_CREATE_INSTANCE_EXTENSION_NAME;
		android_info.applicationVM = vm;
		android_info.applicationActivity = activity;
		create.next = &android_info;
	}
	strncpy(create.applicationInfo.applicationName, "Wgapps shell", XR_MAX_APPLICATION_NAME_SIZE - 1);
	create.applicationInfo.applicationVersion = 1;
	strncpy(create.applicationInfo.engineName, "wgapps", XR_MAX_ENGINE_NAME_SIZE - 1);
	create.applicationInfo.apiVersion = XR_API_VERSION_1_0;
	create.enabledExtensionCount = extension_count;
	create.enabledExtensionNames = extensions;
	CHECK(xrCreateInstance(&create, &s->instance));

	system_info.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
	CHECK(xrGetSystem(s->instance, &system_info, &s->system));
	CHECK(xrGetInstanceProcAddr(s->instance, "xrGetOpenGLESGraphicsRequirementsKHR",
				    (PFN_xrVoidFunction *)&get_requirements));
	CHECK(get_requirements(s->instance, s->system, &requirements));

	if (!init_egl(s)) return 0;
	eglChooseConfig(s->display, config_attribs, &config, 1, &count);
	binding.display = s->display;
	binding.config = config;
	binding.context = s->context;
	session_info.next = &binding;
	session_info.systemId = s->system;
	CHECK(xrCreateSession(s->instance, &session_info, &s->session));

	space_info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
	space_info.poseInReferenceSpace.orientation.w = 1.0f;
	CHECK(xrCreateReferenceSpace(s->session, &space_info, &s->space));
	space_info.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_STAGE;
	if (XR_FAILED(xrCreateReferenceSpace(s->session, &space_info, &s->stage))) s->stage = XR_NULL_HANDLE;
	return 1;
}

static int create_actions(struct shell *s) {
	XrActionSetCreateInfo set_info = {XR_TYPE_ACTION_SET_CREATE_INFO};
	XrActionCreateInfo action_info = {XR_TYPE_ACTION_CREATE_INFO};
	XrPath profile, aim_path[2], select_path[2];
	XrActionSuggestedBinding bindings[4];
	XrInteractionProfileSuggestedBinding suggested = {XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING};
	XrSessionActionSetsAttachInfo attach = {XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO};
	XrActionSpaceCreateInfo space_info = {XR_TYPE_ACTION_SPACE_CREATE_INFO};
	int i;

	strcpy(set_info.actionSetName, "shell");
	strcpy(set_info.localizedActionSetName, "Shell");
	CHECK(xrCreateActionSet(s->instance, &set_info, &s->actions));
	CHECK(xrStringToPath(s->instance, "/user/hand/left", &s->hand[0]));
	CHECK(xrStringToPath(s->instance, "/user/hand/right", &s->hand[1]));

	action_info.countSubactionPaths = 2;
	action_info.subactionPaths = s->hand;
	action_info.actionType = XR_ACTION_TYPE_POSE_INPUT;
	strcpy(action_info.actionName, "aim");
	strcpy(action_info.localizedActionName, "Aim");
	CHECK(xrCreateAction(s->actions, &action_info, &s->aim));
	action_info.actionType = XR_ACTION_TYPE_BOOLEAN_INPUT;
	strcpy(action_info.actionName, "select");
	strcpy(action_info.localizedActionName, "Select");
	CHECK(xrCreateAction(s->actions, &action_info, &s->select));

	CHECK(xrStringToPath(s->instance, "/user/hand/left/input/aim/pose", &aim_path[0]));
	CHECK(xrStringToPath(s->instance, "/user/hand/right/input/aim/pose", &aim_path[1]));
	CHECK(xrStringToPath(s->instance, "/user/hand/left/input/select/click", &select_path[0]));
	CHECK(xrStringToPath(s->instance, "/user/hand/right/input/select/click", &select_path[1]));
	CHECK(xrStringToPath(s->instance, "/interaction_profiles/khr/simple_controller", &profile));
	for (i = 0; i < 2; i++) {
		bindings[i * 2] = (XrActionSuggestedBinding){s->aim, aim_path[i]};
		bindings[i * 2 + 1] = (XrActionSuggestedBinding){s->select, select_path[i]};
	}
	suggested.interactionProfile = profile;
	suggested.suggestedBindings = bindings;
	suggested.countSuggestedBindings = 4;
	CHECK(xrSuggestInteractionProfileBindings(s->instance, &suggested));
	// The Frame's controllers present themselves to OpenXR apps as Index controllers
	// (frame_controller_remapping.json in SteamVR's driver), so bind that profile too.
	{
		XrPath index_profile, trigger_path[2];

		CHECK(xrStringToPath(s->instance, "/user/hand/left/input/trigger/click", &trigger_path[0]));
		CHECK(xrStringToPath(s->instance, "/user/hand/right/input/trigger/click", &trigger_path[1]));
		CHECK(xrStringToPath(s->instance, "/interaction_profiles/valve/index_controller", &index_profile));
		for (i = 0; i < 2; i++) {
			bindings[i * 2] = (XrActionSuggestedBinding){s->aim, aim_path[i]};
			bindings[i * 2 + 1] = (XrActionSuggestedBinding){s->select, trigger_path[i]};
		}
		suggested.interactionProfile = index_profile;
		suggested.suggestedBindings = bindings;
		suggested.countSuggestedBindings = 4;
		CHECK(xrSuggestInteractionProfileBindings(s->instance, &suggested));
	}

	for (i = 0; i < 2; i++) {
		space_info.action = s->aim;
		space_info.subactionPath = s->hand[i];
		space_info.poseInActionSpace.orientation.w = 1.0f;
		CHECK(xrCreateActionSpace(s->session, &space_info, &s->aim_space[i]));
	}
	attach.countActionSets = 1;
	attach.actionSets = &s->actions;
	CHECK(xrAttachSessionActionSets(s->session, &attach));
	return 1;
}

// Where the ray of hand H meets the panel, in the panel's pixels. 0 when it misses.
static int ray_hit(struct shell *s, int h, XrTime time, int *px, int *py) {
	XrSpaceLocation location = {XR_TYPE_SPACE_LOCATION};
	XrQuaternionf q;
	float dx, dy, dz, t, x, y, height = QUAD_WIDTH * GRID_H / GRID_W;
	const XrSpaceLocationFlags needed = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;

	static int tick[2];
	XrResult located = xrLocateSpace(s->aim_space[h], s->space, time, &location);

	if (tick[h] % 150 == 0) {
		XrActionStateGetInfo get = {XR_TYPE_ACTION_STATE_GET_INFO};
		XrActionStatePose pose_state = {XR_TYPE_ACTION_STATE_POSE};
		XrSpaceLocation in_stage = {XR_TYPE_SPACE_LOCATION};
		XrSpaceLocation in_local_head = {XR_TYPE_SPACE_LOCATION};

		get.action = s->aim;
		get.subactionPath = s->hand[h];
		xrGetActionStatePose(s->session, &get, &pose_state);
		if (s->stage) xrLocateSpace(s->aim_space[h], s->stage, time, &in_stage);
		xrLocateSpace(s->space, s->space, time, &in_local_head);
		LOGI("hand %d: aim pose active=%d, flags in STAGE=0x%x, LOCAL in LOCAL=0x%x", h,
		     (int)pose_state.isActive, (unsigned)in_stage.locationFlags, (unsigned)in_local_head.locationFlags);
	}
	if (++tick[h] % 150 == 1)
		LOGI("hand %d aim: result=%d flags=0x%x pos=(%.2f,%.2f,%.2f) q=(%.2f,%.2f,%.2f,%.2f)", h, (int)located,
		     (unsigned)location.locationFlags, location.pose.position.x, location.pose.position.y,
		     location.pose.position.z, location.pose.orientation.x, location.pose.orientation.y,
		     location.pose.orientation.z, location.pose.orientation.w);
	if (XR_FAILED(located) || (location.locationFlags & needed) != needed) return 0;
	q = location.pose.orientation;
	// The aim direction is -Z of the pose: rotate (0, 0, -1) by the quaternion.
	dx = -2.0f * (q.x * q.z + q.w * q.y);
	dy = -2.0f * (q.y * q.z - q.w * q.x);
	dz = -(1.0f - 2.0f * (q.x * q.x + q.y * q.y));
	if (dz > -0.0001f) return 0; // Pointing away from the panel.
	t = (QUAD_Z - location.pose.position.z) / dz;
	if (t < 0) return 0;
	x = location.pose.position.x + dx * t;
	y = location.pose.position.y + dy * t;
	if (x < -QUAD_WIDTH / 2 || x > QUAD_WIDTH / 2 || y < -height / 2 || y > height / 2) return 0;
	*px = (int)((x / QUAD_WIDTH + 0.5f) * GRID_W);
	*py = (int)((0.5f - y / height) * GRID_H);
	return 1;
}

static int java_call_int2(struct shell *s, const char *name, const char *signature, int a, int b, int *result) {
	JNIEnv *env;
	JavaVM *vm = s->app->activity->vm;
	jclass cls;
	jmethodID method;

	if ((*vm)->AttachCurrentThread(vm, &env, NULL) != JNI_OK) return 0;
	cls = (*env)->GetObjectClass(env, s->app->activity->clazz);
	method = (*env)->GetStaticMethodID(env, cls, name, signature);
	if (!method) {
		(*env)->ExceptionClear(env);
		return 0;
	}
	if (result) *result = (*env)->CallStaticIntMethod(env, cls, method, a, b);
	else (*env)->CallStaticVoidMethod(env, cls, method, a, b);
	return 1;
}

// Pointing and clicking: hover changes redraw the panel, a trigger press launches what is under it.
static void handle_input(struct shell *s, XrTime time) {
	XrActiveActionSet active = {s->actions, XR_NULL_PATH};
	XrActionsSyncInfo sync = {XR_TYPE_ACTIONS_SYNC_INFO};
	int h, px = -1, py = -1, hit_any = 0;

	static int logged_profile, last_hit = -1, logged_active[2];

	sync.countActiveActionSets = 1;
	sync.activeActionSets = &active;
	if (XR_FAILED(xrSyncActions(s->session, &sync))) return;
	if (!logged_profile) {
		XrInteractionProfileState profile = {XR_TYPE_INTERACTION_PROFILE_STATE};
		char name[128] = "(none)";
		uint32_t length = 0;

		if (XR_SUCCEEDED(xrGetCurrentInteractionProfile(s->session, s->hand[1], &profile)) &&
		    profile.interactionProfile != XR_NULL_PATH)
			xrPathToString(s->instance, profile.interactionProfile, sizeof name, &length, name);
		LOGI("right hand profile: %s", name);
		if (strcmp(name, "(none)")) logged_profile = 1;
	}
	for (h = 0; h < 2; h++) {
		XrActionStateGetInfo get = {XR_TYPE_ACTION_STATE_GET_INFO};
		XrActionStateBoolean state = {XR_TYPE_ACTION_STATE_BOOLEAN};
		int x, y;

		if (!ray_hit(s, h, time, &x, &y)) {
			s->was_selecting[h] = 0;
			continue;
		}
		if (!hit_any) {
			px = x;
			py = y;
			hit_any = 1;
		}
		get.action = s->select;
		get.subactionPath = s->hand[h];
		if (XR_SUCCEEDED(xrGetActionStateBoolean(s->session, &get, &state)) && !logged_active[h]) {
			LOGI("hand %d select active=%d state=%d", h, (int)state.isActive, (int)state.currentState);
			logged_active[h] = 1;
		}
		if (XR_SUCCEEDED(xrGetActionStateBoolean(s->session, &get, &state)) && state.isActive) {
			if (state.currentState && !s->was_selecting[h]) java_call_int2(s, "onClick", "(II)V", x, y, NULL);
			s->was_selecting[h] = state.currentState;
		}
	}
	if (hit_any != last_hit) {
		LOGI("pointer %s the panel (%d, %d)", hit_any ? "is on" : "left", px, py);
		last_hit = hit_any;
	}
	{
		int changed = 0;

		if (java_call_int2(s, "onHover", "(II)I", px, py, &changed) && changed) s->content_version++;
	}
}

static int create_swapchain(struct shell *s) {
	uint32_t count = 0, i;
	int64_t formats[64], chosen = 0;
	XrSwapchainCreateInfo info = {XR_TYPE_SWAPCHAIN_CREATE_INFO};

	CHECK(xrEnumerateSwapchainFormats(s->session, 0, &count, NULL));
	if (count > 64) count = 64;
	CHECK(xrEnumerateSwapchainFormats(s->session, count, &count, formats));
	// sRGB: the pixels from Java are already sRGB-encoded and are read back as such.
	for (i = 0; i < count; i++)
		if (formats[i] == GL_SRGB8_ALPHA8_FMT) chosen = formats[i];
	for (i = 0; i < count && !chosen; i++)
		if (formats[i] == GL_RGBA8_FMT) chosen = formats[i];
	if (!chosen) {
		LOGE("no usable swapchain format");
		return 0;
	}
	info.usageFlags = XR_SWAPCHAIN_USAGE_SAMPLED_BIT | XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT;
	info.format = chosen;
	info.sampleCount = 1;
	info.width = GRID_W;
	info.height = GRID_H;
	info.faceCount = 1;
	info.arraySize = 1;
	info.mipCount = 1;
	CHECK(xrCreateSwapchain(s->session, &info, &s->swapchain));
	CHECK(xrEnumerateSwapchainImages(s->swapchain, 0, &s->image_count, NULL));
	if (s->image_count > MAX_IMAGES) s->image_count = MAX_IMAGES;
	for (i = 0; i < s->image_count; i++) s->images[i] = (XrSwapchainImageOpenGLESKHR){XR_TYPE_SWAPCHAIN_IMAGE_OPENGL_ES_KHR};
	CHECK(xrEnumerateSwapchainImages(s->swapchain, s->image_count, &s->image_count,
					 (XrSwapchainImageBaseHeader *)s->images));
	LOGI("swapchain format 0x%llX, %u images", (long long)chosen, s->image_count);
	return 1;
}

static int create_eye_swapchains(struct shell *s) {
	uint32_t count = 0, i, e;
	XrViewConfigurationView views[2] = {{XR_TYPE_VIEW_CONFIGURATION_VIEW}, {XR_TYPE_VIEW_CONFIGURATION_VIEW}};

	CHECK(xrEnumerateViewConfigurationViews(s->instance, s->system, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 2, &count, views));
	if (count != 2) {
		LOGE("expected 2 views, got %u", count);
		return 0;
	}
	for (e = 0; e < 2; e++) {
		XrSwapchainCreateInfo info = {XR_TYPE_SWAPCHAIN_CREATE_INFO};

		info.usageFlags = XR_SWAPCHAIN_USAGE_SAMPLED_BIT | XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT;
		info.format = GL_SRGB8_ALPHA8_FMT;
		info.sampleCount = 1;
		info.width = views[e].recommendedImageRectWidth;
		info.height = views[e].recommendedImageRectHeight;
		info.faceCount = 1;
		info.arraySize = 1;
		info.mipCount = 1;
		CHECK(xrCreateSwapchain(s->session, &info, &s->eye_swapchain[e]));
		s->eye_width[e] = info.width;
		s->eye_height[e] = info.height;
		CHECK(xrEnumerateSwapchainImages(s->eye_swapchain[e], 0, &s->eye_image_count[e], NULL));
		if (s->eye_image_count[e] > MAX_IMAGES) s->eye_image_count[e] = MAX_IMAGES;
		for (i = 0; i < s->eye_image_count[e]; i++)
			s->eye_images[e][i] = (XrSwapchainImageOpenGLESKHR){XR_TYPE_SWAPCHAIN_IMAGE_OPENGL_ES_KHR};
		CHECK(xrEnumerateSwapchainImages(s->eye_swapchain[e], s->eye_image_count[e], &s->eye_image_count[e],
						 (XrSwapchainImageBaseHeader *)s->eye_images[e]));
		LOGI("eye %u: %ux%u, %u images", e, info.width, info.height, s->eye_image_count[e]);
	}
	glGenFramebuffers(1, &s->fbo);
	return 1;
}

// Clear both eyes to the shell's background; fills VIEWS with what the projection layer needs.
static int render_environment(struct shell *s, XrTime time, XrCompositionLayerProjectionView views[2]) {
	XrViewState view_state = {XR_TYPE_VIEW_STATE};
	XrViewLocateInfo locate = {XR_TYPE_VIEW_LOCATE_INFO};
	XrView located[2] = {{XR_TYPE_VIEW}, {XR_TYPE_VIEW}};
	uint32_t count = 0, e, index;

	locate.viewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
	locate.displayTime = time;
	locate.space = s->space;
	if (XR_FAILED(xrLocateViews(s->session, &locate, &view_state, 2, &count, located)) || count != 2) return 0;
	for (e = 0; e < 2; e++) {
		XrSwapchainImageAcquireInfo acquire = {XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
		XrSwapchainImageWaitInfo wait = {XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
		XrSwapchainImageReleaseInfo release = {XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};

		wait.timeout = XR_INFINITE_DURATION;
		if (XR_FAILED(xrAcquireSwapchainImage(s->eye_swapchain[e], &acquire, &index)) ||
		    XR_FAILED(xrWaitSwapchainImage(s->eye_swapchain[e], &wait)))
			return 0;
		glBindFramebuffer(GL_FRAMEBUFFER, s->fbo);
		glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, s->eye_images[e][index].image, 0);
		glViewport(0, 0, (GLsizei)s->eye_width[e], (GLsizei)s->eye_height[e]);
		glClearColor(0.004f, 0.005f, 0.008f, 1.0f); // The shell's background, in linear light.
		glClear(GL_COLOR_BUFFER_BIT);
		glBindFramebuffer(GL_FRAMEBUFFER, 0);
		glFinish();
		xrReleaseSwapchainImage(s->eye_swapchain[e], &release);
		views[e] = (XrCompositionLayerProjectionView){XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW};
		views[e].pose = located[e].pose;
		views[e].fov = located[e].fov;
		views[e].subImage.swapchain = s->eye_swapchain[e];
		views[e].subImage.imageRect.extent.width = (int32_t)s->eye_width[e];
		views[e].subImage.imageRect.extent.height = (int32_t)s->eye_height[e];
	}
	return 1;
}

// The grid as ARGB ints from Java, converted to RGBA bytes. Null when Java is not ready.
static unsigned char *grid_pixels(struct shell *s) {
	JNIEnv *env;
	JavaVM *vm = s->app->activity->vm;
	jclass cls;
	jmethodID method;
	jintArray array;
	static unsigned char rgba[GRID_W * GRID_H * 4];
	static jint argb[GRID_W * GRID_H];
	int i;

	if ((*vm)->AttachCurrentThread(vm, &env, NULL) != JNI_OK) return NULL;
	cls = (*env)->GetObjectClass(env, s->app->activity->clazz);
	method = (*env)->GetStaticMethodID(env, cls, "gridPixels", "()[I");
	if (!method) {
		(*env)->ExceptionClear(env);
		return NULL;
	}
	array = (jintArray)(*env)->CallStaticObjectMethod(env, cls, method);
	if (!array || (*env)->GetArrayLength(env, array) != GRID_W * GRID_H) return NULL;
	(*env)->GetIntArrayRegion(env, array, 0, GRID_W * GRID_H, argb);
	(*env)->DeleteLocalRef(env, array);
	// Java's rows run top to bottom, GL's bottom to top: write them flipped.
	for (i = 0; i < GRID_W * GRID_H; i++) {
		int row = i / GRID_W, column = i % GRID_W;
		unsigned char *out = rgba + ((GRID_H - 1 - row) * GRID_W + column) * 4;

		out[0] = (argb[i] >> 16) & 0xFF;
		out[1] = (argb[i] >> 8) & 0xFF;
		out[2] = argb[i] & 0xFF;
		out[3] = 0xFF;
	}
	return rgba;
}

static void render_frame(struct shell *s, XrFrameState *state) {
	XrFrameBeginInfo begin = {XR_TYPE_FRAME_BEGIN_INFO};
	XrFrameEndInfo end = {XR_TYPE_FRAME_END_INFO};
	XrCompositionLayerQuad quad = {XR_TYPE_COMPOSITION_LAYER_QUAD};
	const XrCompositionLayerBaseHeader *layers[2];
	XrCompositionLayerProjection projection = {XR_TYPE_COMPOSITION_LAYER_PROJECTION};
	XrCompositionLayerProjectionView projection_views[2];
	int have_projection = 0;
	uint32_t index;
	XrSwapchainImageAcquireInfo acquire = {XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
	XrSwapchainImageWaitInfo wait = {XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
	XrSwapchainImageReleaseInfo release = {XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
	static int frames;

	xrBeginFrame(s->session, &begin);
	end.displayTime = state->predictedDisplayTime;
	end.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
	if (state->shouldRender) {
		have_projection = render_environment(s, state->predictedDisplayTime, projection_views);
		wait.timeout = XR_INFINITE_DURATION;
		if (XR_SUCCEEDED(xrAcquireSwapchainImage(s->swapchain, &acquire, &index)) &&
		    XR_SUCCEEDED(xrWaitSwapchainImage(s->swapchain, &wait))) {
			if (s->version[index] != s->content_version) {
				unsigned char *pixels = grid_pixels(s);
				if (pixels) {
					glBindTexture(GL_TEXTURE_2D, s->images[index].image);
					glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, GRID_W, GRID_H, GL_RGBA,
							GL_UNSIGNED_BYTE, pixels);
					glFinish();
					s->version[index] = s->content_version;
				}
			}
			xrReleaseSwapchainImage(s->swapchain, &release);
			quad.space = s->space;
			quad.eyeVisibility = XR_EYE_VISIBILITY_BOTH;
			quad.subImage.swapchain = s->swapchain;
			quad.subImage.imageRect.extent.width = GRID_W;
			quad.subImage.imageRect.extent.height = GRID_H;
			quad.pose.orientation.w = 1.0f;
			quad.pose.position.z = QUAD_Z;
			quad.size.width = QUAD_WIDTH;
			quad.size.height = 1.8f * GRID_H / GRID_W;
			end.layerCount = 0;
			if (have_projection) {
				projection.space = s->space;
				projection.viewCount = 2;
				projection.views = projection_views;
				layers[end.layerCount++] = (const XrCompositionLayerBaseHeader *)&projection;
			}
			layers[end.layerCount++] = (const XrCompositionLayerBaseHeader *)&quad;
			end.layers = layers;
			if (frames++ == 0) LOGI("quad shown");
		}
	}
	xrEndFrame(s->session, &end);
}

static void handle_events(struct shell *s) {
	XrEventDataBuffer event = {XR_TYPE_EVENT_DATA_BUFFER};

	while (xrPollEvent(s->instance, &event) == XR_SUCCESS) {
		if (event.type == XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED) {
			XrEventDataSessionStateChanged *change = (XrEventDataSessionStateChanged *)&event;

			LOGI("session state %d", (int)change->state);
			if (change->state == XR_SESSION_STATE_READY) {
				XrSessionBeginInfo begin = {XR_TYPE_SESSION_BEGIN_INFO};
				begin.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
				if (XR_SUCCEEDED(xrBeginSession(s->session, &begin))) s->running = 1;
			} else if (change->state == XR_SESSION_STATE_STOPPING) {
				xrEndSession(s->session);
				s->running = 0;
			} else if (change->state == XR_SESSION_STATE_EXITING ||
				   change->state == XR_SESSION_STATE_LOSS_PENDING) {
				s->exit_requested = 1;
			}
		}
		event = (XrEventDataBuffer){XR_TYPE_EVENT_DATA_BUFFER};
	}
}

static void on_command(struct android_app *app, int32_t command) {
	struct shell *s = (struct shell *)app->userData;

	if (command == APP_CMD_DESTROY) s->exit_requested = 1;
	if (command == APP_CMD_RESUME) s->content_version++; // The catalog may have changed.
}

void android_main(struct android_app *app) {
	struct shell s;

	memset(&s, 0, sizeof s);
	s.app = app;
	s.content_version = 1;
	app->userData = &s;
	app->onAppCmd = on_command;
	LOGI("starting");
	if (!create_session(&s) || !create_actions(&s) || !create_swapchain(&s) ||
	    !create_eye_swapchains(&s)) {
		LOGE("OpenXR setup failed; ending");
		ANativeActivity_finish(app->activity);
		return;
	}
	LOGI("session created");
	while (!app->destroyRequested && !s.exit_requested) {
		struct android_poll_source *source;
		int events;

		while (ALooper_pollOnce(s.running ? 0 : 100, NULL, &events, (void **)&source) >= 0)
			if (source) source->process(app, source);
		handle_events(&s);
		if (s.running) {
			XrFrameWaitInfo wait = {XR_TYPE_FRAME_WAIT_INFO};
			XrFrameState state = {XR_TYPE_FRAME_STATE};

			if (XR_SUCCEEDED(xrWaitFrame(s.session, &wait, &state))) {
				handle_input(&s, state.predictedDisplayTime);
				render_frame(&s, &state);
			}
		}
	}
	if (s.eye_swapchain[0]) xrDestroySwapchain(s.eye_swapchain[0]);
	if (s.eye_swapchain[1]) xrDestroySwapchain(s.eye_swapchain[1]);
	if (s.swapchain) xrDestroySwapchain(s.swapchain);
	if (s.aim_space[0]) xrDestroySpace(s.aim_space[0]);
	if (s.aim_space[1]) xrDestroySpace(s.aim_space[1]);
	if (s.actions) xrDestroyActionSet(s.actions);
	if (s.space) xrDestroySpace(s.space);
	if (s.session) xrDestroySession(s.session);
	if (s.instance) xrDestroyInstance(s.instance);
	ANativeActivity_finish(app->activity);
}
