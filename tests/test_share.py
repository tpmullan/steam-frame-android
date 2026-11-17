"""wgapps share: folders of this computer inside Android's storage."""

import pathlib
import shutil
import tempfile
import unittest

from helpers import wgapps_call, wgapps_mounts


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class ShareTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = pathlib.Path(tmp.name).resolve()
        self.base = self.home / ".local/share/waydroid-gapps"
        self.base.mkdir(parents=True)
        self.env = {"HOME": str(self.home), "WGAPPS_BASE": str(self.base)}
        self.conf = self.base / "shares.conf"

    def share(self, *args):
        return wgapps_call(self.env, "cmd_share", *args)

    def listing(self):
        out = self.share().stdout
        return [tuple(line.split("\t")) for line in out.splitlines()]

    def folder(self, name):
        path = self.home / name
        path.mkdir(exist_ok=True)
        return path

    def test_the_built_in_folder_is_always_there_and_read_write(self):
        self.assertEqual(self.listing(), [("Host", str(self.home / "Android-share"), "rw")])

    def test_added_folders_are_read_only_unless_asked(self):
        music = self.folder("Tunes")
        self.assertEqual(self.share("add", str(music)).returncode, 0)
        self.assertEqual(self.share("add", str(self.folder("Work")), "--rw").returncode, 0)
        rows = {name: (path, mode) for name, path, mode in self.listing()}
        self.assertEqual(rows["Tunes"], (str(music), "ro"))
        self.assertEqual(rows["Work"], (str(self.home / "Work"), "rw"))

    def test_the_whole_home_directory_can_be_shared(self):
        done = self.share("add", str(self.home), "Home")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(("Home", str(self.home), "ro"), self.listing())
        self.assertEqual(self.share("add", str(self.home), "Home", "--rw").returncode, 0)
        self.assertIn(("Home", str(self.home), "rw"), self.listing())

    def test_a_name_can_be_chosen_and_a_clumsy_one_is_cleaned_up(self):
        self.share("add", str(self.folder("My Files")))
        self.assertIn("My-Files", [name for name, _, _ in self.listing()])
        self.share("add", str(self.folder("x")), "photos")
        self.assertIn("photos", [name for name, _, _ in self.listing()])

    def test_names_android_uses_and_the_built_in_one_are_refused(self):
        for name in ("Download", "dcim", "Android", "Host", "host"):
            done = self.share("add", str(self.folder("f")), name)
            self.assertNotEqual(done.returncode, 0, name)
        self.assertEqual(len(self.listing()), 1)

    def test_wgapps_own_data_and_the_root_are_refused(self):
        inside = self.base / "data"
        inside.mkdir()
        for path in ("/", str(self.base), str(inside)):
            self.assertNotEqual(self.share("add", path, "Danger").returncode, 0, path)
        self.assertEqual(len(self.listing()), 1)

    def test_missing_directories_and_awkward_paths_are_refused(self):
        weird = self.home / "a,b"
        weird.mkdir()
        colon = self.home / "a:b"
        colon.mkdir()
        for path in (str(self.home / "nothing"), str(weird), str(colon)):
            self.assertNotEqual(self.share("add", path, "X").returncode, 0, path)
        (self.home / "afile").write_text("x")
        self.assertNotEqual(self.share("add", str(self.home / "afile"), "F").returncode, 0)

    def test_adding_the_same_name_again_replaces_it(self):
        self.share("add", str(self.folder("One")), "Shared")
        self.share("add", str(self.folder("Two")), "Shared", "--rw")
        rows = [r for r in self.listing() if r[0] == "Shared"]
        self.assertEqual(rows, [("Shared", str(self.home / "Two"), "rw")])

    def test_remove_forgets_a_folder_and_keeps_the_built_in_one(self):
        self.share("add", str(self.folder("One")), "One")
        self.assertEqual(self.share("remove", "One").returncode, 0)
        self.assertEqual([n for n, _, _ in self.listing()], ["Host"])
        self.assertNotEqual(self.share("remove", "One").returncode, 0)
        self.assertNotEqual(self.share("remove", "Host").returncode, 0)
        self.assertTrue((self.home / "One").is_dir())  # the folder itself is never touched

    def test_a_remove_matches_the_name_exactly(self):
        self.share("add", str(self.folder("a")), "a.b")
        self.share("add", str(self.folder("b")), "axb")
        self.assertEqual(self.share("remove", "a.b").returncode, 0)
        self.assertEqual([n for n, _, _ in self.listing()], ["Host", "axb"])

    def test_the_mounts_go_into_androids_own_storage(self):
        self.share("add", str(self.folder("Tunes")), "Tunes")
        self.share("add", str(self.folder("Work")), "Work", "--rw")
        mounts = wgapps_mounts("mount_shares", self.env)
        mounts.pop("/vendor/etc/init/wgapps-shares.rc")
        mounts.pop("/vendor/bin/wgapps-shares.sh")
        self.assertEqual(
            mounts,
            {
                "/data/media/0/Host": (str(self.home / "Android-share"), "rw"),
                "/data/media/0/Tunes": (str(self.home / "Tunes"), "ro"),
                "/data/media/0/Work": (str(self.home / "Work"), "rw"),
            },
        )
        self.assertTrue((self.home / "Android-share").is_dir())  # made on the first start

    def test_a_service_binds_each_share_where_the_files_app_looks_once_storage_is_up(self):
        self.share("add", str(self.folder("Tunes")), "Tunes")
        script = wgapps_call(self.env, "shares_script").stdout
        self.assertIn(
            "/mnt/pass_through/0/emulated ' /proc/mounts", script
        )  # waits for vold's mount
        self.assertIn("mount -o bind", script)
        self.assertEqual(script.splitlines()[-2:], ["bind_share Host", "bind_share Tunes"])
        rc = wgapps_call(self.env, "shares_init_rc").stdout
        self.assertIn("service wgapps-shares /system/bin/sh /vendor/bin/wgapps-shares.sh", rc)
        self.assertIn("on property:sys.boot_completed=1\n    start wgapps-shares", rc)

    def test_mounting_also_provides_the_init_file_and_the_script(self):
        mounts = wgapps_mounts("mount_shares", self.env)
        for destination in ("/vendor/etc/init/wgapps-shares.rc", "/vendor/bin/wgapps-shares.sh"):
            source, options = mounts[destination]
            self.assertEqual(options, "ro")
            self.assertTrue(pathlib.Path(source).is_file())
        self.assertIn(
            "bind_share Host", pathlib.Path(mounts["/vendor/bin/wgapps-shares.sh"][0]).read_text()
        )

    def test_a_folder_that_has_gone_or_a_damaged_line_is_not_mounted(self):
        gone = self.folder("Gone")
        self.share("add", str(gone), "Gone")
        gone.rmdir()
        self.conf.write_text(
            self.conf.read_text()
            + f"Bad mode\t{self.home}\tsideways\n../x\t{self.home}\tro\nDownload\t{self.home}\tro\n"
        )
        mounts = wgapps_mounts("mount_shares", self.env)
        self.assertEqual(
            set(mounts),
            {
                "/data/media/0/Host",
                "/vendor/etc/init/wgapps-shares.rc",
                "/vendor/bin/wgapps-shares.sh",
            },
        )

    def fake_tools(self):
        """podman and setfacl stand-ins that record what they are asked."""
        tools = self.home / "tools"
        tools.mkdir()
        log = self.home / "acl.log"
        (tools / "podman").write_text('#!/bin/sh\necho "podman $*" >>' + str(log) + "\n")
        (tools / "setfacl").write_text('#!/bin/sh\necho "setfacl $*" >>' + str(log) + "\n")
        for tool in ("podman", "setfacl"):
            (tools / tool).chmod(0o755)
        return {**self.env, "PATH": f"{tools}:/usr/local/bin:/usr/bin:/bin"}, log

    def test_each_share_gets_the_acl_entries_its_mode_needs_and_loses_them_on_remove(self):
        env, log = self.fake_tools()
        work = self.folder("Work")
        tunes = self.folder("Tunes")
        for args in (("add", str(work), "Work", "--rw"), ("add", str(tunes), "Tunes")):
            self.assertEqual(wgapps_call(env, "cmd_share", *args).returncode, 0)
        done = wgapps_call(env, "mount_shares")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = log.read_text()
        gid = self.group_id(text)
        # read-write: read and write, plus a default entry for what is made later; read-only: list
        self.assertIn(f"setfacl -m g:{gid}:rwx -d -m g:{gid}:rwx {work}", text)
        self.assertIn(f"setfacl -m g:{gid}:rx {tunes}", text)
        # the built-in folder also belongs to the group
        self.assertIn(f"podman unshare chgrp 1023 {self.home / 'Android-share'}", text)
        log.write_text("")
        done = wgapps_call(env, "cmd_share", "remove", "Tunes")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = log.read_text()
        self.assertIn(f"setfacl -x g:{gid} {tunes}", text)
        self.assertIn(f"setfacl -d -x g:{gid} {tunes}", text)

    @staticmethod
    def group_id(text):
        for line in text.splitlines():
            if line.startswith("setfacl -m g:"):
                return line.split("g:")[1].split(":")[0]
        raise AssertionError(text)

    def test_the_usage_and_dispatch_exist(self):
        text = (pathlib.Path(__file__).resolve().parent.parent / "bin/wgapps").read_text()
        self.assertIn("share [add <path> [name] [--rw]|remove <name>|idmap-setup", text)
        self.assertIn('share) cmd_share "$@" ;;', text)
        self.assertNotEqual(self.share("nonsense").returncode, 0)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class IdmapShareTests(unittest.TestCase):
    """The optional idmapped mounts (wgapps share idmap-setup): the parts that need no root."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = pathlib.Path(tmp.name).resolve()
        self.base = self.home / ".local/share/waydroid-gapps"
        self.base.mkdir(parents=True)
        self.mountinfo = self.home / "mountinfo"
        self.mountinfo.write_text("20 1 8:8 / / rw - ext4 /dev/sda8 rw\n")
        self.env = {
            "HOME": str(self.home),
            "WGAPPS_BASE": str(self.base),
            "WGAPPS_MOUNTINFO": str(self.mountinfo),
        }

    def call(self, function, *args):
        return wgapps_call(self.env, function, *args)

    def mount(self, name):
        target = self.base / "idmapped" / name
        target.mkdir(parents=True, exist_ok=True)
        with self.mountinfo.open("a") as handle:
            handle.write(f"99 20 8:8 /x {target.resolve()} rw - ext4 /dev/sda8 rw\n")
        return target

    def test_a_container_id_becomes_the_host_id_of_its_range(self):
        uid_map = self.home / "uid_map"
        uid_map.write_text("         0       1000          1\n         1     100000      65536\n")
        self.assertEqual(self.call("idmap_host_id", "0", str(uid_map)).stdout.strip(), "1000")
        self.assertEqual(self.call("idmap_host_id", "10144", str(uid_map)).stdout.strip(), "110143")
        self.assertEqual(self.call("idmap_host_id", "1023", str(uid_map)).stdout.strip(), "101022")

    def test_the_boot_unit_maps_your_ids_to_androids_for_every_share(self):
        work = self.home / "Work"
        work.mkdir()
        self.call("cmd_share", "add", str(work), "Work", "--rw")
        unit = self.call("idmap_unit", "110143", "110143").stdout
        uid_gid = f"{__import__('os').getuid()} 110143 {__import__('os').getgid()} 110143"
        base = self.base
        host = f'ExecStart=/etc/wgapps/wgapps-idmap-mount "{self.home}/Android-share"'
        self.assertIn(f'{host} "{base}/idmapped/Host" {uid_gid}', unit)
        self.assertIn(f'"{work}" "{base}/idmapped/Work" {uid_gid}', unit)
        self.assertIn(
            f'ExecStop=/etc/wgapps/wgapps-idmap-mount --unmount "{base}/idmapped/Work"', unit
        )
        self.assertIn("Type=oneshot\nRemainAfterExit=yes", unit)
        self.assertIn("WantedBy=multi-user.target", unit)

    def test_an_idmapped_mount_is_what_gets_bound_into_android_when_it_exists(self):
        before = wgapps_mounts("mount_shares", self.env)
        self.assertEqual(before["/data/media/0/Host"][0], str(self.home / "Android-share"))
        target = self.mount("Host")
        after = wgapps_mounts("mount_shares", self.env)
        self.assertEqual(after["/data/media/0/Host"], (str(target), "rw"))

    def test_a_directory_that_is_not_in_the_mount_table_is_not_used(self):
        (self.base / "idmapped/Host").mkdir(parents=True)
        mounts = wgapps_mounts("mount_shares", self.env)
        self.assertEqual(mounts["/data/media/0/Host"][0], str(self.home / "Android-share"))

    def test_the_helper_leaves_idmapped_shares_alone(self):
        share = __import__("helpers").load("wgapps-share")
        (self.home / "Android-share").mkdir()
        self.assertEqual(
            share.rw_shares(self.base, self.home, str(self.mountinfo)),
            [(self.home / "Android-share", True)],
        )
        self.mount("Host")
        self.assertEqual(share.rw_shares(self.base, self.home, str(self.mountinfo)), [])

    def test_setup_needs_android_running_and_status_says_what_each_share_uses(self):
        done = self.call("cmd_share", "idmap-setup")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("start Android first", done.stderr)
        self.assertNotEqual(self.call("cmd_share", "idmap-remove").returncode, 0)
        status = self.call("cmd_share", "idmap-status").stdout
        self.assertIn("idmapped mounts: not set up", status)
        self.assertIn("Host\trw\tACL and helper", status)
        self.mount("Host")
        self.assertIn("Host\trw\tidmapped", self.call("cmd_share", "idmap-status").stdout)


if __name__ == "__main__":
    unittest.main()
