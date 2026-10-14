"""数据池 —— 数据库连接池（懒加载 + 容错）

改动说明（2026-10-12）:
    连接池改为「首次真正访问数据库时才建立」。
    —— MySQL 不可用时，GUI 不再在 import 阶段直接崩溃，
       界面照常启动，语音播报等不依赖数据库的功能可用；
       查询/借阅在访问数据库时才失败，由各页面已有的 try/except 提示。
    —— 数据库本身（服务、数据）不动；DB 恢复后本模块自动重新建池，无需改回。
"""
import pymysql
from dbutils.pooled_db import PooledDB
from env_loader import load_env

_CFG = load_env()


class DatabasePool:
    """数据库连接池（懒加载：数据库不可用时不会拖垮界面启动）"""

    def __init__(self):
        self._pool = None

    def _ensure(self):
        if self._pool is None:
            self._pool = PooledDB(
                creator=pymysql,
                maxconnections=10,
                mincached=2,
                maxcached=5,
                blocking=True,
                host=_CFG.get('DB_HOST', 'localhost'),
                user=_CFG.get('DB_USER', 'library'),
                password=_CFG.get('DB_PASSWORD', 'library123'),
                database=_CFG.get('DB_NAME', 'books'),
                charset='utf8mb4',
                autocommit=True,
            )
            print("✅ 数据库连接池初始化成功")
        return self._pool

    def get_connection(self):
        return self._ensure().connection()

    def close(self):
        if self._pool is not None:
            self._pool.close()
            self._pool = None
            print("🔌 数据库连接池已关闭")


db_pool = DatabasePool()
