#!/usr/bin/env python3
"""CI-only restoration. Does not run untrusted PR code or restore arbitrary paths."""
import json
import os
from pathlib import Path
import subprocess
import sys
from ntv.common import read_json, write_json, split_episodes, restore_pending_episodes


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    if sys.argv[1] == 'restore':
        runs = json.loads(gh('api', f'repos/{repo}/actions/workflows/ntv-update.yml/runs?status=success&per_page=10'))
        for run in runs['workflow_runs']:
            artifacts = json.loads(gh('api', f"repos/{repo}/actions/runs/{run['id']}/artifacts"))
            if any(a['name']=='ntv-cache' and not a['expired'] for a in artifacts['artifacts']):
                subprocess.run(['gh','run','download',str(run['id']),'--name','ntv-cache','--dir','.cache/ntv'], check=True)
                return
        print('No prior cache; starting with an empty cache.')
    elif sys.argv[1] == 'pending':
        prs = json.loads(gh('pr','list','--head','automation/ntv-data','--state','open','--json','number,headRefOid'))
        if not prs:
            return
        subprocess.run(['git','fetch','origin','automation/ntv-data'],check=True)
        base = subprocess.check_output(['git','merge-base','HEAD','FETCH_HEAD'],text=True).strip()
        # Restore only generated data files from the existing automation PR; use current main code.
        names = subprocess.check_output(['git','ls-tree','-r','--name-only','FETCH_HEAD'],text=True).splitlines()
        for name in names:
            if name == 'src/data/episodes-ntv.json':
                # Migration from an unmerged PR produced by the former split-file updater.
                path = Path('src/data/episodes.json')
                current = read_json(path)
                legacy, _ = split_episodes(current)
                pending = json.loads(subprocess.check_output(['git','show','FETCH_HEAD:'+name]))
                original = subprocess.run(['git','show',base+':'+name],capture_output=True)
                before = json.loads(original.stdout) if original.returncode == 0 else []
                write_json(path, restore_pending_episodes(current, legacy + pending, legacy + before))
                continue
            if name == 'src/data/episodes.json' or name.startswith('data/ntv/generated/'):
                path = Path(name)
                pending = subprocess.check_output(['git','show','FETCH_HEAD:'+name])
                original = subprocess.run(['git','show',base+':'+name],capture_output=True)
                base_content = original.stdout if original.returncode == 0 else None
                current = path.read_bytes() if path.exists() else None
                if name == 'src/data/episodes.json':
                    write_json(path, restore_pending_episodes(json.loads(current), json.loads(pending), json.loads(base_content)))
                    continue
                if current != base_content and pending != base_content and current != pending:
                    raise ValueError('Generated data changed on both main and the pending PR: ' + name)
                if pending == base_content:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(pending)
    else:
        raise ValueError('Unknown command')


if __name__ == '__main__':
    main()
