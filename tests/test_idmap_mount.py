"""wgapps-idmap-mount: the root helper that makes the idmapped bind mount (its pure parts)."""

import pathlib
import struct
import tempfile
import unittest

import helpers

idmap = helpers.load("wgapps-idmap-mount")


class IdmapMountTests(unittest.TestCase):
    def test_the_map_line_names_the_id_on_disk_first_and_the_id_shown_second(self):
        # Verified on a Linux 7.0 kernel: "1000 110143 1" shows 1000's file as 110143's.
        self.assertEqual(idmap.id_map_line(1000, 110143), "1000 110143 1")

    def test_ids_outside_the_valid_range_are_refused(self):
        for bad in (-1, 2**32 - 1, 2**32):
            with self.assertRaises(ValueError):
                idmap.id_map_line(bad, 5)
            with self.assertRaises(ValueError):
                idmap.id_map_line(5, bad)

    def test_the_mount_attribute_asks_for_an_idmap_with_the_user_namespace_fd(self):
        attr = idmap.mount_attr(7)
        self.assertEqual(len(attr), 32)
        self.assertEqual(struct.unpack("QQQQ", attr), (0x00100000, 0, 0, 7))

    def test_a_target_is_found_in_the_mount_table_by_its_real_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp).resolve() / "mapped"
            target.mkdir()
            table = pathlib.Path(tmp) / "mountinfo"
            table.write_text(
                "20 1 8:8 / / rw - ext4 /dev/sda8 rw\n"
                f"99 20 8:8 /x {target} rw,relatime - ext4 /dev/sda8 rw\n"
            )
            self.assertTrue(idmap.is_mounted(str(target), str(table)))
            self.assertFalse(idmap.is_mounted(str(target.parent), str(table)))

    def test_the_arguments_are_checked_before_anything_is_done(self):
        self.assertEqual(idmap.main(["wgapps-idmap-mount"]), 2)
        self.assertEqual(idmap.main(["wgapps-idmap-mount", "a", "b", "1", "2", "3"]), 2)


if __name__ == "__main__":
    unittest.main()
