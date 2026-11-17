# A file bundle, not a runnable system: `wgapps update` and the README
# bootstrap copy /wgapps into ~/.local/share/waydroid-gapps on the Frame.
# Contains only this project's files and libgbinder (BSD-3-Clause, built by
# tools/build-libgbinder.sh into lib/). Android (and Google's apps) is
# downloaded on each Frame from Waydroid's servers.
FROM scratch
# Layer 1: libraries (change least often).
COPY lib/ /wgapps/lib/
# Layer 2: launcher and tools.
COPY bin/ /wgapps/bin/
COPY VERSION LICENSE /wgapps/
# Layer 3: runtime overrides bind-mounted over Android paths.
COPY overrides/ /wgapps/overrides/
