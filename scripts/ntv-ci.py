#!/usr/bin/env python3
"""Restore collection caches and push verified generated data to the default branch."""
import json
import os
import subprocess
import sys

DATA_PATHS = ('src/data/episodes.json', 'data/ntv/generated/decisions.json', 'data/ntv/generated/report.md')


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def publish(branch):
    if git('branch', '--show-current') != branch:
        raise ValueError('Default branch must be checked out before publishing data')
    if git('diff', '--cached', '--name-only'):
        raise ValueError('Unexpected staged changes before publishing data')
    subprocess.run(['git', 'add', '--', *DATA_PATHS], check=True)
    if not git('diff', '--cached', '--name-only'):
        print('No generated data changes; nothing to push.')
        return False
    subprocess.run(['git', 'fetch', 'origin', branch], check=True)
    if git('rev-parse', 'HEAD') != git('rev-parse', 'FETCH_HEAD'):
        raise ValueError('Default branch advanced during collection; retry using the latest code and data')
    subprocess.run(['git', 'config', 'user.name', 'github-actions[bot]'], check=True)
    subprocess.run(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], check=True)
    subprocess.run(['git', 'commit', '-m', 'data: update NTV broadcast records'], check=True)
    # A concurrent push is rejected normally. Never force-push or rebase untested changes.
    subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/' + branch], check=True)
    print('Published generated data: ' + git('rev-parse', 'HEAD'))
    return True


def main():
    if sys.argv[1] == 'restore':
        repo = os.environ['GITHUB_REPOSITORY']
        runs = json.loads(gh('api', f'repos/{repo}/actions/workflows/ntv-update.yml/runs?status=success&per_page=10'))
        for run in runs['workflow_runs']:
            artifacts = json.loads(gh('api', f"repos/{repo}/actions/runs/{run['id']}/artifacts"))
            if any(a['name']=='ntv-cache' and not a['expired'] for a in artifacts['artifacts']):
                subprocess.run(['gh','run','download',str(run['id']),'--name','ntv-cache','--dir','.cache/ntv'], check=True)
                return
        print('No prior cache; starting with an empty cache.')
    elif sys.argv[1] == 'publish':
        publish(os.environ['NTV_TARGET_BRANCH'])
    else:
        raise ValueError('Unknown command')


if __name__ == '__main__':
    main()
