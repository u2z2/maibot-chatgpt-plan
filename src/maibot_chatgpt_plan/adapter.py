"""Add an optional MaiBot model without changing task assignments."""
import os
from pathlib import Path
import uuid

import tomlkit
from .storage import protect_write


def add_model_option(config_path: Path, state_dir: Path, model: str, origin: str,
                     local_key: str, provider_name: str, model_name: str) -> Path:
    original_bytes = config_path.read_bytes()
    doc = tomlkit.parse(original_bytes.decode('utf-8-sig'))
    if not all(k in doc for k in ('api_providers', 'models', 'model_task_config')):
        raise ValueError('不是有效的 MaiBot 模型配置。')
    providers = doc['api_providers']
    provider = next((p for p in providers if p.get('name') == provider_name), None)
    if provider is not None and provider.get('base_url') != origin + '/v1':
        raise ValueError('提供商名称与已有配置冲突，请使用独立配置。')
    entry = next((m for m in doc['models'] if m.get('name') == model_name), None)
    if entry is not None and entry.get('api_provider') != provider_name:
        raise ValueError('模型名称与已有配置冲突。')
    backup = state_dir / ('model-config-backup-' + uuid.uuid4().hex + '.dpapi')
    protect_write(backup, {'path': str(config_path), 'content': original_bytes.decode('utf-8-sig')})
    if provider is None:
        provider = tomlkit.table()
        providers.append(provider)
    provider.update({'name': provider_name, 'base_url': origin + '/v1', 'api_key': local_key,
                     'client_type': 'openai_responses', 'max_retry': 0,
                     'timeout': 180, 'retry_interval': 5})
    if entry is None:
        entry = tomlkit.table()
        doc['models'].append(entry)
    entry.update({'name': model_name, 'model_identifier': model, 'api_provider': provider_name,
                  'price_in': 0, 'price_out': 0, 'send_temperature': False,
                  'visual': False, 'force_stream_mode': True, 'extra_params': {}})
    result = tomlkit.dumps(doc)
    tomlkit.parse(result)
    if config_path.read_bytes() != original_bytes:
        raise ValueError('配置被其他程序修改；没有覆盖，请重新添加。')
    temp = config_path.with_name(config_path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(result, encoding='utf-8', newline='')
        os.replace(temp, config_path)
    finally:
        temp.unlink(missing_ok=True)
    return backup
