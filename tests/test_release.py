import gzip
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import sfa_release as rel  # noqa: E402

GOOD_FILES = {name: b"content\n" for name in rel.REQUIRED_FILES}


class VersionTests(unittest.TestCase):
    def test_highest_orders_numerically(self):
        self.assertEqual(rel.highest(["v0.1.9", "v0.1.10", "v0.1.2"]), "v0.1.10")
        self.assertEqual(rel.highest(["v0.1.0", "v0.2.0", "v0.1.9"]), "v0.2.0")
        self.assertEqual(rel.highest(["v0.9.9", "v1.0.0"]), "v1.0.0")

    def test_highest_ignores_non_version_tags(self):
        self.assertEqual(rel.highest(["latest", "v0.1.0", "v0.2", "main"]), "v0.1.0")
        self.assertIsNone(rel.highest(["latest"]))

    def test_latest_moves_on_higher_or_equal_only(self):
        self.assertTrue(rel.is_latest("v0.2.0", ["v0.1.0"]))
        self.assertTrue(rel.is_latest("v0.2.0", ["v0.1.0", "v0.2.0"]))
        self.assertFalse(rel.is_latest("v0.1.1", ["v0.2.0"]))
        self.assertTrue(rel.is_latest("v0.1.0", []))


class PatternTests(unittest.TestCase):
    def test_ci_hosts_cluster_names_and_deny_list(self):
        with tempfile.NamedTemporaryFile("w", suffix=".deny") as deny:
            deny.write("# comment\n\n\\b192\\.168\\.[0-9]+\\.[0-9]+\\b\n")
            deny.flush()
            env = {"CI_SERVER_HOST": "git.internal.test", "CI_REGISTRY": "registry.internal.test"}
            pat = rel.internal_patterns(env, deny.name)
        for leak in (
            b"https://git.internal.test/x",
            b"registry.internal.test/a/b",
            b"app.example.svc.cluster.local",
            b"frame." + b"tun" + b".example",
            b"host 192.168.1" + b".20",
        ):
            self.assertIsNotNone(pat.search(leak), leak)
        for clean in (b"ghcr.io/tpmullan/steam-frame-android", b"172.20.0.2", b"gitXinternal.test"):
            self.assertIsNone(pat.search(clean), clean)


