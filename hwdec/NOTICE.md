# Hardware video decode add-on (optional, unstable, in testing)

**Status: unstable, in testing.** Optional, off unless you install and turn it on, and not recommended on a Frame you
leave unattended (see the warning at the end).

`wgapps-hwdec.tar.xz` is an optional add-on. `wgapps install --hwdec` or `wgapps hwdec install` unpacks it into
`~/.local/share/waydroid-gapps/lib/v4l2-codec2`, and nothing in it is used unless you do that and turn it on.
The rest of this project ships no Android software; this add-on is the one exception, and it is a separate
file so you can see exactly what it is.

## What it is

The Codec2 hardware video decoder service for Android's media stack, driving the SoC's V4L2 decoder
(`qcom-iris`: H.264, HEVC and VP9). It is built from the Android Open Source Project, tag
`android-13.0.0_r75` (`external/v4l2_codec2`, the Codec2 HIDL service in `frameworks/av`, and the libraries
they need), inside the Waydroid LineageOS 20 tree (product `lineage_waydroid_arm64_only-userdebug`), with the
six patches in [`tools/v4l2-codec2/`](../tools/v4l2-codec2/) applied. `tools/v4l2-codec2/README.md` describes the
build and what each patch fixes. The 22 files, as installed:

- `vendor/bin/hw/android.hardware.media.c2@1.0-service-v4l2-64` and its seccomp policy
- `vendor/lib64/`: `libv4l2_codec2_components`, `libv4l2_codec2_common`, `libc2plugin_store`, the Codec2 HIDL
  libraries (`libcodec2_hidl@1.0`/`1.1`/`1.2`, `android.hardware.media.c2@1.0`/`1.1`/`1.2`, buffer pools),
  `libchrome`, `libavservices_minijail` and a few helpers
- `system/lib64/libc2plugin_store.so`, the small client-side library the patches add

## License

The AOSP code is under the Apache License 2.0 (text in `LICENSE-Apache-2.0`), copyright The Android Open Source
Project and its contributors; `libchrome` is BSD-3-Clause (Chromium Authors). The patches are under the same
licenses as the files they change. This project's own GPL-3.0-or-later license (`LICENSE`) covers this project's
files, not these binaries. The source of every file is the public AOSP / LineageOS / Waydroid repositories at the
revisions above plus the patches here, so the binaries can be rebuilt (`tools/package-hwdec.py` packs a rebuilt
tree into the same archive format).

## Warning

On one Frame this decoder service was installed when the SoC's video codec reported a firmware error
(`qcom-iris ... received system error of type 0x5000003`) and the kernel then crashed (`Unable to handle kernel
paging request`), which rebooted the whole machine. The cause is not known. About 150 scripted Wolvic runs before
that decoded without a fault. Install it only if you want hardware decoding enough to accept that, and if your
Frame reboots shortly after Android starts, run `wgapps hwdec off` and look in `journalctl -k` for `qcom-iris`.
