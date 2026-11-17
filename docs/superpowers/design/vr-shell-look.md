# VR shell: how it should look and behave

Direction (from the user, 2026-11-15): a merge of **Steam** and **Android's generic launcher**, with
**Meta Spatial SDK / Horizon OS** panels as the spatial inspiration.

## What each source contributes

| Source | What we take |
|---|---|
| **Android's launcher** (the image ships Trebuchet/Launcher3 under `/system/system_ext/priv-app/TrebuchetQuickStep`) | a grid of app icons with labels, a **dock** of favorites along the bottom (Launcher3's hotseat), icons drawn from each app's own `PackageManager` icon, and the app list coming from the packages that have a launcher activity (our catalog already is that list) |
| **Steam** (the library the Frame already shows) | the **library header** with filter tabs (All / VR / Flat), the "VR apps" **first**, then everything else, Steam's blue as the single accent colour, Steam-style entries for per-app shortcuts remain in Steam mode |
| **Meta Spatial SDK / Horizon OS** ([panels](https://developers.meta.com/horizon/design/panels/)) | the shell and every 2D app window are **panels**: rounded rectangles in 3D that can be moved, resized and snapped; a panel's default size is 1024 x 640 dp and layouts are tested at 384 x 500, 1024 x 640 and 1440 x 1000 dp; any Android UI can be a panel, and the system handles input; viewing from varying distances including a theater view |

## Decisions for the build

1. **The shell is one panel at first** (V1, built): an OpenXR quad, 1.8 m wide at 1.7 m, 1920 x 1080
   texture drawn by Java (`VrShellActivity.gridPixels`) and uploaded by `native/shell.c`.
2. **App windows are panels too** (V2): each 2D app gets a virtual display (S4 measured this works)
   sized 1024 x 640 dp by default, shown as a quad, with a title bar for move/close and corner
   handles for resize; windows snap to a shared curved layout in front of the user.
3. **The dock stays visible** at the bottom of the shell panel and lists running apps first (their
   windows), then favorites; favorites come from a small list (`DOCK` in `VrShellActivity`) until a
   setting exists.
4. **Pointer input** is a controller ray (OpenXR actions, trigger = select); hover highlights a tile
   like Quest's library does. Not built yet.
5. **The 3D home** (V3) is the optional environment behind the panels; with it off the background
   is solid, or SteamVR's room view (the S5 result: passthrough is the system's room view, not a blend
   mode).
6. Steam mode is unchanged; this is only `wgapps mode vr`.

## Not decided yet

- Whether tabs filter in place or switch pages (Launcher3 pages, Quest library tabs).
- Cover art for VR apps (Steam shows art; Android apps only have icons). Art would be fetched at
  runtime, never bundled.
