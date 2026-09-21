from 数据池 import db_pool



def search_books(keyword):
    """
    查询数据库图书。

    返回 (reply, first_book_name):
      * reply           : 文本回复, 原有格式保持不变
      * first_book_name : 命中的第一本书的书名(用于对齐 bookmarks 锚点),
                          没有命中返回 None
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

            return ("没有找到", {})
        first = books[0]
        first_name = first[0] if first else None
        result="查询结果:\n\n"
        result_lines = []
        for b in books:
            result_lines.append(
                f"{b[0]}\n"
                f"作者:{b[1]}\n"
                f"位置:{b[2]}\n"
                f"库存:{b[3]}\n"
                f"状态:{'可借' if b[4] else '不可借'}\n"
                "\n"
            )
        result = result + ''.join(result_lines)
        return (result, first_name)



        result="查询结果:\n\n"


        for b in books:


            result+=(
                f"{b[0]}\n"
                f"作者:{b[1]}\n"
                f"位置:{b[2]}\n"
                f"库存:{b[3]}\n"
                f"状态:{'可借' if b[4] else '不可借'}\n"
                "\n"
            )


        return result



    except Exception as e:

        return (f"数据库错误:{e}", None)



    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()