import json
import unittest
from maibot_chatgpt_plan.streaming import iter_response_stream, parse_event, has_text_output


def frame(event, newline=b"\n"):
    return b"event: " + event['type'].encode() + newline + b"data: " + json.dumps(event, ensure_ascii=False).encode() + newline * 2


class Content:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_any(self):
        for chunk in self.chunks:
            yield chunk


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, chunks):
        return [part async for part in iter_response_stream(Content(chunks))]

    async def test_chunked_utf8_rebuild_matches_maibot_terminal_reader(self):
        item = {'type':'message', 'content':[{'type':'output_text', 'text':'连接成功'}]}
        wire = frame({'type':'response.output_item.done', 'output_index':0, 'item':item}) + frame({'type':'response.completed', 'response':{'output':[]}})
        parts = await self.collect([wire[i:i+1] for i in range(len(wire))])
        terminal = parse_event(parts[-1])
        self.assertEqual(terminal['response']['output'], [item])
        self.assertTrue(has_text_output(terminal))

    async def test_preserve_existing_terminal_output(self):
        done = frame({'type':'response.output_item.done', 'output_index':0, 'item':{'id':'old'}})
        terminal = frame({'type':'response.completed', 'response':{'output':[{'id':'canonical'}]}})
        self.assertEqual((await self.collect([done + terminal]))[-1], terminal)

    async def test_order_and_replace_duplicate_items(self):
        frames = [frame({'type':'response.output_item.done','output_index':i,'item':{'id':v}})
                  for i,v in [(1,'b'),(0,'a'),(1,'updated')]]
        frames.append(frame({'type':'response.completed','response':{}}))
        parts = await self.collect(frames)
        self.assertEqual(parse_event(parts[-1])['response']['output'], [{'id':'a'},{'id':'updated'}])

    async def test_multiline_crlf_and_unknown_frames(self):
        item = b'data: {"type":"response.output_item.done",\r\n' + b'data: "output_index":0,"item":{"type":"message","content":[{"type":"output_text","text":"ok"}]}}\r\n\r\n'
        heartbeat = b': heartbeat\r\n\r\n'
        done = frame({'type':'response.completed','response':{}}, b'\r\n')
        parts = await self.collect([item + heartbeat + done + b'data: [DONE]\n\n'])
        self.assertEqual(parts[1], heartbeat)
        self.assertTrue(has_text_output(parse_event(parts[2])))
        self.assertEqual(parts[3], b'data: [DONE]\n\n')

    async def test_failures_and_truncated_terminal_do_not_become_success(self):
        failed = frame({'type':'response.failed','response':{'error':{'code':'limit'}}})
        incomplete = b'data: {"type":"response.completed","response":{}}'
        self.assertEqual(await self.collect([failed, incomplete]), [failed, incomplete])
        self.assertIsNone(parse_event(incomplete))
        self.assertFalse(has_text_output(parse_event(failed)))

    async def test_empty_completion_stays_empty(self):
        terminal = frame({'type':'response.completed','response':{}})
        self.assertEqual(await self.collect([terminal]), [terminal])
        self.assertFalse(has_text_output(parse_event(terminal)))
