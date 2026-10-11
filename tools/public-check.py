"""Check publishable source and relative Markdown links, excluding generated output."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.terraform', '.runtime', '.build', 'dist', 'build', '__pycache__', '.venv'}
errors = []
for path in ROOT.rglob('*'):
    if not path.is_file() or any(part in EXCLUDED or part.endswith('.egg-info') for part in path.relative_to(ROOT).parts): continue
    if path.suffix in {'.tfstate', '.tfplan', '.tfvars', '.sqlite', '.pem'} or path.name in {'credentials', 'config.json', 'deployment.json', '.env'}:
        errors.append('Private file: ' + str(path.relative_to(ROOT)))
        continue
    try: source = path.read_text(encoding='utf-8')
    except UnicodeDecodeError: continue
    # Detect concrete AWS keys and secrets, never print their values.
    if re.search(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}', source):
        errors.append('Possible secret: ' + str(path.relative_to(ROOT)))
    if path.suffix == '.md':
        for link in re.findall(r'\]\(([^)]+)\)', source):
            if ':' in link or link.startswith('#'): continue
            target = link.split('#')[0]
            if target and not (path.parent / target).exists(): errors.append('Broken link: ' + str(path.relative_to(ROOT)) + ' -> ' + target)
if errors: raise SystemExit('\n'.join(errors))
print('Public source and local documentation links passed.')
