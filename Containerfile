# A file bundle, not a runnable system: `wgapps update` and the README
# bootstrap copy /wgapps into ~/.local/share/waydroid-gapps on the Frame.
# Contains this project's files, libgbinder (BSD-3-Clause, built by
# tools/build-libgbinder.sh into lib/) and, in hwdec/, the optional hardware video decode add-on
# (AOSP code under Apache-2.0, see hwdec/NOTICE.md), which is used only if `wgapps hwdec install` is run.
# Android itself (and Google's apps) is downloaded on each Frame from Waydroid's servers.
FROM scratch
# Layer 1: libraries (change least often).
COPY lib/ /wgapps/lib/
# Layer 2: launcher and tools.
COPY bin/ /wgapps/bin/
COPY VERSION LICENSE /wgapps/
# Layer 3: the optional hardware decode add-on (a checked archive; nothing uses it unless installed).
COPY hwdec/ /wgapps/hwdec/
# Layer 4: runtime overrides bind-mounted over Android paths.
COPY overrides/ /wgapps/overrides/
