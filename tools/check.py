"""Credential-free library checks. Production plans belong to environment repositories."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-only', action='store_true')
    args = parser.parse_args()
    environment = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT / 'components/moderation/src'), str(ROOT / 'runtime/comments')])}
    def run(command, directory=ROOT): subprocess.run(command, cwd=directory, env=environment, check=True)
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'components/moderation/tests', '-q'])
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'runtime/comments/tests', '-q'])
    run([sys.executable, 'tools/public-check.py'])
    if not args.python_only:
        run(['terraform', 'fmt', '-check', '-recursive'])
        for directory in sorted((ROOT / 'modules').iterdir()) + sorted((ROOT / 'examples').iterdir()):
            if not (directory / 'main.tf').exists(): continue
            run(['terraform', 'init', '-backend=false', '-input=false', '-no-color'], directory)
            if directory.parent.name == 'examples': run(['terraform', 'validate', '-no-color'], directory)
            if (directory / 'tests').is_dir(): run(['terraform', 'test', '-no-color'], directory)


if __name__ == '__main__': main()