@unittest.skipUnless(shutil.which("git"), "needs git")
class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.public = str(root / "public.git")
        self.dev = str(root / "dev")
        self.deny = root / "deny"
        self.deny.write_text("# test deny-list\ninternal\\.example\n")
        subprocess.run(["git", "init", "-q", "--bare", self.public], check=True)
        subprocess.run(["git", "init", "-q", self.dev], check=True)
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.dev, check=True, capture_output=True, text=True
        ).stdout.strip()

    def pub(self, *args):
        return subprocess.run(
            ["git", f"--git-dir={self.public}", *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, name, content):
        pathlib.Path(self.dev, name).write_text(content)
        self.git("add", name)
        self.git("commit", "-q", "-m", f"dev change {name}")

    def release(self, version):
        return rel.release(version, "HEAD", self.public, self.deny, cwd=self.dev)

    def test_release_sequence(self):
        self.commit("file.txt", "one\n")
        self.release("v0.1.0")
        self.assertEqual(
            self.pub("rev-parse", "v0.1.0^{tree}"), self.git("rev-parse", "HEAD^{tree}")
        )
        self.assertEqual(self.pub("rev-parse", "main"), self.pub("rev-parse", "v0.1.0"))
        self.assertEqual(self.pub("rev-list", "--count", "main"), "1")
        self.assertEqual(self.pub("log", "-1", "--format=%s", "main"), "Release v0.1.0")

        self.commit("file.txt", "two\n")
        self.release("v0.2.0")
        self.assertEqual(self.pub("rev-parse", "main"), self.pub("rev-parse", "v0.2.0"))
        self.assertEqual(self.pub("rev-parse", "main^"), self.pub("rev-parse", "v0.1.0"))

        self.commit("file.txt", "hotfix\n")
        result = self.release("v0.1.1")
        self.assertFalse(result["advance_main"])
        self.assertEqual(self.pub("rev-parse", "main"), self.pub("rev-parse", "v0.2.0"))
        self.assertEqual(
            self.pub("rev-parse", "v0.1.1^{tree}"), self.git("rev-parse", "HEAD^{tree}")
        )

    def test_shared_history_publishes_the_commit_itself(self):
        self.commit("file.txt", "one\n")
        self.git("push", "-q", self.public, "HEAD:refs/heads/main")
        self.commit("file.txt", "two\n")
        head = self.git("rev-parse", "HEAD")
        self.release("v0.4.0")
        self.assertEqual(self.pub("rev-parse", "main"), head)
        self.assertEqual(self.pub("rev-parse", "v0.4.0^{commit}"), head)
        self.assertEqual(self.pub("rev-list", "--count", "main"), "2")

    def test_shared_history_checks_new_commit_messages(self):
        self.commit("file.txt", "one\n")
        self.git("push", "-q", self.public, "HEAD:refs/heads/main")
        pathlib.Path(self.dev, "file.txt").write_text("two\n")
        self.git("commit", "-q", "-am", "talks to host.internal.example")
        with self.assertRaises(rel.ReleaseError):
            self.release("v0.5.0")

    def test_rerun_same_version_republishes(self):
        self.commit("file.txt", "three\n")
        self.release("v0.3.0")
        before = self.pub("rev-parse", "main")
        self.release("v0.3.0")
        self.assertEqual(self.pub("rev-parse", "main"), before)
        self.assertEqual(self.pub("rev-parse", "v0.3.0"), before)

        self.commit("file.txt", "four\n")
        self.release("v0.3.0")
        self.assertEqual(
            self.pub("rev-parse", "v0.3.0^{tree}"), self.git("rev-parse", "HEAD^{tree}")
        )
        self.assertEqual(self.pub("rev-parse", "main"), self.pub("rev-parse", "v0.3.0"))

    def test_deny_list_hit_publishes_nothing(self):
        self.commit("file.txt", "one\n")
        self.release("v0.1.0")
        main_before = self.pub("rev-parse", "main")
        self.commit("leak.txt", "host=internal.example\n")
        with self.assertRaisesRegex(rel.ReleaseError, "deny-list"):
            self.release("v0.2.0")
        self.assertEqual(self.pub("rev-parse", "main"), main_before)
        self.assertNotIn("v0.2.0", self.pub("tag", "--list"))

    def test_dry_run_pushes_nothing(self):
        self.commit("file.txt", "one\n")
        rel.release("v0.1.0", "HEAD", self.public, self.deny, dry_run=True, cwd=self.dev)
        self.assertEqual(self.pub("tag", "--list"), "")


def _write_blob(layout, data):
    digest = hashlib.sha256(data).hexdigest()
    path = layout / "blobs" / "sha256" / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"sha256:{digest}", len(data)


def make_layout(root, files, platform=("linux", "arm64"), labels=None, attestation=False):
    """Write a minimal OCI image layout with one gzip layer holding FILES."""
    layout = pathlib.Path(root)
    (layout / "oci-layout").parent.mkdir(parents=True, exist_ok=True)
    (layout / "oci-layout").write_text('{"imageLayoutVersion": "1.0.0"}')
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        dirs = sorted({str(pathlib.PurePosixPath(n).parent) for n in files} - {"."})
        for d in dirs:
            info = tarfile.TarInfo(d + "/")
            info.type = tarfile.DIRTYPE
            tar.addfile(info)
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    layer_digest, layer_size = _write_blob(layout, gzip.compress(buf.getvalue()))
    config = {
        "os": platform[0],
        "architecture": platform[1],
        "config": {"Labels": labels or {}},
        "rootfs": {"type": "layers", "diff_ids": []},
    }
    config_digest, config_size = _write_blob(layout, json.dumps(config).encode())
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": config_digest,
            "size": config_size,
        },
        "layers": [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": layer_digest,
                "size": layer_size,
            }
        ],
    }
    m_digest, m_size = _write_blob(layout, json.dumps(manifest).encode())
    entries = [
        {"mediaType": manifest["mediaType"], "digest": m_digest, "size": m_size},
    ]
    if attestation:
        entries.append(
            {
                "mediaType": manifest["mediaType"],
                "digest": m_digest,
                "size": m_size,
                "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
            }
        )
    index = {"schemaVersion": 2, "manifests": entries}
    (layout / "index.json").write_text(json.dumps(index))
    return layout


class CheckLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pat = rel.internal_patterns({"CI_SERVER_HOST": "git.internal.test"})

    def tearDown(self):
        self.tmp.cleanup()

    def layout(self, files=None, **kw):
        return make_layout(self.tmp.name, GOOD_FILES if files is None else files, **kw)

    def assert_rejected(self, pattern, **kw):
        with self.assertRaisesRegex(rel.ReleaseError, pattern):
            rel.check_layout(self.layout(**kw), self.pat)

    def test_good_image_passes(self):
        summary = rel.check_layout(self.layout(), self.pat)
        self.assertIn("linux/arm64", summary)

    def test_attestation_rejected(self):
        self.assert_rejected("attestation", attestation=True)

    def test_internal_name_in_a_file_rejected(self):
        files = {**GOOD_FILES, "wgapps/bin/wgapps": b"url=https://git.internal.test/x\n"}
        self.assert_rejected("internal names", files=files)

    def test_internal_name_in_labels_rejected(self):
        self.assert_rejected(
            "internal names",
            labels={"org.opencontainers.image.source": "https://git.internal.test"},
        )

    def test_file_outside_wgapps_rejected(self):
        self.assert_rejected("outside /wgapps", files={**GOOD_FILES, "etc/passwd": b"x\n"})

    def test_android_artifacts_rejected(self):
        self.assert_rejected("must not ship", files={**GOOD_FILES, "wgapps/app.apk": b"x"})
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        files = {**GOOD_FILES, "wgapps/overrides/vendor/etc/vintf/manifest.xml": b"<manifest/>"}
        self.assert_rejected("must not ship", files=files)

    def test_missing_file_rejected(self):
        files = {k: v for k, v in GOOD_FILES.items() if k != "wgapps/LICENSE"}
        self.assert_rejected("missing files: wgapps/LICENSE", files=files)

    def test_wrong_platform_rejected(self):
        self.assert_rejected("platform is linux/amd64", platform=("linux", "amd64"))

    def test_internal_name_in_registry_manifest_rejected(self):
        with self.assertRaisesRegex(rel.ReleaseError, "internal names"):
            rel.check_layout(self.layout(), self.pat, (b'{"x": "git.internal.test"}',))


class RegistryManifestTests(unittest.TestCase):
    def test_single_manifest_accepted(self):
        rel.check_registry_manifest('{"mediaType": "application/vnd.oci.image.manifest.v1+json"}')

    def test_index_rejected(self):
        with self.assertRaisesRegex(rel.ReleaseError, "single image manifest"):
            rel.check_registry_manifest('{"mediaType": "application/vnd.oci.image.index.v1+json"}')


class CheckImageArchiveTests(unittest.TestCase):
    def test_oci_archive_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = make_layout(os.path.join(tmp, "layout"), GOOD_FILES)
            archive = os.path.join(tmp, "image.tar")
            with tarfile.open(archive, "w") as tar:
                for item in layout.iterdir():
                    tar.add(item, arcname=item.name)
            summary = rel.check_image(f"oci-archive:{archive}", rel.internal_patterns({}))
            self.assertIn("linux/arm64", summary)


if __name__ == "__main__":
    unittest.main()
