# -*- coding: utf-8 -*-
"""
电视语音助手音频自动化压测主脚本（自动扫描版本）
====================================================
基于 Python + ADB 实现语音助手自动化回归/压测，支持双模式运行：
  1. 真实硬件模式：ADB 连接电视设备，推送/播放 wav、清空并抓取 logcat、解析判定、保存日志、输出 CSV。
  2. 模拟日志兜底模式：无 ADB 设备时使用内置 mock 日志，保证可本地演示调试。

用例来源：自动扫描 audio/ 目录下所有 wav 文件，无需写死用例列表。
每次测试只需把本次的音频文件放入 audio/ 目录，脚本会自动逐一执行。

用法：
    python audio_test.py                      # 自动检测设备，执行 audio/ 下全部 wav
    python audio_test.py --serial <序列号>    # 多设备时指定某台电视
    python audio_test.py --loop 20            # 每条用例循环执行 20 次（压测模式，输出通过率）
    python audio_test.py --mock               # 强制模拟日志模式
    python audio_test.py --audio-dir <目录>   # 指定音频目录

退出码：0=全部通过；1=存在 FAIL；2=存在 ERROR（链路失败/日志无法判定）。
"""
import os
import sys
import csv
import time
import wave
import argparse
import subprocess
from datetime import datetime

# Windows 控制台默认 GBK，防止 emoji/中文输出触发 UnicodeEncodeError
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ====================== 项目基础配置 ======================
# skill 自包含：所有资源目录基于脚本所在目录的上一级（skill 根目录）自动定位
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
LOG_DIR = os.path.join(BASE_DIR, "logs")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# ====================== 结果常量 ======================
# 预期配置（DEFAULT_EXPECT / EXPECT_RESULTS）与日志解析（parse_voice_log）共用同一组常量，
# 避免两套字符串各自维护、拼写不一致导致整批误判。
RES_WAKE_OK = "唤醒成功"
RES_WAKE_FAIL = "唤醒失败"
RES_MISWAKE = "发生误唤醒"
RES_NO_MISWAKE = "不误唤醒"
RES_VOL_UP = "音量调高成功"
RES_UNDETERMINED = "无法判定"

# 日志关键字 -> 实际结果，按优先级从上到下匹配；日志为空/无任何关键字时返回"无法判定"（结论记 ERROR）。
LOG_KEYWORDS = [
    ("wakeup_fail", RES_WAKE_FAIL),
    ("mis_wakeup", RES_MISWAKE),
    ("exec command volume up ok", RES_VOL_UP),
    ("wakeup_success", RES_WAKE_OK),
]

# ====================== 用例配置 ======================
# 默认预期结果：扫描到的音频若未在 EXPECT_RESULTS 中单独配置，则使用该值作为预期。
DEFAULT_EXPECT = RES_WAKE_OK

# 特例预期映射：音频文件名 -> 预期结果。
# 仅当某用例的预期结果与 DEFAULT_EXPECT 不同时，在此补一行；否则无需配置。
EXPECT_RESULTS = {
    "mis_wake_noise.wav": RES_NO_MISWAKE,
    "cmd_volume_up.wav": RES_VOL_UP,
}

# 模拟日志（ADB 无法连接设备时自动启用，仅用于本地演示）
# 已知演示音频用对应的 mock 日志；audio/ 里有但未在此配置的音频，演示时用 DEFAULT_MOCK_LOG。
MOCK_LOG_DICT = {
    "wakeup_normal.wav": "I/VoiceService: wakeup_success\nI/VoiceService: ready receive command",
    "mis_wake_noise.wav": "I/VoiceService: idle standby",
    "cmd_volume_up.wav": "I/VoiceService: wakeup_success\nI/VoiceService: exec command volume up ok",
    "wakeup_noisy.wav": "I/VoiceService: wakeup_fail"
}
DEFAULT_MOCK_LOG = "I/VoiceService: wakeup_success"

