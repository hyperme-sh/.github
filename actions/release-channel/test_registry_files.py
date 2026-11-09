import io
import os
import tarfile
import unittest
import zipfile
from unittest.mock import patch

import release


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.repo = "hyperme-sh/oracles"
        self.workflow = ".github/workflows/package.yml"
        self.revision = "a" * 40
        self.digest = "sha256:" + "b" * 64
        repo = {"full_name": self.repo}
        self.run = {"repository": repo, "head_repository": repo, "head_sha": self.revision,
                    "head_branch": "main", "event": "push", "path": self.workflow,
                    "status": "completed", "conclusion": "success", "run_attempt": 2}
        self.jobs = {"total_count": 1, "jobs": [{"name": "Qualified OCI " + self.digest,
                                                 "conclusion": "success"}]}

    def test_different_original_digest_refused_before_pull(self):
        with patch.object(release, "api", side_effect=[self.run, self.jobs]), \
                patch.object(release.subprocess, "run") as docker:
            with self.assertRaisesRegex(ValueError, "digest changed"):
                release.registry_files(self.repo, self.workflow, self.revision, 123, 2, "sha256:"+"c"*64)
            docker.assert_not_called()

    def test_exact_bytes_from_recorded_digest_without_starting_image(self):
        zipbytes = io.BytesIO()
        with zipfile.ZipFile(zipbytes, "w") as packages:
            packages.writestr("package.whl", b"qualified wheel")
        def docker(args, **kwargs):
            if args[1] == "create":
                self.assertIn("ghcr.io/hyperme-sh/oracles/runtime@"+self.digest, args)
                return release.subprocess.CompletedProcess(args, 0, stdout=b"container-id")
            if args[1] == "cp":
                entry = tarfile.TarInfo("tested-dist.zip")
                entry.size = len(zipbytes.getvalue())
                zipbytes.seek(0)
                with tarfile.open(fileobj=kwargs["stdout"], mode="w") as archive:
                    archive.addfile(entry, zipbytes)
            self.assertIn(args[1], ("login", "pull", "cp", "rm"))
        with patch.object(release, "api", side_effect=[self.run, self.jobs]), \
                patch.dict(os.environ, GH_TOKEN="fixture", GITHUB_ACTOR="fixture"), \
                patch.object(release.subprocess, "run", side_effect=docker):
            digest, attempt, files = release.registry_files(self.repo, self.workflow, self.revision, 123)
        self.assertEqual((digest, attempt, files), (self.digest, 2, {"package.whl": b"qualified wheel"}))
