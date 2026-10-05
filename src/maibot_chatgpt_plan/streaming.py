"""Preserve SSE events and restore output omitted by terminal responses."""
import json
import re

_BOUNDARY = re.compile(br'\r?\n\r?\n')
_MAX_EVENT_BYTES = 16 * 1024 * 1024


def parse_event(frame):
    if not frame.endswith((b'\n\n', b'\r\n\r\n')):
        return None
    data = b'\n'.join(line[5:].lstrip(b' ') for line in frame.splitlines()
                      if line.startswith(b'data:'))
    try:
        event = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    return event if isinstance(event, dict) else None


def normalize_frame(frame, completed_items):
    event = parse_event(frame)
    if event is None:
        return frame
    if event.get('type') == 'response.output_item.done':
        item, index = event.get('item'), event.get('output_index')
        if isinstance(item, dict) and type(index) is int and index >= 0:
            completed_items[index] = item
    elif event.get('type') == 'response.completed':
        response = event.get('response')
        if isinstance(response, dict) and not response.get('output') and completed_items:
            response['output'] = [completed_items[index] for index in sorted(completed_items)]
            lines = [line for line in frame.splitlines() if not line.startswith(b'data:')]
            lines.append(b'data: ' + json.dumps(event, ensure_ascii=False).encode('utf-8'))
            return b'\n'.join(lines) + b'\n\n'
    return frame


async def iter_response_stream(content):
    """Parse full frames even when network chunks split UTF-8 or SSE data."""
    pending = b''
    completed_items = {}
    async for chunk in content.iter_any():
        pending += chunk
        while (match := _BOUNDARY.search(pending)) is not None:
            if match.end() > _MAX_EVENT_BYTES:
                raise ValueError('上游流事件过大。')
            frame, pending = pending[:match.end()], pending[match.end():]
            yield normalize_frame(frame, completed_items)
        if len(pending) > _MAX_EVENT_BYTES:
            raise ValueError('上游流事件过大。')
    if pending:
        # An unterminated event is incomplete and must not count as success.
        yield pending


def has_text_output(event):
    response = event.get('response')
    if not isinstance(response, dict):
        return False
    output = response.get('output')
    if not isinstance(output, list):
        return False
    for item in output:
        if not isinstance(item, dict) or not isinstance(item.get('content'), list):
            continue
        for part in item['content']:
            if (isinstance(part, dict) and part.get('type') == 'output_text'
                    and isinstance(part.get('text'), str) and part['text'].strip()):
                return True
    return False