# 真实模式下推送到设备的音频路径
DEVICE_AUDIO_PATH = "/sdcard/test_audio.wav"


# ====================== 命令行参数 ======================
def parse_args():
    p = argparse.ArgumentParser(description="电视语音助手音频自动化压测（自动扫描 audio/ 目录）")
    p.add_argument("--serial", help="指定 ADB 设备序列号（多设备时建议指定；默认取第一台在线设备）")
    p.add_argument("--loop", type=int, default=1,
                   help="每条用例循环执行次数（压测模式，输出通过率，默认 1）")
    p.add_argument("--mock", action="store_true",
                   help="强制使用模拟日志模式（忽略真实设备，仅供演示调试）")
    p.add_argument("--audio-dir", help="指定音频目录（默认 skill 根目录下 audio/）")
    return p.parse_args()


# ====================== 用例扫描 ======================
def scan_audio_cases(audio_dir):
    """扫描指定目录下所有 wav 文件，作为本次要执行的测试用例。"""
    if not os.path.isdir(audio_dir):
        return []
    wav_files = sorted(f for f in os.listdir(audio_dir) if f.lower().endswith(".wav"))
    return [
        {"audio": f, "expect": EXPECT_RESULTS.get(f, DEFAULT_EXPECT)}
        for f in wav_files
    ]


# ====================== 日志解析 ======================
def parse_voice_log(log_text):
    """靠关键字提取实际结果。空日志/无关键字返回 RES_UNDETERMINED（由主流程记为 ERROR）。"""
    if not log_text or not log_text.strip():
        return RES_UNDETERMINED
    for keyword, result in LOG_KEYWORDS:
        if keyword in log_text:
            return result
    return RES_NO_MISWAKE


# ====================== ADB 设备交互 ======================
def adb_base(serial):
    """构造带设备序列号的 adb 基础命令，避免多设备时命令歧义。"""
    return ["adb"] + (["-s", serial] if serial else [])


def detect_adb_device(prefer_serial=None):
    """检测 ADB 环境与在线设备。

    返回 (serial, status, message)：
      status = "online"    -> serial 为可用设备序列号
      status = "no-adb"    -> 本机未安装/不可用 adb
      status = "no-device" -> 有 adb 但无可用设备（未连接或未授权）
    """
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=5)
    except FileNotFoundError:
        return None, "no-adb", "⚠️ 未找到 adb 命令（请安装 platform-tools 并加入 PATH）"
    except Exception:
        return None, "no-adb", "⚠️ adb devices 执行异常"

    devices = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            devices.append((parts[0], parts[1]))

    online = [s for s, state in devices if state == "device"]
    unauthorized = [s for s, state in devices if state == "unauthorized"]

    if prefer_serial:
        if prefer_serial in online:
            return prefer_serial, "online", ""
        return None, "no-device", (
            f"⚠️ 指定设备 {prefer_serial} 不在线（当前在线设备：{online or '无'}）"
        )
    if online:
        msg = ""
        if len(online) > 1:
            msg = f"ⓘ 检测到多台设备，默认使用第一台 {online[0]}，可用 --serial 指定"
        return online[0], "online", msg
    if unauthorized:
        return None, "no-device", (
            f"⚠️ 设备 {unauthorized} 已连接但未授权 USB 调试，请在电视上确认授权弹窗"
        )
    return None, "no-device", "⚠️ 未检测到在线 ADB 设备（请确认电视已上电、USB 调试已开启）"


