"""Validate OpenAI identity before storing any authorization credentials."""
import secrets
import jwt


def validate_id_token(token: str, jwks: dict, client_id: str, nonce: str) -> dict:
    header = jwt.get_unverified_header(token)
    if header.get('alg') != 'RS256':
        raise ValueError('Unsupported ID-token algorithm')
    key = next(k for k in jwks['keys'] if k['kid'] == header['kid'])
    claims = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=['RS256'],
                        audience=client_id, issuer='https://auth.openai.com',
                        options={'require': ['exp', 'iss', 'aud', 'sub', 'nonce']})
    if not secrets.compare_digest(claims['nonce'], nonce):
        raise ValueError('ID-token nonce mismatch')
    return claims
