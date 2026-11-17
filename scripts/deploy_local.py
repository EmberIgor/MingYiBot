"""Build and deploy this checkout using an existing local Compose runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(*args, capture=False):
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    args = parser.parse_args()
    runtime = args.runtime_dir.resolve(strict=True)
    for name in (".env", "data", "logs", "docker-compose.yml"):
        if not (runtime / name).exists():
            parser.error(f"Existing runtime required: {runtime / name}")
    mounts = json.loads(
        run(
            "docker",
            "inspect",
            "mingyi-bot",
            "--format",
            "{{json .Mounts}}",
            capture=True,
        )
    )
    current = {
        m["Destination"]: Path(m["Source"]).resolve()
        for m in mounts
        if m["Type"] == "bind"
    }
    for name in (".env", "data", "logs"):
        if current.get(f"/app/{name}") != (runtime / name).resolve():
            parser.error(f"Runtime does not match current container mount: {name}")
    version = run("git", "rev-parse", "HEAD", capture=True)
    if run("git", "status", "--porcelain", capture=True):
        parser.error("Commit the reviewed checkout before deploying")
    compose = runtime / "docker-compose.yml"
    run(
        "docker",
        "compose",
        "--project-directory",
        str(runtime),
        "-f",
        str(ROOT / "docker-compose.yml"),
        "config",
        "--quiet",
    )
    before = compose.read_bytes()
    old_id = run(
        "docker", "inspect", "mingyi-bot", "--format", "{{.Image}}", capture=True
    )
    # Build before touching the current service. Keep only one rollback alias.
    run(
        "docker",
        "build",
        "--build-arg",
        f"MINGYI_VERSION={version}",
        "-t",
        "mingyibot:local-candidate",
        ".",
    )
    if compose.read_bytes() != before:
        raise RuntimeError(
            "Runtime Compose changed during build; no deployment performed"
        )
    run("docker", "tag", old_id, "mingyibot:previous")
    shutil.copy2(compose, runtime / "docker-compose.yml.previous")
    staged = runtime / "docker-compose.yml.new"
    try:
        shutil.copyfile(ROOT / "docker-compose.yml", staged)
        os.replace(staged, compose)
    finally:
        staged.unlink(missing_ok=True)
    run("docker", "tag", "mingyibot:local-candidate", "mingyibot:local")
    run(
        "docker",
        "compose",
        "-p",
        "mingyibot",
        "-f",
        str(compose),
        "up",
        "-d",
        "--no-deps",
        "--no-build",
        "--pull",
        "never",
        "--wait",
        "--wait-timeout",
        "90",
        "bot",
    )
    # Inspect only public deployment state, never the complete environment.
    actual = run(
        "docker",
        "exec",
        "mingyi-bot",
        "python",
        "-c",
        "import os; print(os.environ.get('MINGYI_VERSION', 'unknown'))",
        capture=True,
    )
    health = run(
        "docker",
        "inspect",
        "mingyi-bot",
        "--format",
        "{{.State.Health.Status}}",
        capture=True,
    )
    if actual != version or health != "healthy":
        raise RuntimeError(
            f"Deployment verification failed: version={actual} health={health}"
        )
    print(json.dumps(dict(version=actual, health=health, image="mingyibot:local")))


if __name__ == "__main__":
    main()
