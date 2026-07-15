import importlib
import sys

packages = [
    'fastapi', 'uvicorn', 'openai', 'requests', 'pandas', 'networkx',
    'matplotlib', 'pyvis', 'PIL', 'jinja2', 'aiofiles', 'python_dotenv',
    'python_multipart', 'sse_starlette', 'pydantic', 'neo4j', 'tqdm', 'seaborn',
    'pytest', 'pytest_asyncio', 'pytest_cov', 'pytest_mock', 'ruff',
]

print('python', sys.version)
for name in packages:
    try:
        module = importlib.import_module(name)
        version = getattr(module, '__version__', None)
        if version is None:
            version = getattr(module, 'VERSION', None)
        print(f'{name}: OK {version}')
    except Exception as exc:
        print(f'{name}: FAIL {exc}')

try:
    import pkgutil
    installed = sorted([m.name for m in pkgutil.iter_modules()])
    print('\ninstalled packages count:', len(installed))
    print(','.join(installed[:100]))
except Exception as exc:
    print('pkgutil fail', exc)
