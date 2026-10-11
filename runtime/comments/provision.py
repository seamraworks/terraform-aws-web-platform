#!/usr/bin/env python3
"""Prepare/publish private runtime configuration for an existing Terraform deployment."""
import argparse
import configparser
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
from deployment import load_deployment, validate_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'publish'])
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--private-dir', required=True)
    parser.add_argument('--config', help='Operator configuration; required on the first prepare')
    parser.add_argument('--profile', required=True)
    args = parser.parse_args()
    deployment = load_deployment(args.deployment)
    private = Path(args.private_dir).resolve()
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'nt':
        subprocess.run(['icacls', str(private), '/inheritance:r', '/grant:r',
                        getpass.getuser() + ':(OI)(CI)F'], check=True, capture_output=True)
    else: private.chmod(0o700)

    def write(name, text):
        temporary = private / (name + '.next')
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream: stream.write(text)
        temporary.replace(private / name)

    def aws(*arguments, missing=None):
        result = subprocess.run(['aws', '--profile', args.profile, '--region', deployment['region'],
                                 '--no-cli-pager', '--output', 'json', *arguments], capture_output=True, text=True)
        if result.returncode:
            if missing and missing in result.stderr: return None
            raise SystemExit('AWS operation failed: ' + ' '.join(arguments[:2]))
        return json.loads(result.stdout or '{}')

    path = private / 'config.json'
    if args.command == 'prepare':
        if path.exists(): config = json.loads(path.read_text())
        elif args.config: config = json.loads(Path(args.config).read_text())
        else:
            existing = aws('ssm', 'get-parameter', '--name', deployment['config_parameter'], '--with-decryption', missing='ParameterNotFound')
            if not existing: parser.error('First prepare requires --config')
            config = json.loads(existing['Parameter']['Value'])
        config.update(site=deployment['site_id'], region=deployment['region'], backup_bucket=deployment['backup_bucket'],
                      public_url=deployment['public_url'])
        for key in ('origin_secret', 'remark_secret', 'admin_password', 'webhook_secret'):
            if not config.get(key) or config[key].startswith('REPLACE_'): config[key] = secrets.token_urlsafe(48)
        write('config.json', json.dumps(config, indent=2) + '\n')
        write('deployment.json', json.dumps(deployment, indent=2) + '\n')
        write('origin.tfvars.json', json.dumps({'comments_origin_secret': config['origin_secret']}) + '\n')
        print('Prepared private configuration; no AWS resources changed. Supply the same origin secret to Terraform.')
        return

    config = validate_config(json.loads(path.read_text()), deployment)
    existing = aws('ssm', 'get-parameter', '--name', deployment['config_parameter'], '--with-decryption', missing='ParameterNotFound')
    if existing:
        old = json.loads(existing['Parameter']['Value'])
        if any(old.get(key) != config[key] for key in ('remark_secret', 'origin_secret', 'webhook_secret', 'admin_password')):
            raise SystemExit('Refusing to rotate persistent secrets during configuration publication')
    user = aws('iam', 'get-user', '--user-name', deployment['host_iam_user'])['User']
    keys = aws('iam', 'list-access-keys', '--user-name', user['UserName'])['AccessKeyMetadata']
    credentials = private / 'credentials'
    if not credentials.exists():
        if keys: raise SystemExit('Recover the existing host credentials; do not create a duplicate key')
        key = aws('iam', 'create-access-key', '--user-name', user['UserName'])['AccessKey']
        write('credentials', '[default]\naws_access_key_id = ' + key['AccessKeyId'] +
              '\naws_secret_access_key = ' + key['SecretAccessKey'] + '\n')
        keys = aws('iam', 'list-access-keys', '--user-name', user['UserName'])['AccessKeyMetadata']
    parsed = configparser.ConfigParser(); parsed.read(credentials)
    if parsed['default']['aws_access_key_id'] not in {key['AccessKeyId'] for key in keys if key['Status'] == 'Active'}:
        raise SystemExit('Credentials do not match the dedicated host IAM user')
    payload = {'Name': deployment['config_parameter'], 'Type': 'SecureString', 'Tier': 'Standard',
               'Value': json.dumps(config), 'Overwrite': True}
    if len(payload['Value'].encode()) > 4096: raise SystemExit('Configuration exceeds SSM Standard size limit')
    write('ssm-request.json', json.dumps(payload))
    try: aws('ssm', 'put-parameter', '--cli-input-json', 'file://' + str(private / 'ssm-request.json'))
    finally: (private / 'ssm-request.json').unlink(missing_ok=True)
    print('Published runtime configuration; persistent secrets and host identity retained.')


if __name__ == '__main__': main()
