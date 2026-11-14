#!/usr/bin/env python3
"""Compare fresh drafts of a prose guide with a reviewed instruction set.

The drafter will always misread some prose, so CI installs from a reviewed
instruction set pinned to a guide version. This drafts the same guide again
with the production converter and lists every component whose draft differs
from the reviewed steps. A difference shows where the drafter would have
needed a human; it is only a failure with --strict.

The reviewed set itself must be clean: a component in it that still needs
review, or a component only one side has, always fails.
Nothing is installed and no game or mod folder is read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

GUIDE_URL = 'https://raw.githubusercontent.com/kolto-labs/mod-builds/{ref}/{path}'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def convert(binary, source, target, parse, log):
    argv = [str(binary), 'convert', str(source), str(target), '--format', 'json']
    if parse:
        argv.append('--parse-directions')
    result = subprocess.run(argv, capture_output=True, text=True)
    log.append({'argv': argv, 'exitCode': result.returncode, 'stderr': result.stderr[-4000:]})
    if result.returncode != 0:
        raise SystemExit(f'convert failed ({result.returncode}): {" ".join(argv)}\n{result.stderr}')
    components = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(components, list):
        raise SystemExit(f'{target}: expected a component array')
    return components


def path(text):
    """A path as the engine compares it: either separator, any case, no trailing one."""
    return (text or '').replace('/', '\\').rstrip('\\').lower()


def steps(component):
    """Install-relevant fields of a component's steps, options included."""
    own = [{
        'action': (i.get('Action') or '').lower(),
        'source': [path(s) for s in (i.get('Source') or [])],
        'destination': path(i.get('Destination')),
        'arguments': i.get('Arguments') or '',
        'overwrite': i.get('Overwrite', True),
    } for i in component.get('Instructions') or []]
    options = [{
        'name': o.get('Name') or '',
        'selected': bool(o.get('IsSelected')),
        **steps(o),
    } for o in component.get('Options') or []]
    return {'steps': own, 'options': options}


def needs_review(component):
    review = component.get('DraftReview')
    if isinstance(review, dict) and review.get('RequiresReview') is not False:
        return True
    return any(needs_review(o) for o in component.get('Options') or [])


def key(component):
    return (component.get('Guid') or '').lower()


def compare(binary, guide, reviewed_path, out, strict):
    """Compare one guide with its reviewed set; returns the exit code."""
    out.mkdir(parents=True, exist_ok=True)
    log = []
    drafted = convert(binary, guide, out / 'drafted.json', True, log)
    reviewed = convert(binary, reviewed_path, out / 'reviewed.json', False, log)
    by_guid = {key(c): c for c in reviewed}
    by_name = {(c.get('Name') or '').lower(): c for c in reviewed}

    rows, problems = [], []
    seen = set()
    for component in drafted:
        match = by_guid.get(key(component)) or by_name.get((component.get('Name') or '').lower())
        row = {'name': component.get('Name'), 'guid': component.get('Guid')}
        draft = steps(component)
        drafted_anything = bool(draft['steps'] or any(o['steps'] for o in draft['options']))
        if match is None:
            row['result'] = 'missing-from-reviewed'
            problems.append(f'{row["name"]}: in the guide but not in the reviewed set')
        else:
            seen.add(id(match))
            want = steps(match)
            if needs_review(match):
                row['result'] = 'reviewed-set-not-reviewed'
                problems.append(f'{row["name"]}: still needs review in the reviewed set')
            elif not drafted_anything:
                row['result'] = 'not-drafted'
            elif draft == want:
                row['result'] = 'same'
            else:
                row['result'] = 'differs'
                row['drafted'] = draft
                row['reviewed'] = want
        rows.append(row)
    extra = [c.get('Name') for c in reviewed if id(c) not in seen]

    counts = {}
    for row in rows:
        counts[row['result']] = counts.get(row['result'], 0) + 1
    report = {
        'guide': {'path': str(guide), 'sha256': sha256(guide)},
        'reviewed': {'path': str(reviewed_path), 'sha256': sha256(reviewed_path)},
        'components': len(drafted),
        'counts': counts,
        'onlyInReviewed': extra,
        'problems': problems,
        'rows': rows,
        'commands': log,
    }
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    lines = [
        f'## Drafter check: {guide.name}',
        '',
        f'{len(drafted)} components. The drafter matched the reviewed steps for '
        f'{counts.get("same", 0)}, differed for {counts.get("differs", 0)}, and drafted nothing for '
        f'{counts.get("not-drafted", 0)}.',
        '',
    ]
    differs = [r for r in rows if r['result'] == 'differs']
    if differs:
        lines += ['<details><summary>Components where the draft differs</summary>', '']
        lines += [f'- {r["name"]}' for r in differs]
        lines += ['', '</details>', '']
    if problems or extra:
        lines += ['### Reviewed set problems', '']
        lines += [f'- {p}' for p in problems]
        lines += [f'- {name}: in the reviewed set but not in the guide' for name in extra]
        lines.append('')
    summary = '\n'.join(lines)
    (out / 'summary.md').write_text(summary, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
            handle.write(summary + '\n')
    print(summary)

    if problems or extra:
        return 2
    if strict and differs:
        return 1
    return 0


def fetch(url, target, expected=None):
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if expected and actual.lower() != expected.lower():
        raise SystemExit(f'{url}: SHA-256 {actual} does not match the pinned {expected}')
    target.write_bytes(data)
    return target


def from_manifest(binary, manifest, out, strict):
    """Every reviewed set pinned in the manifest, against its guide version."""
    sets = json.loads(manifest.read_text(encoding='utf-8')).get('sets', [])
    if not sets:
        note = ('No reviewed instruction sets are pinned yet, so there is nothing to compare. '
                f'Add one to {manifest.as_posix()} (see docs/drafter-check.md).')
        print(note)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
                handle.write(f'## Drafter check\n\n{note}\n')
        return 0
    worst = 0
    for entry in sets:
        name = entry['name']
        folder = out / name
        folder.mkdir(parents=True, exist_ok=True)
        guide = fetch(GUIDE_URL.format(ref=entry['guide_ref'], path=entry['guide_path']),
                      folder / Path(entry['guide_path']).name, entry.get('guide_sha256'))
        reviewed = fetch(entry['reviewed_url'],
                         folder / ('reviewed' + Path(entry['reviewed_url']).suffix),
                         entry['reviewed_sha256'])
        worst = max(worst, compare(binary, guide, reviewed, folder / 'report', strict))
    return worst


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--binary', type=Path, required=True, help='modsync executable')
    parser.add_argument('--guide', type=Path, help='prose Markdown guide')
    parser.add_argument('--reviewed', type=Path,
                        help='reviewed instruction set for the same guide version (TOML, JSON, YAML or XML)')
    parser.add_argument('--manifest', type=Path,
                        help='compare every reviewed set pinned in this file instead')
    parser.add_argument('--output', type=Path, required=True, help='folder for the report')
    parser.add_argument('--strict', action='store_true',
                        help='fail when any draft differs from the reviewed set')
    args = parser.parse_args()
    out = args.output.resolve()
    if args.manifest:
        return from_manifest(args.binary, args.manifest, out, args.strict)
    if not (args.guide and args.reviewed):
        parser.error('give --guide and --reviewed, or --manifest')
    return compare(args.binary, args.guide, args.reviewed, out, args.strict)


if __name__ == '__main__':
    sys.exit(main())
