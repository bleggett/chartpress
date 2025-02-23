import json
import sys
from subprocess import PIPE, run
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from chartpress import PRERELEASE_PREFIX


def test_list_images(git_repo):
    p = run(
        [sys.executable, "-m", "chartpress", "--list-images"],
        check=True,
        capture_output=True,
    )
    stdout = p.stdout.decode("utf8").strip()
    # echo stdout/stderr for debugging
    sys.stderr.write(p.stderr.decode("utf8", "replace"))
    sys.stdout.write(stdout)

    images = stdout.strip().splitlines()
    assert len(images) == 1
    # split hash_suffix which will be different every run
    pre_hash, hash_suffix = images[0].rsplit(".", 1)
    assert pre_hash == f"testchart/testimage:0.0.1-{PRERELEASE_PREFIX}.1"

    p = run(
        ["git", "status", "--porcelain"],
        check=True,
        capture_output=True,
    )
    assert not p.stdout, "--list-images should not make changes!"


def _get_architectures_from_manifest(name, tag):
    # https://docs.docker.com/registry/spec/manifest-v2-2/
    # To debug this with curl:
    # curl -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json' localhost:5000/v2/{name}/manifests/{tag}
    MANIFEST_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
    MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"

    r = Request(
        f"http://localhost:5000/v2/{name}/manifests/{tag}",
        headers={"Accept": f"{MANIFEST_LIST}, {MANIFEST}"},
    )
    with urlopen(r) as h:
        d = json.load(h)

    assert d["mediaType"] in (MANIFEST_LIST, MANIFEST)
    if d["mediaType"] == MANIFEST_LIST:
        assert "manifests" in d
        architectures = sorted(
            manifest["platform"]["architecture"] for manifest in d["manifests"]
        )
    else:
        assert "manifests" not in d
        architectures = None

    return architectures


@pytest.mark.registry
def test_buildx(git_repo, capfd):
    tag = f"1.2.3-{uuid4()}"
    p = run(
        [
            sys.executable,
            "-m",
            "chartpress",
            "--builder",
            "docker-buildx",
            "--platform",
            "linux/amd64",
            "--platform",
            "linux/arm64",
            "--platform",
            "linux/ppc64le",
            "--push",
            "--image-prefix",
            "localhost:5000/test-buildx/",
            "--tag",
            tag,
        ],
        check=True,
    )
    stdout, stderr = capfd.readouterr()
    # echo stdout/stderr for debugging
    sys.stderr.write(stderr)
    sys.stdout.write(stdout)

    # Note: Parsing stderr for these logs may be fragile. We could probably omit
    # it and just verify the registry manifests instead.

    assert "[linux/amd64 1/1] FROM docker.io/library/alpine@" in stderr
    assert "[linux/arm64 1/1] FROM docker.io/library/alpine@" in stderr
    assert "[linux/ppc64le 1/1] FROM docker.io/library/alpine@" in stderr

    # If there's only one platform it doesn't appear in the output logs
    # assert "[linux/amd64 1/1] FROM docker.io/library/busybox@" in stderr
    assert "[1/1] FROM docker.io/library/busybox@" in stderr
    assert "[linux/arm64 1/1] FROM docker.io/library/busybox@" not in stderr
    assert "[linux/ppc64le 1/1] FROM docker.io/library/busybox@" not in stderr

    assert f"pushing manifest for localhost:5000/test-buildx/testimage:{tag}" in stderr
    assert f"pushing manifest for localhost:5000/test-buildx/amd64only:{tag}" in stderr

    with urlopen("http://localhost:5000/v2/test-buildx/testimage/tags/list") as h:
        d = json.load(h)
    assert d["name"] == "test-buildx/testimage"
    assert tag in d["tags"]

    architectures = _get_architectures_from_manifest("test-buildx/testimage", tag)
    assert architectures == ["amd64", "arm64", "ppc64le"]

    architectures = _get_architectures_from_manifest("test-buildx/amd64only", tag)
    assert architectures is None
