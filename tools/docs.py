"""Generate module reference tables from the Terraform source."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INTRO = {
    'static-site': 'S3/CloudFront static hosting with private OAC origins and an optional GitHub pipeline. Existing hosted zones and GitHub connection authorization belong to the caller.',
    'journal-comments': 'Dedicated Lightsail Remark42 hosting, CloudFront origin protection, S3 archives, restricted host IAM, health alarms and readable SES alerts with independent SNS fallback.',
    'journal-comments-email': 'SES identity, configuration set, DKIM, MAIL FROM and confirmed bounce/complaint notifications. Regional suppression belongs to the environment root.',
}


def generate():
    for module, intro in INTRO.items():
        directory = ROOT / 'modules' / module
        source = (directory / 'variables.tf').read_text()
        rows = []
        matches = list(re.finditer(r'^variable "([^"]+)" \{', source, re.M))
        for index, match in enumerate(matches):
            block = source[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(source)]
            type_ = re.search(r'\btype\s*=\s*([^\n]+)', block)[1].strip().removesuffix('}').strip()
            default = re.search(r'\bdefault\s*=\s*([^\n]+)', block)
            description = re.search(r'description\s*=\s*"([^"]*)"', block)
            rows.append(f'| `{match[1]}` | `{type_}` | {"Required" if default is None else "`" + default[1].strip() + "`"} | {description[1] if description else ""} |')
        outputs = re.findall(r'^output "([^"]+)"', (directory / 'outputs.tf').read_text(), re.M)
        text = f'# {module}\n\n{intro}\n\nUse AWS provider 6.x; CloudFront certificates require the `aws.use1` alias in us-east-1.\n\n'
        text += '## Inputs\n\n| Input | Type | Default | Description |\n| --- | --- | --- | --- |\n' + '\n'.join(rows)
        text += '\n\n## Outputs\n\n' + '\n'.join('- `' + name + '`' for name in outputs)
        text += '\n\nSee [examples](../../examples), [operations](../../docs/operations.md) and [migration](../../docs/migration.md).\n'
        (directory / 'README.md').write_text(text, newline='\n')


if __name__ == '__main__': generate()
