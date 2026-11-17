# V4L2 Codec2 hardware video decode for Waydroid on the Steam Frame

The Frame's SoC decodes H.264, HEVC and VP9 up to 8K in hardware (the `iris` V4L2 driver,
`/dev/video-dec0`), but Waydroid's LineageOS 20 image only has Google's software codecs, which is why
YouTube stops at 1080p. AOSP's `external/v4l2_codec2` is a Codec2 HAL that drives V4L2 decoders; these
patches make it work on this image and this driver, and `bin/wgapps` (`mount_hw_decode`) installs it.
`tools/decode-check.py` is the acceptance test (host decoder, container node, Android codec list, and a
4K clip played in Chrome that must use `c2.v4l2.vp9.decoder`).

## Build

1. A Lineage 20 tree with Waydroid's local manifests and patches, exactly as Waydroid's own build
   instructions say (`repo init -b lineage-20.0`, `generate-manifest.sh`, `repo sync`,
   `apply-waydroid-patches`), product `lineage_waydroid_arm64_only-userdebug`. The tree must keep the
   `device` group (Waydroid's device tree needs it).
2. Apply `0001` to `0006` in order, each from the directory it names (the paths are relative to
   `external/v4l2_codec2/` for 0001 to 0003, 0005 and 0006, and to `frameworks/av/media/codec2/hidl/` for
   0004).
3. Add to `device/waydroid/waydroid/device.mk`:

       PRODUCT_SOONG_NAMESPACES += external/v4l2_codec2
       PRODUCT_PACKAGES += \
           android.hardware.media.c2@1.0-service-v4l2 \
           libc2plugin_store \
           libc2plugin_store_client \
           libv4l2_codec2_components

4. `m android.hardware.media.c2@1.0-service-v4l2 libv4l2_codec2_components libc2plugin_store
   libc2plugin_store_client`.

## Install

Copy these out of `out/target/product/waydroid_arm64_only/` into
`~/.local/share/waydroid-gapps/lib/v4l2-codec2/` keeping the paths (the layout of Android's partitions):

- `vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2-64`
- `vendor/etc/seccomp_policy/android.hardware.media.c2@1.2-default-seccomp_policy`
- `vendor/lib64/` the libraries the service needs that the image lacks: `libv4l2_codec2_components`,
  `libv4l2_codec2_common`, `libc2plugin_store`, `libchrome`, `libavservices_minijail`, `libcodec2_vndk`,
  `libcodec2_soft_common`, `libcodec2_hidl_plugin`, `libcodec2_hidl@1.0/1.1/1.2`,
  `android.hardware.media.c2@1.0/1.1/1.2`, `android.hardware.media.bufferpool@1.0`,
  `libsfplugin_ccodec_utils`, `libstagefright_bufferpool@1.0` and `@2.0.1`
- `system/lib64/libc2plugin_store.so` (the client-side build, from `libc2plugin_store_client`)

Replace a library by renaming a new file over it, never by writing into a file a running process has
mapped (that crashes the process). `wgapps` does the rest at the next Android start: mounts, init file,
HAL declaration, codec list, seccomp extension, properties and the device node.

## What each patch fixes (found in this order)

| Patch | Symptom | Cause |
|---|---|---|
| 0001 | `VIDIOC_REQBUFS` fails, kernel logs `current session not supported(-22)` | the service sets the input format with a 0x0 size; iris wants a real one and learns the true size from the stream |
| 0002 | `VIDIOC_QBUF` fails | iris needs 17694720-byte bitstream buffers whatever the resolution; the service allocates 1 to 4 MB. Now `ro.vendor.v4l2_codec2.min_input_buffer_size` (set by `wgapps`) |
| 0003 | `VIDIOC_G_CTRL` fails and the decoder goes to an error state | this kernel's iris exposes no `V4L2_CID_MIN_BUFFERS_FOR_CAPTURE`; assume the default 4 |
| 0004 | crash in `C2VdaBqBlockPool` | the HIDL `Component::setOutputSurface` only configures the producer of pools whose allocator id is `BUFFERQUEUE`, not the V4L2 pool's |
| 0005 | the same | Android 13 calls the sync-object overload of `configureProducer`, which the V4L2 pool did not override |
| 0006 | the same, `Failed to load library: libc2plugin_store.so` in the client | the client (Chrome's MediaCodec) cannot load a vendor library, so it cannot resolve the V4L2 allocator ids and asks for a plain buffer-queue pool, which the V4L2 code then mistakes for its own type; a small system-side library answers for the ids |

## Debugging

- The service dies with `init: ... received signal 31` (SIGSYS): a seccomp kill. Android's `strace` exists
  in the container: stop the service (`setprop ctl.stop android-hardware-media-c2-v4l2-hal-1-0`), start
  it under `strace -f -o /data/local/tmp/c2.strace <binary>`, replay, and look for `--- SIGSYS`
  (`si_syscall=`) or an earlier `--- SIGSEGV`. A crash is hidden by the sandbox because Android's crash
  handler needs calls (`sysinfo`, `execve`, ...) the policy lacks; widen `hw_decode_ext_policy` temporarily
  to get a tombstone.
- The kernel's reason for a refused V4L2 call is in `dmesg` (`qcom-iris ...`). `v4l2-ctl -d /dev/video22`
  reproduces the service's steps on the host.
- The service only probes `/dev/video` and `/dev/video0..15`, so `wgapps` also exposes the decoder as
  `/dev/video0`.
