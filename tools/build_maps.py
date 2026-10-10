"""Build the patched scraper, retaining source checksums and dependency verification."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request
import secrets

import prepare_maps

GO_VERSION = "1.27.1"
GO_SHA256 = "63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445"


def run(args, cwd=None, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def flatten_if_vfs(build, env):
    driver = subprocess.check_output(["docker", "info", "--format", "{{.Driver}}"], env=env, text=True).strip()
    if driver != "vfs":
        return
    # This temporary container is never started and has no customer data volumes.
    name = "iecho-maps-build-" + secrets.token_hex(6)
    archive = build / "verified-maps-flat.tar"
    run(["docker", "create", "--name", name, "iecho/maps:1.18.1-verified"], env=env)
    try:
        run(["docker", "export", name, "-o", str(archive)], env=env)
        with tarfile.open(archive) as tar:
            with tar.extractfile("usr/bin/google-maps-scraper") as binary:
                hasher = hashlib.sha256()
                for chunk in iter(lambda: binary.read(1024 * 1024), b""):
                    hasher.update(chunk)
                digest = hasher.hexdigest()
        if (build / "google-maps-scraper").exists():
            expected = hashlib.sha256((build / "google-maps-scraper").read_bytes()).hexdigest()
            if digest != expected:
                raise RuntimeError("Flattened image binary mismatch")
    finally:
        run(["docker", "rm", name], env=env)
    run(["docker", "image", "rm", "iecho/maps:1.18.1-verified"], env=env)
    run(["docker", "import", "--change", 'ENTRYPOINT ["google-maps-scraper"]', "--change", "ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers PLAYWRIGHT_DRIVER_PATH=/opt/ms-playwright-go DISABLE_TELEMETRY=1", str(archive), "iecho/maps:1.18.1-verified"], env=env)
    archive.unlink()
    print("Flattened verified image for the vfs storage driver.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true", help="Linux amd64: compile in /tmp to conserve Docker disk.")
    args = parser.parse_args()
    prepare_maps.main()
    build = prepare_maps.BUILD
    env = dict(os.environ)
    if args.native:
        archive = build / "go.tar.gz"
        if not archive.exists():
            with urllib.request.urlopen(f"https://go.dev/dl/go{GO_VERSION}.linux-amd64.tar.gz", timeout=120) as response:
                archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != GO_SHA256:
            raise RuntimeError("Official Go checksum mismatch")
        if not (build / "go/bin/go").exists():
            with tarfile.open(archive) as tar:
                for member in tar.getmembers():
                    path = Path(member.name)
                    if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                        raise RuntimeError("Unsafe Go archive")
                tar.extractall(build, filter="data")
        for key, dirname in [("GOCACHE", "go-cache"), ("GOPATH", "go-path"), ("GOMODCACHE", "go-modules"), ("GOTMPDIR", "go-tmp")]:
            target = build / dirname
            target.mkdir(exist_ok=True)
            env[key] = str(target)
        go = str(build / "go/bin/go")
        run([go, "mod", "edit", "-replace", "github.com/gosom/scrapemate=../scrapemate"], build / "maps", env)
        run([go, "mod", "download"], build / "maps", env)
        for package in ["jshttp", "stealth"]:
            run([go, "test", "./adapters/fetchers/" + package, "-run", "^TestIECHO", "-count=1"], build / "scrapemate", env)
        env["CGO_ENABLED"] = "0"
        run([go, "build", "-p", "4", "-mod=readonly", "-buildvcs=false", "-ldflags=-w -s", "-o", str(build / "google-maps-scraper")], build / "maps", env)
        text = (build / "Dockerfile").read_text()
        text = "FROM gosom/" + text.split("FROM gosom/", 1)[1]
        text = text.replace("COPY --from=builder /build/google-maps-scraper", "COPY google-maps-scraper")
        text = text.replace("COPY --from=builder /build/scrapemate/LICENSE", "COPY scrapemate/LICENSE")
        (build / "Dockerfile").write_text(text)
    run(["docker", "build", "--build-arg", "HTTP_PROXY", "--build-arg", "HTTPS_PROXY", "--build-arg", "NO_PROXY", "-t", "iecho/maps:1.18.1-verified", str(build)], env=env)
    flatten_if_vfs(build, env)


if __name__ == "__main__":
    main()
