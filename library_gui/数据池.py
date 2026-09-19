import pymysql
from dbutils.pooled_db import PooledDB
from env_loader import load_env

_CFG = load_env()

class DatabasePool:
    """数据库连接池"""
    
    def __init__(self):
        self.pool = PooledDB(
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
            autocommit=True
        )
        print("✅ 数据库连接池初始化成功")
    
    def get_connection(self):
        return self.pool.connection()
    
    def close(self):
        self.pool.close()
        print("🔌 数据库连接池已关闭")

db_pool = DatabasePool()