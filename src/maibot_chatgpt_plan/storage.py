"""Windows user-controlled storage. Never copy authorization files to releases."""
import json
import os
from pathlib import Path
import uuid

import ntsecuritycon
import win32api
import win32con
import win32crypt
import win32cryptcon
import win32security


def secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    acl = win32security.ACL()
    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION,
                             win32con.CONTAINER_INHERIT_ACE | win32con.OBJECT_INHERIT_ACE,
                             ntsecuritycon.FILE_ALL_ACCESS, user)
    win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, acl, None)


def protect_write(path: Path, value) -> None:
    encrypted = win32crypt.CryptProtectData(json.dumps(value).encode('utf-8'),
        'MaiBot ChatGPT Plan', None, None, None, win32cryptcon.CRYPTPROTECT_UI_FORBIDDEN)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_bytes(encrypted)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def protected_read(path: Path):
    if not path.exists():
        return None
    decrypted = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None,
        win32cryptcon.CRYPTPROTECT_UI_FORBIDDEN)[1]
    return json.loads(decrypted)
