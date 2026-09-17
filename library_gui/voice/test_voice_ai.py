import sys
import os

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

sys.path.insert(0, PROJECT_ROOT)


from asr import recognize
from ai_api import ask_ai


wav_file = os.path.join(
    os.path.dirname(__file__),
    "test.wav"
)


print("================================")
print("第一步：语音识别")
print("================================")

text = recognize(wav_file)

print()
print("用户说：")
print(text)


if not text:
    print("语音识别失败")
    exit(1)


print()
print("================================")
print("第二步：发送给 AI")
print("================================")

answer = ask_ai(text)

print()
print("AI回答：")
print(answer)

print()
print("================================")
print("语音 AI 测试完成")
print("================================")