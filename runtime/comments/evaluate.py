#!/usr/bin/env python3
"""Optional live model evaluation on synthetic comments; never deletes anything.

Uses a provider configuration and a separate persistent evaluation ledger.
OpenAI evaluations require an explicit evaluation budget; secrets can use the
same environment variables as the standalone component.
"""
import argparse
import json
import os
from pathlib import Path
from moderator import Database, ModerationAdapter

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Provider JSON configuration; keep secrets outside source control')
    parser.add_argument('--budget-usd', type=float, help='Explicit monthly evaluation ceiling for OpenAI')
    parser.add_argument('--ledger', type=Path, default=ROOT / '.runtime/evaluation.sqlite')
    parser.add_argument('--cases', type=Path, default=ROOT / 'tests/evaluation.json')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if config.get('moderation_provider') == 'openai':
        if args.budget_usd is None or args.budget_usd <= 0:
            parser.error('OpenAI evaluation requires a positive --budget-usd ceiling')
        config['monthly_budget_usd'] = args.budget_usd
    database = Database(args.ledger)
    model = ModerationAdapter(config, database)
    results = []
    for case in json.loads(args.cases.read_text()):
        decision = model.classify({'orig': case['text'], 'title': 'SMTP connection lifetimes and delivery',
                                   'locator': {'url': 'https://www.example.com/journal/example.html'}})
        passed = decision['decision'] in case['allow']
        results.append({'label': case['label'], 'passed': passed, **decision})
        print(('PASS' if passed else 'FAIL') + ': ' + case['label'] + ' -> ' + decision['decision'])
    args.ledger.with_suffix('.results.json').write_text(json.dumps(results, indent=2))
    if not all(result['passed'] for result in results):
        raise SystemExit('Evaluation failed. Keep production in report mode and review the policy.')
    print('All synthetic cases passed. Review real report-mode classifications before enabling automatic removal.')


if __name__ == '__main__': main()
