import pymysql
from dbutils.pooled_db import PooledDB

class DatabasePool:
    """数据库连接池"""
    
    def __init__(self):
        self.pool = PooledDB(
            creator=pymysql,
            maxconnections=10,
            mincached=2,
            maxcached=5,
            blocking=True,
            host='localhost',
            user='library',
            password='library123',
            database='books',
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