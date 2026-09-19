#!/usr/bin/env python3
"""轻量 .env 加载(不依赖 python-dotenv)。
用法: 在代码里
    from env_loader import load_env
    CFG = load_env()
    CFG.get('OLLAMA_HOST', '10.1.27.7')
"""
import os

_DEFAULTS = {
    # AI / Ollama
    'OLLAMA_HOST': '10.1.27.7',
    'OLLAMA_PORT': '11434',
    'OLLAMA_MODEL': 'deepseek-r1:1.5b',
    # 数据库
    'DB_HOST': 'localhost',
    'DB_USER': 'library',
    'DB_PASSWORD': 'library123',
    'DB_NAME': 'books',
    # 串口
    'STM32_PORT': '/dev/ttyACM0',
}

_ENV_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '.env')


def load_env():
    cfg = dict(_DEFAULTS)
    if os.path.exists(_ENV_FILE):
        for line in open(_ENV_FILE, encoding='utf-8'):
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    # 环境变量优先(真正的 secret 不打进 .env)
    for k in list(cfg):
        if k in os.environ:
            cfg[k] = os.environ[k]
    return cfg