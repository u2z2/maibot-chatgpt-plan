"""The initial release supports the text-only SIWC Responses subset."""
from copy import deepcopy

UNSUPPORTED_FIELDS = frozenset({
    'background', 'conversation', 'max_output_tokens', 'max_tool_calls', 'metadata',
    'moderation', 'multi_agent', 'prompt', 'prompt_cache_retention', 'safety_identifier',
    'temperature', 'top_logprobs', 'top_p', 'truncation', 'user', 'previous_response_id',
})


def normalize_request(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('请求必须是 JSON 对象。')
    body = deepcopy(payload)
    if body.get('stream') is not True or body.get('store') is not False:
        raise ValueError('需要 stream=true 和 store=false。')
    if body.get('tools') or body.get('tool_choice') not in (None, 'none'):
        raise ValueError('0.1 版只支持文本；原生工具调用尚未适配。')
    body.pop('tools', None)
    body.pop('tool_choice', None)
    for field in UNSUPPORTED_FIELDS:
        body.pop(field, None)
    if isinstance(body.get('input'), str):
        body['input'] = [{'role': 'user', 'content': body['input']}]
    if not isinstance(body.get('input'), list) or not body['input']:
        raise ValueError('input 必须是非空消息列表。')
    for item in body['input']:
        if not isinstance(item, dict) or item.get('type', 'message') != 'message':
            raise ValueError('0.1 版只接受文本消息。')
        if item.get('role') == 'system':
            item['role'] = 'developer'
        if item.get('role') not in ('user', 'assistant', 'developer'):
            raise ValueError('消息角色不受支持。')
        content = item.get('content')
        if isinstance(content, list):
            if any(not isinstance(part, dict) or part.get('type') not in ('input_text', 'output_text')
                   for part in content):
                raise ValueError('0.1 版尚未适配图片、音频或文件输入。')
        elif not isinstance(content, str):
            raise ValueError('消息内容必须是文本。')
    return body
