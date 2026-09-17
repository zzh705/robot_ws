from book_ai import search_books
import requests


# ============================================================
# Ollama 配置
# ============================================================

OLLAMA_HOST = "10.1.27.7"
OLLAMA_PORT = 11434
OLLAMA_MODEL = "deepseek-r1:1.5b"

OLLAMA_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/chat"


# ============================================================
# 调用 AI
# ============================================================

def ask_ai(question):
    """
    调用 Ollama 大模型。

    参数：
        question: 用户问题

    返回：
        AI 回复文本
    """

    question = question.strip()

    if not question:
        return "请输入你的问题。"

    try:

        data = {
            "model": OLLAMA_MODEL,

            "messages": [
                {
                    "role": "system",
                    "content": "你是图书馆智能助手。请始终使用简体中文回答用户问题，回答简洁、自然、容易理解。"
                },
                {
                    "role": "user",
                    "content": question
                }
            ],
            "stream": False
        }

        response = requests.post(
            OLLAMA_URL,
            json=data,
            timeout=60
        )

        # HTTP错误直接抛出
        response.raise_for_status()

        result = response.json()

        # Ollama /api/chat 返回格式：
        #
        # {
        #   "message": {
        #       "role": "assistant",
        #       "content": "..."
        #   }
        # }

        answer = result["message"]["content"]

        return answer.strip()

    except requests.exceptions.ConnectionError:
        return "AI连接失败：无法连接到 Ollama，请检查 10.1.27.7:11434 是否正常运行。"

    except requests.exceptions.Timeout:
        return "AI请求超时，请检查 Ollama 服务或网络连接。"

    except requests.exceptions.HTTPError as e:
        return f"AI服务器错误：{e}"

    except Exception as e:
        return f"AI错误：{e}"