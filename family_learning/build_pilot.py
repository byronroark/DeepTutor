"""Build a source overlay using a data-free temporary Docker context."""

from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["npm", "run", "build"], cwd=root / "web", check=True)
    with tempfile.TemporaryDirectory(prefix="family-learning-image-") as directory:
        target = Path(directory)
        shutil.copytree(
            root / "deeptutor",
            target / "deeptutor",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(root / "web/.next/standalone", target / "web")
        shutil.copytree(root / "web/.next/static", target / "web/.next/static", dirs_exist_ok=True)
        shutil.copytree(root / "web/public", target / "web/public", dirs_exist_ok=True)
        shutil.copy2(root / "family_learning/Dockerfile.acceptance", target / "Dockerfile")
        subprocess.run(
            ["docker", "build", "-t", "family-deeptutor:acceptance", str(target)], check=True
        )


if __name__ == "__main__":
    main()
