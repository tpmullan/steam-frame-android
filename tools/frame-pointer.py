#!/usr/bin/env python3
"""Move, click, drag and scroll a pointer on the Android panel the way the headset does.

Runs ON the Frame (gamescope's emulated-input socket is local): the controller's pointing
reaches gamescope as pointer events from the OpenVR overlay, and this sends the same kind of
events through gamescope's libei socket, so the whole path from gamescope to Android's input
is exercised. Used by tools/gpu-trial.py (it pipes this file to `python3 -` over ssh).

  python3 frame-pointer.py [--seconds 8] [--socket /run/user/1000/gamescope-0-ei]

Exit 0 when events were sent, 2 when gamescope offered no pointer.
"""

import argparse
import ctypes
import os
import select
import sys
import time

EVENT_SEAT_ADDED, EVENT_DEVICE_ADDED, EVENT_DEVICE_RESUMED = 3, 5, 8
CAP_POINTER, CAP_POINTER_ABSOLUTE, CAP_SCROLL, CAP_BUTTON = 1, 2, 16, 32
BTN_LEFT = 0x110


def load():
    lib = ctypes.CDLL("libei.so.1")
    p = ctypes.c_void_p
    lib.ei_new_sender.restype = p
    lib.ei_new_sender.argtypes = [p]
    lib.ei_configure_name.argtypes = [p, ctypes.c_char_p]
    lib.ei_setup_backend_socket.argtypes = [p, ctypes.c_char_p]
    lib.ei_get_fd.argtypes = [p]
    lib.ei_dispatch.argtypes = [p]
    lib.ei_get_event.restype = p
    lib.ei_get_event.argtypes = [p]
    lib.ei_event_unref.argtypes = [p]
    lib.ei_event_get_type.argtypes = [p]
    lib.ei_event_get_seat.restype = p
    lib.ei_event_get_seat.argtypes = [p]
    lib.ei_event_get_device.restype = p
    lib.ei_event_get_device.argtypes = [p]
    lib.ei_seat_bind_capabilities.argtypes = None  # variadic
    lib.ei_device_has_capability.argtypes = [p, ctypes.c_int]
    lib.ei_device_has_capability.restype = ctypes.c_bool
    lib.ei_device_ref.restype = p
    lib.ei_device_ref.argtypes = [p]
    lib.ei_device_start_emulating.argtypes = [p, ctypes.c_uint32]
    lib.ei_device_get_region.restype = p
    lib.ei_device_get_region.argtypes = [p, ctypes.c_size_t]
    lib.ei_region_get_width.restype = ctypes.c_uint32
    lib.ei_region_get_width.argtypes = [p]
    lib.ei_region_get_height.restype = ctypes.c_uint32
    lib.ei_region_get_height.argtypes = [p]
    lib.ei_device_pointer_motion_absolute.argtypes = [p, ctypes.c_double, ctypes.c_double]
    lib.ei_device_button_button.argtypes = [p, ctypes.c_uint32, ctypes.c_bool]
    lib.ei_device_scroll_discrete.argtypes = [p, ctypes.c_int32, ctypes.c_int32]
    lib.ei_device_frame.argtypes = [p, ctypes.c_uint64]
    lib.ei_now.restype = ctypes.c_uint64
    lib.ei_now.argtypes = [p]
    return lib


class Pointer:
    def __init__(self, socket):
        self.lib = load()
        self.ei = self.lib.ei_new_sender(None)
        self.lib.ei_configure_name(self.ei, b"wgapps-pointer-test")
        if self.lib.ei_setup_backend_socket(self.ei, socket.encode()) != 0:
            raise SystemExit(f"cannot connect to {socket}")
        self.device = None
        self.size = (1280, 800)

    def pump(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            select.select([self.lib.ei_get_fd(self.ei)], [], [], 0.05)
            self.lib.ei_dispatch(self.ei)
            while event := self.lib.ei_get_event(self.ei):
                self.handle(event)
                self.lib.ei_event_unref(event)

    def handle(self, event):
        kind = self.lib.ei_event_get_type(event)
        if kind == EVENT_SEAT_ADDED:
            seat = self.lib.ei_event_get_seat(event)
            self.lib.ei_seat_bind_capabilities(
                ctypes.c_void_p(seat),
                ctypes.c_int(CAP_POINTER_ABSOLUTE),
                ctypes.c_int(CAP_BUTTON),
                ctypes.c_int(CAP_SCROLL),
                ctypes.c_int(0),
            )
        elif kind == EVENT_DEVICE_ADDED:
            device = self.lib.ei_event_get_device(event)
            if self.lib.ei_device_has_capability(device, CAP_POINTER_ABSOLUTE):
                self.device = self.lib.ei_device_ref(device)
                region = self.lib.ei_device_get_region(device, 0)
                if region:
                    self.size = (
                        self.lib.ei_region_get_width(region),
                        self.lib.ei_region_get_height(region),
                    )
        elif kind == EVENT_DEVICE_RESUMED and self.device:
            self.lib.ei_device_start_emulating(self.device, 1)
            self.ready = True

    ready = False

    def frame(self):
        self.lib.ei_device_frame(self.device, self.lib.ei_now(self.ei))
        self.pump(0.02)

    def move(self, fx, fy):
        w, h = self.size
        self.lib.ei_device_pointer_motion_absolute(self.device, fx * w, fy * h)
        self.frame()

    def button(self, down):
        self.lib.ei_device_button_button(self.device, BTN_LEFT, down)
        self.frame()

    def scroll(self, steps):
        self.lib.ei_device_scroll_discrete(self.device, 0, steps * 120)
        self.frame()

    def sweep(self, x0, y0, x1, y1, steps=25, pause=0.02):
        for i in range(steps + 1):
            self.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
            time.sleep(pause)


def scenario(pointer, seconds):
    """What a person does with the panel: point around, click, drag a window, scroll."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pointer.sweep(0.1, 0.1, 0.9, 0.9)  # point across the panel
        pointer.sweep(0.9, 0.2, 0.2, 0.8)
        pointer.move(0.5, 0.5)
        pointer.button(True)  # click
        time.sleep(0.05)
        pointer.button(False)
        pointer.button(True)  # drag
        pointer.sweep(0.3, 0.3, 0.7, 0.6, steps=15)
        pointer.button(False)
        pointer.scroll(-3)
        pointer.scroll(3)
        pointer.sweep(0.5, 0.0, 0.5, 1.0, steps=30)  # up the edge, over the status bar


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--socket", default=f"/run/user/{os.getuid()}/gamescope-0-ei")
    args = parser.parse_args(argv)
    pointer = Pointer(args.socket)
    pointer.pump(1.5)
    if not pointer.device or not pointer.ready:
        print("gamescope offered no absolute pointer", file=sys.stderr)
        return 2
    print(f"pointer ready, region {pointer.size[0]}x{pointer.size[1]}", flush=True)
    scenario(pointer, args.seconds)
    print("events sent")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
