# -*- coding: utf-8 -*-
"""
合成示例音频生成脚本
====================
程序化合成 4 个示例 wav（纯正弦音/白噪声，无任何真实语音、无版权风险），
放入 audio/ 目录，保证模拟日志模式与 CI 开箱即跑。

文件名与 scripts/audio_test.py 中 MOCK_LOG_DICT / EXPECT_RESULTS 的
演示用例一一对应：
  - wakeup_normal.wav  ：预期"唤醒成功"       （mock 日志 wakeup_success）
  - mis_wake_noise.wav ：预期"不误唤醒"       （mock 日志 idle standby）
  - cmd_volume_up.wav  ：预期"音量调高成功"   （mock 日志 exec command volume up ok）
  - wakeup_noisy.wav   ：预期"唤醒成功"，实际"唤醒失败"（复现 BUG001）

重新生成：python scripts/make_sample_audio.py
"""
import math
import os
import random
import struct
import wave

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")

SAMPLE_RATE = 16000  # 16kHz 单声道 16bit

# 文件名 -> (类型, 频率Hz, 时长秒)
SAMPLES = {
    "wakeup_normal.wav": ("tone", 800, 1.5),
    "mis_wake_noise.wav": ("tone", 500, 1.0),
    "cmd_volume_up.wav": ("tone", 1000, 1.2),
    "wakeup_noisy.wav": ("noise", 0, 2.0),
}


def synthesize(kind, freq, seconds):
    """合成音频帧：tone 为正弦波，noise 为固定种子的白噪声。"""
    rng = random.Random(42)
    frames = bytearray()
    for i in range(int(SAMPLE_RATE * seconds)):
        if kind == "tone":
            value = int(20000 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
        else:
            value = rng.randint(-12000, 12000)
        frames += struct.pack("<h", value)
    return bytes(frames)


def main():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    for name, (kind, freq, seconds) in SAMPLES.items():
        path = os.path.join(AUDIO_DIR, name)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(synthesize(kind, freq, seconds))
        print(f"生成示例音频：{path}（{seconds:.1f}s）")
    print("完成。示例音频为纯合成信号，可安全提交至公开仓库。")


if __name__ == "__main__":
    main()
