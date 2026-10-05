import json
from pathlib import Path
import sys
import time
import unittest
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from maibot_chatgpt_plan.auth import validate_id_token


class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        public['kid'] = 'test-key'
        cls.jwks = {'keys': [public]}

    def token(self, **changes):
        claims = {'iss': 'https://auth.openai.com', 'aud': 'issued-client', 'sub': 'test-user',
                  'nonce': 'expected-nonce', 'exp': int(time.time()) + 120, **changes}
        return jwt.encode(claims, self.key, algorithm='RS256', headers={'kid':'test-key'})

    def test_verified_identity(self):
        claims = validate_id_token(self.token(), self.jwks, 'issued-client', 'expected-nonce')
        self.assertEqual(claims['sub'], 'test-user')

    def test_reject_expiry_audience_issuer_and_nonce(self):
        for changes in ({'exp':int(time.time())-60}, {'aud':'another-client'},
                        {'iss':'https://untrusted.invalid'}, {'nonce':'wrong-nonce'}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, jwt.PyJWTError)):
                validate_id_token(self.token(**changes), self.jwks, 'issued-client', 'expected-nonce')

    def test_reject_untrusted_signature(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode({'iss':'https://auth.openai.com','aud':'issued-client','sub':'fake',
            'nonce':'expected-nonce','exp':int(time.time())+120}, other, algorithm='RS256', headers={'kid':'test-key'})
        with self.assertRaises(jwt.InvalidSignatureError):
            validate_id_token(token, self.jwks, 'issued-client', 'expected-nonce')