def clear_device_log(serial):
    """清空 logcat 缓冲区，避免上一条用例的日志串扰本条判定。"""
    try:
        subprocess.run(adb_base(serial) + ["logcat", "-c"],
                       capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def get_device_log(serial, timeout_sec=3):
    """抓取语音服务 VoiceService 日志。"""
    try:
        cmd = adb_base(serial) + ["logcat", "-d", "VoiceService:*", "*:S"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        return result.stdout or ""
    except Exception:
        return ""


def push_audio_to_device(serial, local_audio_path):
    """推送音频文件到电视设备，失败返回 False。"""
    try:
        result = subprocess.run(
            adb_base(serial) + ["push", local_audio_path, DEVICE_AUDIO_PATH],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0 and "error" not in (result.stderr or "").lower()
    except Exception:
        return False


def play_audio_on_device(serial):
    """调用媒体播放器播放音频，触发语音服务，失败返回 False。"""
    try:
        cmd = adb_base(serial) + [
            "shell", "am", "start", "-a", "android.intent.action.VIEW",
            "-d", f"file://{DEVICE_AUDIO_PATH}", "-t", "audio/wav"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0 and "error" not in output.lower()
    except Exception:
        return False


def get_wav_duration(path):
    """读取 wav 时长（秒），读取失败返回 None。"""
    try:
        with wave.open(path, "rb") as w:
            rate = w.getframerate() or 1
            return w.getnframes() / float(rate)
    except Exception:
        return None


def wait_and_get_log(serial, duration):
    """按音频时长轮询 VoiceService 日志，出现可识别关键字即提前返回，超时返回最新日志。

    等待时长 = max(3s, 音频时长 + 2s)，保证音频播完再下结论（尤其"不误唤醒"类
    用例必须完整播完才有意义）。
    """
    timeout = max(3.0, (duration or 0.0) + 2.0) if duration else 5.0
    if duration:
        print(f"   ⓘ 音频时长约 {duration:.1f}s，等待语音服务处理…")
    deadline = time.time() + timeout
    log = ""
    while True:
        time.sleep(1.0)
        log = get_device_log(serial)
        if any(keyword in log for keyword, _ in LOG_KEYWORDS):
            break
        if time.time() >= deadline:
            break
    return log


def run_real_case(serial, audio_path):
    """执行单条真实硬件链路：推送 -> 清日志 -> 播放 -> 按时长等待并抓取日志。

    返回 (log_content, error_reason)；error_reason 非空表示链路失败（结论记 ERROR）。
    """
    if not push_audio_to_device(serial, audio_path):
        return "", "推送音频到设备失败（请检查 adb 连接与设备存储）"
    if not clear_device_log(serial):
        print("   ⚠️ logcat 清空失败，本条结果可能受历史日志串扰")
    if not play_audio_on_device(serial):
        return "", "触发播放失败（am start 返回错误，请确认设备有可用播放器）"
    duration = get_wav_duration(audio_path)
    log_content = wait_and_get_log(serial, duration)
    return log_content, ""


# ====================== 主流程 ======================
def main():
    args = parse_args()
    loop = max(1, args.loop or 1)

    print("===== 电视语音助手自动化压测脚本【自动扫描版本】=====")

    audio_dir = args.audio_dir or AUDIO_DIR
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 扫描本次要执行的用例
    cases = scan_audio_cases(audio_dir)
    if not cases:
        print("⚠️ %s 目录下没有 wav 音频，请先放入本次要测试的音频文件。" % audio_dir)
        return 0

    # 判断设备是否在线，选择运行模式
    serial = ""
    if args.mock:
        mode = "mock"
        print("ⓘ 已指定 --mock，强制【模拟日志模式】（结果仅供演示，不代表真实设备表现）")
    else:
        serial, status, message = detect_adb_device(args.serial)
        if status == "online":
            mode = "real"
            print(f"✅ 检测到 ADB 设备（{serial}），【真实硬件模式】启动")
            if message:
                print(f"   {message}")
        else:
            mode = "mock"
            print(f"{message}，自动切换【模拟日志模式】（结果仅供演示，不代表真实设备表现）")

    print(f"📂 本次扫描到 {len(cases)} 条用例，每条执行 {loop} 轮：")
    print(f"   {[c['audio'] for c in cases]}")
    print("-" * 50)

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_rows = []
    case_stats = {c["audio"]: {"PASS": 0, "FAIL": 0, "ERROR": 0} for c in cases}
    total_exec = 0

    for case in cases:
        audio_name = case["audio"]
        expect_res = case["expect"]
        audio_path = os.path.join(audio_dir, audio_name)
        stem = os.path.splitext(audio_name)[0]

        for idx in range(1, loop + 1):
            total_exec += 1
            prefix = f"[第 {idx}/{loop} 轮] " if loop > 1 else ""
            print(f"\n{prefix}正在执行用例：{audio_name}")
            note = ""

            if mode == "real":
                # ========= 真实硬件链路 =========
                log_content, err_reason = run_real_case(serial, audio_path)
                if err_reason:
                    actual_res = RES_UNDETERMINED
                    note = err_reason
                else:
                    actual_res = parse_voice_log(log_content)
                    if actual_res == RES_UNDETERMINED:
                        note = "日志中未出现任何可识别关键字，请人工查看原始日志"
            else:
                # ========= 模拟兜底链路 =========
                if audio_name in MOCK_LOG_DICT:
                    log_content = MOCK_LOG_DICT[audio_name]
                else:
                    log_content = DEFAULT_MOCK_LOG
                    note = "演示模式：该音频未配置 mock 日志，使用默认日志"
                actual_res = parse_voice_log(log_content)

            # 保存原始日志（文件名含日期+轮次，避免跨天/同秒冲突）
            log_filename = f"{run_stamp}_L{idx:02d}_{stem}.log"
            with open(os.path.join(LOG_DIR, log_filename), "w", encoding="utf-8") as f:
                f.write(log_content)

            # 判定结论：链路失败/日志无法判定记 ERROR，绝不参与 PASS
            if actual_res == RES_UNDETERMINED:
                conclusion = "ERROR"
            elif actual_res == expect_res:
                conclusion = "PASS"
            else:
                conclusion = "FAIL"

            case_stats[audio_name][conclusion] += 1
            report_rows.append({
                "轮次": idx,
                "测试用例": audio_name,
                "预期结果": expect_res,
                "实际结果": actual_res,
                "测试结论": conclusion,
                "运行模式": "真实硬件" if mode == "real" else "模拟日志",
                "设备序列号": serial if mode == "real" else "-",
                "日志文件": log_filename,
                "备注": note,
            })
            print(f"预期:{expect_res} | 实际:{actual_res} | {conclusion}"
                  + (f"（{note}）" if note else ""))

    # 输出 CSV 测试报告
    csv_name = f"voice_test_report_{run_stamp}.csv"
    csv_full = os.path.join(OUTPUT_DIR, csv_name)
    headers = ["轮次", "测试用例", "预期结果", "实际结果", "测试结论",
               "运行模式", "设备序列号", "日志文件", "备注"]
    with open(csv_full, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(report_rows)

    # 汇总统计
    n_pass = sum(s["PASS"] for s in case_stats.values())
    n_fail = sum(s["FAIL"] for s in case_stats.values())
    n_err = sum(s["ERROR"] for s in case_stats.values())
    rate = n_pass * 100.0 / total_exec if total_exec else 0.0

    print("\n" + "=" * 50)
    print(f"📊 汇总：用例 {len(cases)} 条 | 执行 {total_exec} 次 | "
          f"PASS {n_pass} | FAIL {n_fail} | ERROR {n_err} | 通过率 {rate:.1f}%")
    if loop > 1:
        for name, s in case_stats.items():
            print(f"   {name}: PASS {s['PASS']}/{loop}（{s['PASS'] * 100 // loop}%）"
                  + (f"，FAIL {s['FAIL']}" if s["FAIL"] else "")
                  + (f"，ERROR {s['ERROR']}" if s["ERROR"] else ""))
    print(f"📄 测试报告：{csv_full}")
    print(f"📄 原始日志目录：{LOG_DIR}")

    if n_fail:
        return 1
    if n_err:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
