# A file bundle, not a runnable system: `wgapps update` and the README
# bootstrap copy /wgapps into ~/.local/share/waydroid-gapps on the Frame.
# Contains only this project's files. Android (and Google's apps) is
# downloaded on each Frame from Waydroid's own servers.
FROM scratch
# Layer 1: launcher and tools (changes most often, smallest).
COPY bin/ /wgapps/bin/
COPY VERSION LICENSE /wgapps/
# Layer 2: runtime overrides bind-mounted over Android paths.
COPY overrides/ /wgapps/overrides/
