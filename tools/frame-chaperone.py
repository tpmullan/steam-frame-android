"""Runs ON the Frame. Reads or sets SteamVR's standing zero pose (the play-space origin) through the
OpenVR chaperone setup API, so a headset that cannot be moved can still behave as if it had turned.
  python3 chap.py get [seated]
  python3 chap.py yaw DEGREES [seated]   (rotate the origin about vertical by DEGREES, keeping its position)

The standing pose is the stage reference space; the seated pose is what OpenXR's LOCAL space (and so a
360 video sphere) follows. Add `seated` to work on that one.
"""

import ctypes as C
import math
import sys

LIB = "/opt/steamvr/bin/linuxarm64/libopenvr_api.so"
APP_UTILITY = 4
LIVE = 1  # EChaperoneConfigFile_Live


class Matrix34(C.Structure):
    _fields_ = [("m", (C.c_float * 4) * 3)]


Err = C.c_int
# VR_IVRChaperoneSetup_FnTable, IVRChaperoneSetup_006 (openvr_capi.h), in declaration order.
FIELDS = [
    ("CommitWorkingCopy", C.CFUNCTYPE(C.c_bool, C.c_int)),
    ("RevertWorkingCopy", C.CFUNCTYPE(None)),
    ("GetWorkingPlayAreaSize", C.CFUNCTYPE(C.c_bool, C.POINTER(C.c_float), C.POINTER(C.c_float))),
    ("GetWorkingPlayAreaRect", C.CFUNCTYPE(C.c_bool, C.c_void_p)),
    ("GetWorkingCollisionBoundsInfo", C.CFUNCTYPE(C.c_bool, C.c_void_p, C.POINTER(C.c_uint32))),
    ("GetLiveCollisionBoundsInfo", C.CFUNCTYPE(C.c_bool, C.c_void_p, C.POINTER(C.c_uint32))),
    ("GetWorkingSeatedZeroPoseToRawTrackingPose", C.CFUNCTYPE(C.c_bool, C.POINTER(Matrix34))),
    ("GetWorkingStandingZeroPoseToRawTrackingPose", C.CFUNCTYPE(C.c_bool, C.POINTER(Matrix34))),
    ("SetWorkingPlayAreaSize", C.CFUNCTYPE(None, C.c_float, C.c_float)),
    ("SetWorkingCollisionBoundsInfo", C.CFUNCTYPE(None, C.c_void_p, C.c_uint32)),
    ("SetWorkingPerimeter", C.CFUNCTYPE(None, C.c_void_p, C.c_uint32)),
    ("SetWorkingSeatedZeroPoseToRawTrackingPose", C.CFUNCTYPE(None, C.POINTER(Matrix34))),
    ("SetWorkingStandingZeroPoseToRawTrackingPose", C.CFUNCTYPE(None, C.POINTER(Matrix34))),
    ("ReloadFromDisk", C.CFUNCTYPE(None, C.c_int)),
]


class FnTable(C.Structure):
    _fields_ = FIELDS


def show(m):
    r = [[round(m.m[i][j], 4) for j in range(4)] for i in range(3)]
    yaw = math.degrees(math.atan2(-m.m[2][0], m.m[0][0]))
    print("pose rows:", r, "yaw about vertical (deg): %.1f" % yaw)


def main():
    vr = C.CDLL(LIB)
    vr.VR_InitInternal2.restype = C.c_uint32
    vr.VR_InitInternal2.argtypes = [C.POINTER(Err), C.c_int, C.c_char_p]
    vr.VR_GetGenericInterface.restype = C.c_void_p
    vr.VR_GetGenericInterface.argtypes = [C.c_char_p, C.POINTER(Err)]
    err = Err(0)
    vr.VR_InitInternal2(C.byref(err), APP_UTILITY, None)
    if err.value:
        sys.exit(f"cannot reach SteamVR (init error {err.value})")
    ptr = vr.VR_GetGenericInterface(b"FnTable:IVRChaperoneSetup_006", C.byref(err))
    if err.value or not ptr:
        sys.exit(f"no IVRChaperoneSetup_006 ({err.value})")
    t = C.cast(ptr, C.POINTER(FnTable)).contents
    t.ReloadFromDisk(LIVE)
    m = Matrix34()
    seated = sys.argv[-1] == "seated"
    get = (
        t.GetWorkingSeatedZeroPoseToRawTrackingPose
        if seated
        else t.GetWorkingStandingZeroPoseToRawTrackingPose
    )
    put = (
        t.SetWorkingSeatedZeroPoseToRawTrackingPose
        if seated
        else t.SetWorkingStandingZeroPoseToRawTrackingPose
    )
    if not get(C.byref(m)):
        sys.exit("reading the zero pose failed")
    print("before:"), show(m)
    if sys.argv[1] == "yaw":
        a = math.radians(float(sys.argv[2]))
        c, s = math.cos(a), math.sin(a)
        n = Matrix34()
        # R * M for a rotation R about the vertical axis: rows 0 and 2 mix, the position is kept
        for j in range(4):
            r0, r1, r2 = m.m[0][j], m.m[1][j], m.m[2][j]
            n.m[0][j] = c * r0 + s * r2 if j < 3 else r0
            n.m[1][j] = r1
            n.m[2][j] = -s * r0 + c * r2 if j < 3 else r2
        put(C.byref(n))
        print("commit:", t.CommitWorkingCopy(LIVE))
        t.ReloadFromDisk(LIVE)
        get(C.byref(m))
        print("after:"), show(m)
    vr.VR_ShutdownInternal()


main()
