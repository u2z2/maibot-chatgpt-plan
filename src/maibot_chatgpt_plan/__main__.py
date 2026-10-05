import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description='Windows MaiBot ChatGPT plan integration')
    parser.add_argument('--version', action='version', version='0.1.0')
    parser.add_argument('--port', type=int, default=8776)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--maibot-config', type=Path)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('0.1.0 supports Windows only.')
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port between 1024 and 65535.')
    if args.maibot_config and (not args.maibot_config.is_file() or args.maibot_config.name != 'model_config.toml'):
        parser.error('--maibot-config must point to an existing model_config.toml.')
    import msvcrt
    from aiohttp import web
    from .app import Bridge
    from .storage import secure_directory
    state_dir = (args.data_dir or Path(os.environ['LOCALAPPDATA']) / 'MaiBotChatGPTPlan').resolve()
    secure_directory(state_dir)
    lock = (state_dir / 'instance.lock').open('a+b')
    if os.fstat(lock.fileno()).st_size == 0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        parser.error('Another instance owns this data directory. Open its local setup page.')
    try:
        bridge = Bridge(state_dir, args.maibot_config, args.port)
        app = bridge.app()
        if args.open_browser:
            async def open_browser(app):
                import asyncio
                import webbrowser
                asyncio.get_running_loop().call_later(1, webbrowser.open, bridge.origin)
            app.on_startup.append(open_browser)
        print('MaiBot ChatGPT Plan: ' + bridge.origin, flush=True)
        web.run_app(app, host='127.0.0.1', port=args.port, access_log=None, print=None)
    finally:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


if __name__ == '__main__':
    main()
