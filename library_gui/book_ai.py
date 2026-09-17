from 数据池 import db_pool



def search_books(keyword):

    """
    查询数据库图书
    """

    conn=None
    cursor=None


    try:

        conn=db_pool.get_connection()

        cursor=conn.cursor()


        sql="""

        SELECT

        book_name,
        author,
        location,
        total_count,
        is_available


        FROM books


        WHERE

        book_name LIKE %s

        OR

        author LIKE %s


        LIMIT 5

        """


        key="%"+keyword+"%"


        cursor.execute(
            sql,
            (key,key)
        )


        books=cursor.fetchall()



        if not books:

            return "没有找到相关图书"



        result="查询结果:\n\n"


        for b in books:


            result+=(
                f"📖 {b[0]}\n"
                f"作者:{b[1]}\n"
                f"位置:{b[2]}\n"
                f"库存:{b[3]}\n"
                f"状态:{'可借' if b[4] else '不可借'}\n\n"
            )


        return result



    except Exception as e:

        return f"数据库错误:{e}"



    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()