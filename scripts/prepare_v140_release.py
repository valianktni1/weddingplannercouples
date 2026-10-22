"""Prepare private Compose files without changing a running installation."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys


def write_compose(path, config):
    # Compose re-interpolates its input: protect literal dollars in resolved values.
    def literal(value):
        if isinstance(value, str):
            return value.replace('$', '$$')
        if isinstance(value, list):
            return [literal(v) for v in value]
        if isinstance(value, dict):
            return {k: literal(v) for k, v in value.items()}
        return value
    with open(path, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as out:
        json.dump(literal(config), out, indent=2)
        out.write('\n')


def prepare(config, release_dir, image, rollback_dir, previous_images):
    if set(config.get('services', {})) != {'web', 'worker'}:
        raise ValueError('Expected only planner web and worker services; no changes made.')
    next_config = copy.deepcopy(config)
    rollback = copy.deepcopy(config)
    for name, service in next_config['services'].items():
        build = service.get('build')
        if not isinstance(build, dict) or build.get('dockerfile', 'Dockerfile') != 'Dockerfile' or 'dockerfile_inline' in build:
            raise ValueError('Unexpected planner build configuration; no changes made.')
        build['context'] = str(release_dir)
        build['dockerfile'] = 'Dockerfile'
        service['image'] = image
        service['pull_policy'] = 'never'
        rollback['services'][name]['image'] = previous_images[name]
        rollback['services'][name]['pull_policy'] = 'never'
    # Keep env_file references in the new deployment; preserve their contents for rollback.
    for name, service in rollback['services'].items():
        for index, entry in enumerate(service.get('env_file', [])):
            source = Path(entry['path'] if isinstance(entry, dict) else entry)
            if not source.is_absolute():
                raise ValueError('Expected absolute environment file paths; no changes made.')
            if not source.exists() and isinstance(entry, dict) and entry.get('required') is False:
                continue
            target = rollback_dir / f'{name}-environment-{index}.env'
            with source.open('rb') as incoming, open(target, 'xb', opener=lambda p, f: os.open(p, f, 0o600)) as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            if isinstance(entry, dict):
                entry['path'] = str(target)
            else:
                service['env_file'][index] = str(target)
    write_compose(rollback_dir / 'rollback.json', rollback)
    write_compose(rollback_dir / 'next.json', next_config)


if __name__ == '__main__':
    try:
        config_path, release, image, rollback, web_image, worker_image = sys.argv[1:]
        prepare(json.loads(Path(config_path).read_text()), Path(release), image, Path(rollback),
                {'web': web_image, 'worker': worker_image})
    except Exception:
        # Never include config/credentials in terminal errors.
        print('STOP: could not prepare the deployment safely. Existing configuration is unchanged.', file=sys.stderr)
        sys.exit(1)
