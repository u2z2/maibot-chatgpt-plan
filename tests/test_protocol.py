from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from maibot_chatgpt_plan.protocol import normalize_request, UNSUPPORTED_FIELDS


class ProtocolTests(unittest.TestCase):
    def test_maibot_parameters_and_system_messages(self):
        payload = {'model': 'test', 'input': [{'type':'message','role':'system','content':'instruction'},
                    {'role':'user','content':[{'type':'input_text','text':'hello'}]}],
                   'stream': True, 'store': False, 'max_output_tokens': 4096,
                   'temperature': .7, 'previous_response_id': 'old-response'}
        before = deepcopy(payload)
        actual = normalize_request(payload)
        self.assertEqual(payload, before)
        self.assertEqual(actual['input'][0]['role'], 'developer')
        self.assertTrue(UNSUPPORTED_FIELDS.isdisjoint(actual))

    def test_string_input(self):
        actual = normalize_request({'model':'test','input':'hello','stream':True,'store':False})
        self.assertEqual(actual['input'], [{'role':'user','content':'hello'}])

    def test_reject_unsupported_inputs_and_tools(self):
        for extra in ({'tools':[{'type':'web_search'}]},
                      {'input':[{'role':'user','content':[{'type':'input_image','image_url':'fake'}]}]},
                      {'input':[]}, {'input':[{'type':'function_call_output','output':'fake'}]},
                      {'store':True}, {'stream':False}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                normalize_request({'model':'test','input':'hello','store':False,'stream':True,**extra})
