import importlib.util, sys
required = ('keyboard', 'numpy', 'pyperclip', 'requests', 'sounddevice', 'pystray', 'PIL')
missing = [name for name in required if importlib.util.find_spec(name) is None]
sys.exit(0 if not missing else 1)
