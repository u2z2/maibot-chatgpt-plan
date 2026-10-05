"""Explicitly restore a protected configuration backup; preview by default."""
import argparse
import os
from pathlib import Path
import uuid
from .storage import protected_read, protect_write


def main():
    parser = argparse.ArgumentParser(description='Preview or restore a protected MaiBot config backup')
    parser.add_argument('backup', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    record = protected_read(args.backup)
    if not record:
        parser.error('Backup does not exist.')
    target = Path(record['path'])
    if not target.is_file() or target.name != 'model_config.toml':
        parser.error('Original configuration path no longer exists.')
    print('Target: ' + str(target))
    if not args.apply:
        print('Preview only. Add --apply to restore. The current file will be backed up first.')
        return
    backup = args.backup.parent / ('pre-restore-' + uuid.uuid4().hex + '.dpapi')
    protect_write(backup, {'path': str(target), 'content': target.read_text(encoding='utf-8-sig')})
    temp = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(record['content'], encoding='utf-8', newline='')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    print('Restored. Protected pre-restore backup: ' + str(backup))


if __name__ == '__main__':
    main()
