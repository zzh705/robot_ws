from ai_api import ask_ai
from book_ai import search_books


# ============================================================
# 1. 提取图书搜索关键词
# ============================================================

def extract_keyword(question):
    """
    从用户自然语言中提取图书搜索关键词。

    示例：

    Python在哪里
    -> Python

    Python的书在哪
    -> Python

    我想找Python
    -> Python

    帮我找一本Python的书
    -> Python
    """

    keyword = question.strip()

    remove_words = [
        # 地点 / 查询表达
        "在哪里",
        "在哪儿",
        "在哪",
        "什么位置",
        "位置",
        "怎么找",
        "怎么去",

        # 图书相关表达
        "的书",
        "书籍",
        "图书",
        "这本书",
        "这本",

        # 请求表达
        "帮我找一本",
        "帮我找",
        "帮我查询",
        "帮我查一下",
        "帮我查",
        "我要找",
        "我要去找",
        "请找",
        "带我去",
        "我想看",
        "想看",
        "想读",
        "我想读",
        "请帮我去",
        "我想找一本",
        "我想找",
        "我想查询",
        "我想查一下",
        "我想查",
        "请帮我找",
        "请帮我查询",
        "请帮我查",

        # 数量 / 泛化表达
        "一本",
        "一套",
    ]

    for word in remove_words:
        keyword = keyword.replace(word, "")

    return keyword.strip()


# ============================================================
# 2. 判断用户意图
# ============================================================

def detect_intent(text):
    """
    判断用户问题属于哪一种意图。

    返回：

    search  -> 查询/寻找图书
    borrow  -> 借书
    return  -> 还书
    ai      -> 普通 AI 问题
    """

    text = text.strip()

    # --------------------------------------------------------
    # 借书
    # --------------------------------------------------------

    borrow_words = [ "借书", "借阅", "我要借", "想借", "借一本", "借这本", "帮我借", ]

    for word in borrow_words:
        if word in text:
            return "borrow"

    # --------------------------------------------------------
    # 还书
    # --------------------------------------------------------

    return_words = [ "还书", "归还", "我要还", "想还", "还一本", "还这本", "帮我还", ]

    for word in return_words:
        if word in text:
            return "return"

    # --------------------------------------------------------
    # 查询 / 寻找图书
    # --------------------------------------------------------

    search_words = [ "找书", "找一本", "找一套", "我想找", "帮我找", "请帮我找", "寻找", "查找", "查询图书", "查图书", "查询书", "查书", "有没有", "有这本书吗", "有这本书", "在哪里", "在哪儿", "在哪", "什么位置", "位置", "怎么找", "怎么去", "书架", "馆藏", "库存", ]

    for word in search_words:
        if word in text:
            return "search"
    # ⭐ 补漏: "我要找 X / 想看 X / 想读 X / 请找 X / 带我去 X" 等
    # 关键词列表里没明列出来, 用正则补上
    import re as _re
    if _re.search(r'(我要|我想|我想看|想看|想读|我想读|请找|请帮我找|带我去|我要去)\s*\S', text):
        return "search"

    # --------------------------------------------------------
    # 其他问题交给 AI
    # --------------------------------------------------------

    return "ai"


# ============================================================
# 3. Library AI 总入口
# ============================================================

def book_chat(text):
    """
    Library AI 总入口。

    用户的问题从这里进入。

    当前支持：

    1. 查询图书
       -> extract_keyword()
       -> search_books()

    2. 借书
       -> 暂时返回提示
       -> 后续接入 borrow_book()

    3. 还书
       -> 暂时返回提示
       -> 后续接入 return_book()

    4. 普通问题
       -> ask_ai()
    """

    text = text.strip()

    # --------------------------------------------------------
    # 空消息
    # --------------------------------------------------------

    if not text:
        return "请输入你的问题。"

    # --------------------------------------------------------
    # 判断意图
    # --------------------------------------------------------

    intent = detect_intent(text)

    print(f"用户问题：{text}")
    print(f"识别意图：{intent}")

    # ========================================================
    # 查询图书
    # ========================================================

    if intent == "search":

        keyword = extract_keyword(text)

        print(f"提取关键词：{keyword}")

        if not keyword:
            return "请告诉我你想查询哪本书。"

        # ---------- 拿到命中书, 若 bookmarks.json 有锚点则顺便派单 ----------
        result = search_books(keyword)
        # search_books 现在返回 (reply_text, first_book_name)
        reply = result[0] if isinstance(result, tuple) else result
        first_name = result[1] if isinstance(result, tuple) and len(result) > 1 else None

        try:
            import json, os
            bm_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                '..', 'maps', 'bookmarks.json')
            with open(bm_path, 'r', encoding='utf-8') as f:
                bm = json.load(f).get('books', {})
        except Exception:
            bm = {}

        # 优先精确匹配; 否则从 bookmarks 里找一个"包含 first_name"或
        # "first_name 包含" 的 key —— 应对数据库里命名变体的情况
        # (例: first='中国科幻基石丛书·三体（全三册）', bookmarks 里是'三体')
        anchor = None
        if first_name:
            if first_name in bm:
                anchor = bm[first_name]
            else:
                for k, v in bm.items():
                    if k in first_name or first_name in k:
                        anchor = v
                        break
        if anchor and anchor.get('goal_x') is not None:
            from robot_comm import send_goto_xy
            ok, msg = send_goto_xy(
                anchor['goal_x'], anchor['goal_y'],
                book_name=first_name)
            tail = (f"\n\n📍 检测到该书已在地图上锚定"
                    f"\n🤖 已让机器人带您去《{first_name}》"
                    f"({anchor.get('book_name', first_name)}): {msg}")
            return reply + tail
        return reply

    # ========================================================
    # 借书
    # ========================================================

    elif intent == "borrow":

        # 暂时不执行数据库修改
        # 后续这里接：
        #
        # return borrow_book(...)

        return "我可以帮你办理借书。借书功能正在接入中。"

    # ========================================================
    # 还书
    # ========================================================

    elif intent == "return":

        # 暂时不执行数据库修改
        # 后续这里接：
        #
        # return return_book(...)

        return "我可以帮你办理还书。还书功能正在接入中。"

    # ========================================================
    # 普通 AI 对话
    # ========================================================

    else:

        return ask_ai(text)

