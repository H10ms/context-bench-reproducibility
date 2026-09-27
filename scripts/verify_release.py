"""Verify public release bytes and frozen inputs; standard library only."""
from pathlib import Path
import ast
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / 'experiments/gpt6-sol-vs-luna-swbench-v1'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify():
    entries = (ROOT / 'SHA256SUMS').read_text(encoding='utf-8').splitlines()
    for line in entries:
        digest, name = line.split('  ', 1)
        path = ROOT / name
        if not path.is_file() or sha(path) != digest:
            raise ValueError(f'Checksum mismatch: {name}')
    freeze = json.loads((EXP / 'EXPERIMENT_FREEZE.json').read_text())
    manifest = [json.loads(x) for x in (EXP / 'manifest.jsonl').read_text().splitlines()]
    canonical = ''.join(json.dumps(x, sort_keys=True) + '\n' for x in manifest).encode()
    if hashlib.sha256(canonical).hexdigest() != freeze['manifest_hash']:
        raise ValueError('Canonical manifest hash mismatch')
    for name, digest in freeze['config_hashes'].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f'Frozen config mismatch: {name}')
    tree = ast.parse((ROOT / 'context_bench/runner.py').read_text(encoding='utf-8'))
    wrapper = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'PROMPT_WRAPPER' for t in n.targets))
    if hashlib.sha256(wrapper.encode()).hexdigest() != freeze['prompt_wrapper_sha256']:
        raise ValueError('Frozen prompt wrapper mismatch')
    provenance = json.loads((ROOT / 'RELEASE_PROVENANCE.json').read_text())
    for name, digest in provenance['source_code_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f'Source snapshot mismatch: {name}')
    print(f'PASS: {len(entries)} release files; frozen configs, prompt and canonical manifest')

if __name__ == '__main__':
    verify()
