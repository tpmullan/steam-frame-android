import unittest

from helpers import load

ota = load("wgapps-ota")

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def entry(build, kind, sha):
    name = f"lineage-20.0-{build}-{kind}-waydroid_arm64_only-x.zip"
    return {"filename": name, "id": sha, "url": f"https://example.invalid/{name}/download"}


SYSTEM = {
    "response": [
        entry("20260927", "GAPPS", SHA_A),
        entry("20260403", "GAPPS", SHA_B),
        entry("20260101", "GAPPS", SHA_C),
    ]
}
VENDOR = {
    "response": [
        entry("20260927", "MAINLINE", SHA_B),
        entry("20260403", "MAINLINE", SHA_C),
    ]
}


class ResolveTests(unittest.TestCase):
    def test_newest_build_present_in_both_indexes(self):
        build, sysent, venent = ota.resolve(SYSTEM, VENDOR)
        self.assertEqual(build, "20260927")
        self.assertEqual(sysent["id"], SHA_A)
        self.assertEqual(venent["id"], SHA_B)

    def test_pinned_build(self):
        build, sysent, _ = ota.resolve(SYSTEM, VENDOR, "20260403")
        self.assertEqual((build, sysent["id"]), ("20260403", SHA_B))

    def test_pinned_build_missing_from_vendor_is_an_error(self):
        with self.assertRaises(ValueError):
            ota.resolve(SYSTEM, VENDOR, "20260101")

    def test_rows_without_https_or_sha256_are_ignored(self):
        bad = {
            "response": [
                {**entry("20261001", "GAPPS", SHA_A), "url": "http://example.invalid/x"},
                {**entry("20261002", "GAPPS", "not-a-hash")},
            ]
        }
        with self.assertRaises(ValueError):
            ota.resolve(bad, VENDOR)


if __name__ == "__main__":
    unittest.main()
