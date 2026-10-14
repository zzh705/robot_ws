#!/usr/bin/env python3
"""library_gui/tts.py — 文字转语音（离线 · 板载喇叭发声）

链路:
    GUI 按钮 → 本模块 → espeak-ng 合成 → 重采样 48kHz/立体声 → aplay → 喇叭

为什么不用官方 hobot_tts:
    1) 本机 hobot_tts 二进制启动即段错误(rc=139)，当前不可用;
    2) 板载 ES8326 codec 只吃 8000/16000/32000/48000Hz —— 22050/44100
       会触发 "Clock coefficients do not match" 而静音;
    3) espeak-ng 是板子上现成的离线 TTS，零依赖、断网可用。

播放设备: 环境变量 TTS_DEVICE (默认 hw:0,0 = 板载 ES8326 圆孔)
音色:     环境变量 TTS_VOICE  (默认 cmn = 中文普通话)
"""
import audioop
import os
import shutil
import subprocess
import tempfile
import threading
import wave

VOICE = os.environ.get('TTS_VOICE', 'cmn')
SPEAK_RATE = int(os.environ.get('TTS_SPEAK_RATE', '150'))
OUT_RATE = 48000                      # 必须落在 ES8326 支持的档位
DEVICE = os.environ.get('TTS_DEVICE', 'hw:0,0')

_lock = threading.Lock()


def _synth(text):
    """espeak-ng 合成，返回临时 wav 路径。"""
    fd, path = tempfile.mkstemp(prefix='tts_', suffix='.wav', dir='/tmp')
    os.close(fd)
    subprocess.run(
        ['espeak-ng', '-v', VOICE, '-s', str(SPEAK_RATE), text, '-w', path],
        check=True, capture_output=True, timeout=30)
    return path


def _to_48k_stereo(src):
    """重采样成 48kHz 立体声（ES8326 只认这几档采样率，且必须 2 声道）。"""
    fd, dst = tempfile.mkstemp(prefix='tts48_', suffix='.wav', dir='/tmp')
    os.close(fd)
    with wave.open(src, 'rb') as w:
        data = w.readframes(w.getnframes())
        sw, ch, fr = w.getsampwidth(), w.getnchannels(), w.getframerate()
    if ch == 2:
        data = audioop.tomono(data, sw, 0.5, 0.5)
    if fr != OUT_RATE:
        data, _ = audioop.ratecv(data, sw, 1, fr, OUT_RATE, None)
    data = audioop.tostereo(data, sw, 1.0, 1.0)
    with wave.open(dst, 'wb') as o:
        o.setnchannels(2)
        o.setsampwidth(sw)
        o.setframerate(OUT_RATE)
        o.writeframes(data)
    return dst


def speak(text):
    """把 text 合成语音并从喇叭播出；阻塞到播完。返回 (ok, 说明)。"""
    text = (text or '').strip()
    if not text:
        return False, '空文本'
    if not shutil.which('espeak-ng'):
        return False, '未安装 espeak-ng'

    with _lock:
        src = dst = None
        try:
            src = _synth(text)
            dst = _to_48k_stereo(src)
            subprocess.run(['aplay', '-D', DEVICE, '-q', dst],
                           check=True, capture_output=True, timeout=60)
            return True, '已播报 %d 字' % len(text)
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b'').decode('utf-8', 'ignore').strip()
            return False, '播放失败: %s' % (err or e)
        except Exception as e:
            return False, '语音播报失败: %s' % e
        finally:
            for p in (src, dst):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass


def shutdown():
    """兼容旧接口（已不使用 rclpy，无需清理）。"""
    return None


if __name__ == '__main__':
    import sys
    print(speak(sys.argv[1] if len(sys.argv) > 1 else '你好，我是图书馆机器人'))
