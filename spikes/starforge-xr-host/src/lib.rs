//! The Starforge VR host, R0 (docs/plans: VR shell on the engine): an OpenXR session on Android
//! with one quad panel in front of the user.
//!
//! This crate builds as a `cdylib` that `android-activity`'s NativeActivity glue calls into, like
//! `starforge-mobile-android`. R0 only proves the platform path in Rust: the OpenXR loader
//! (loaded at run time from the APK), an OpenGL ES 3 session (the binding verified on the Steam
//! Frame), an sRGB swapchain, a quad layer, and the session state machine. R1 shows the native-ui
//! Android Views tree on the quad, R2 adds controller input.
#![cfg(target_os = "android")]

use android_activity::{AndroidApp, MainEvent, PollEvent};
use glow::HasContext;
use khronos_egl as egl;
use openxr as xr;
use std::time::Duration;

const PANEL_W: u32 = 1280;
const PANEL_H: u32 = 720;
const GL_SRGB8_ALPHA8: u32 = 0x8C43;
const QUAD_DISTANCE: f32 = 1.7;
const QUAD_WIDTH: f32 = 1.8;

/// What can go wrong setting the host up; logged, then the activity ends.
#[derive(Debug)]
enum HostError {
    Load(String),
    Xr(xr::sys::Result),
    Egl(String),
    Missing(&'static str),
}

impl From<xr::sys::Result> for HostError {
    fn from(e: xr::sys::Result) -> Self {
        HostError::Xr(e)
    }
}

/// An EGL context with a tiny pbuffer, current on this thread, and GL functions loaded from it.
struct Gl {
    egl: egl::DynamicInstance<egl::EGL1_4>,
    display: egl::Display,
    config: egl::Config,
    context: egl::Context,
    gl: glow::Context,
}

fn init_gl() -> Result<Gl, HostError> {
    let lib = unsafe { egl::DynamicInstance::<egl::EGL1_4>::load_required() }
        .map_err(|e| HostError::Egl(format!("load libEGL: {e}")))?;
    let display = unsafe { lib.get_display(egl::DEFAULT_DISPLAY) }
        .ok_or(HostError::Egl("no display".into()))?;
    lib.initialize(display)
        .map_err(|e| HostError::Egl(format!("initialize: {e}")))?;
    let attribs = [
        egl::RENDERABLE_TYPE,
        egl::OPENGL_ES3_BIT,
        egl::RED_SIZE,
        8,
        egl::GREEN_SIZE,
        8,
        egl::BLUE_SIZE,
        8,
        egl::ALPHA_SIZE,
        8,
        egl::SURFACE_TYPE,
        egl::PBUFFER_BIT,
        egl::NONE,
    ];
    let config = lib
        .choose_first_config(display, &attribs)
        .map_err(|e| HostError::Egl(format!("choose config: {e}")))?
        .ok_or(HostError::Egl("no config".into()))?;
    let context = lib
        .create_context(
            display,
            config,
            None,
            &[egl::CONTEXT_CLIENT_VERSION, 3, egl::NONE],
        )
        .map_err(|e| HostError::Egl(format!("create context: {e}")))?;
    let surface = lib
        .create_pbuffer_surface(
            display,
            config,
            &[egl::WIDTH, 16, egl::HEIGHT, 16, egl::NONE],
        )
        .map_err(|e| HostError::Egl(format!("pbuffer: {e}")))?;
    lib.make_current(display, Some(surface), Some(surface), Some(context))
        .map_err(|e| HostError::Egl(format!("make current: {e}")))?;
    let gl = unsafe {
        glow::Context::from_loader_function(|name| {
            lib.get_proc_address(name)
                .map_or(std::ptr::null(), |f| f as *const _)
        })
    };
    Ok(Gl {
        egl: lib,
        display,
        config,
        context,
        gl,
    })
}

/// Fill a texture with a dark panel and a bright bar, so a quad on the headset is recognisable.
fn paint_panel(gl: &glow::Context, fbo: glow::Framebuffer, texture: u32) {
    unsafe {
        gl.bind_framebuffer(glow::FRAMEBUFFER, Some(fbo));
        gl.framebuffer_texture_2d(
            glow::FRAMEBUFFER,
            glow::COLOR_ATTACHMENT0,
            glow::TEXTURE_2D,
            std::num::NonZeroU32::new(texture).map(glow::NativeTexture),
            0,
        );
        gl.viewport(0, 0, PANEL_W as i32, PANEL_H as i32);
        gl.enable(glow::SCISSOR_TEST);
        gl.scissor(0, 0, PANEL_W as i32, PANEL_H as i32);
        gl.clear_color(0.012, 0.014, 0.022, 1.0);
        gl.clear(glow::COLOR_BUFFER_BIT);
        gl.scissor(64, PANEL_H as i32 - 160, PANEL_W as i32 - 128, 96);
        gl.clear_color(0.01, 0.35, 1.0, 1.0); // Steam's blue, in linear light
        gl.clear(glow::COLOR_BUFFER_BIT);
        gl.disable(glow::SCISSOR_TEST);
        gl.finish();
        gl.bind_framebuffer(glow::FRAMEBUFFER, None);
    }
}

fn run(app: &AndroidApp) -> Result<(), HostError> {
    let entry = unsafe { xr::Entry::load() }.map_err(|e| HostError::Load(format!("{e}")))?;
    entry.initialize_android_loader()?;
    let available = entry.enumerate_extensions()?;
    if !available.khr_opengl_es_enable {
        return Err(HostError::Missing("XR_KHR_opengl_es_enable"));
    }
    let mut enabled = xr::ExtensionSet::default();
    enabled.khr_opengl_es_enable = true;
    enabled.khr_android_create_instance = available.khr_android_create_instance;
    let instance = entry.create_instance(
        &xr::ApplicationInfo {
            application_name: "Starforge VR host",
            application_version: 1,
            engine_name: "starforge",
            engine_version: 1,
            api_version: xr::Version::new(1, 0, 0),
        },
        &enabled,
        &[],
    )?;
    let system = instance.system(xr::FormFactor::HEAD_MOUNTED_DISPLAY)?;
    let _requirements = instance.graphics_requirements::<xr::OpenGlEs>(system)?;
    log::info!("OpenXR instance created");

    let gl = init_gl()?;
    let (session, mut frame_wait, mut frame_stream) = unsafe {
        instance.create_session::<xr::OpenGlEs>(
            system,
            &xr::opengles::SessionCreateInfo::Android {
                display: gl.display.as_ptr() as _,
                config: gl.config.as_ptr() as _,
                context: gl.context.as_ptr() as _,
            },
        )?
    };
    let space =
        session.create_reference_space(xr::ReferenceSpaceType::LOCAL, xr::Posef::IDENTITY)?;

    let mut swapchain = session.create_swapchain(&xr::SwapchainCreateInfo {
        create_flags: xr::SwapchainCreateFlags::EMPTY,
        usage_flags: xr::SwapchainUsageFlags::COLOR_ATTACHMENT | xr::SwapchainUsageFlags::SAMPLED,
        format: GL_SRGB8_ALPHA8,
        sample_count: 1,
        width: PANEL_W,
        height: PANEL_H,
        face_count: 1,
        array_size: 1,
        mip_count: 1,
    })?;
    let images = swapchain.enumerate_images()?;
    let fbo = unsafe { gl.gl.create_framebuffer() }.map_err(|e| HostError::Egl(e))?;
    log::info!("session created, {} swapchain images", images.len());

    let mut event_storage = xr::EventDataBuffer::new();
    let mut running = false;
    let mut shown = false;
    let mut quitting = false;
    while !quitting {
        app.poll_events(
            Some(Duration::from_millis(if running { 0 } else { 100 })),
            |event| {
                if let PollEvent::Main(MainEvent::Destroy) = event {
                    quitting = true;
                }
            },
        );
        while let Some(event) = instance.poll_event(&mut event_storage)? {
            if let xr::Event::SessionStateChanged(change) = event {
                log::info!("session state {:?}", change.state());
                match change.state() {
                    xr::SessionState::READY => {
                        session.begin(xr::ViewConfigurationType::PRIMARY_STEREO)?;
                        running = true;
                    }
                    xr::SessionState::STOPPING => {
                        session.end()?;
                        running = false;
                    }
                    xr::SessionState::EXITING | xr::SessionState::LOSS_PENDING => quitting = true,
                    _ => {}
                }
            }
        }
        if !running {
            continue;
        }
        let state = frame_wait.wait()?;
        frame_stream.begin()?;
        if !state.should_render {
            frame_stream.end(
                state.predicted_display_time,
                xr::EnvironmentBlendMode::OPAQUE,
                &[],
            )?;
            continue;
        }
        let index = swapchain.acquire_image()? as usize;
        swapchain.wait_image(xr::Duration::INFINITE)?;
        paint_panel(&gl.gl, fbo, images[index]);
        swapchain.release_image()?;
        let rect = xr::Rect2Di {
            offset: xr::Offset2Di { x: 0, y: 0 },
            extent: xr::Extent2Di {
                width: PANEL_W as _,
                height: PANEL_H as _,
            },
        };
        let quad = xr::CompositionLayerQuad::new()
            .space(&space)
            .eye_visibility(xr::EyeVisibility::BOTH)
            .pose(xr::Posef {
                orientation: xr::Quaternionf::IDENTITY,
                position: xr::Vector3f {
                    x: 0.0,
                    y: 0.0,
                    z: -QUAD_DISTANCE,
                },
            })
            .size(xr::Extent2Df {
                width: QUAD_WIDTH,
                height: QUAD_WIDTH * PANEL_H as f32 / PANEL_W as f32,
            })
            .sub_image(
                xr::SwapchainSubImage::new()
                    .swapchain(&swapchain)
                    .image_rect(rect),
            );
        frame_stream.end(
            state.predicted_display_time,
            xr::EnvironmentBlendMode::OPAQUE,
            &[&quad],
        )?;
        if !shown {
            log::info!("quad shown");
            shown = true;
        }
    }
    drop((space, swapchain, session, frame_wait, frame_stream));
    let _ = gl.egl.destroy_context(gl.display, gl.context);
    Ok(())
}

#[no_mangle]
fn android_main(app: AndroidApp) {
    android_logger::init_once(
        android_logger::Config::default()
            .with_max_level(log::LevelFilter::Info)
            .with_tag("SFXR"),
    );
    log::info!("starting");
    if let Err(error) = run(&app) {
        log::error!("host failed: {error:?}");
    }
}
