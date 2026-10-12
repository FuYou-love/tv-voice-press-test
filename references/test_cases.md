# 语音助手自动化测试用例

## 用例机制（自动扫描）

脚本会**自动扫描 `audio/` 目录下所有 wav 文件**作为本次要执行的用例，无需维护固定的用例列表。每次测试，只需把本次的音频文件放入 `audio/` 目录即可。

### 预期结果来源
- **默认预期** `DEFAULT_EXPECT`：扫描到的音频若未单独配置，预期结果取此值（脚本顶部可配置，默认"唤醒成功"）。
- **特例预期** `EXPECT_RESULTS`：预期结果与默认不同的音频，在此映射里按文件名补一行。

### 配置示例
```python
# 脚本顶部
DEFAULT_EXPECT = "唤醒成功"          # 大多数用例的默认预期
EXPECT_RESULTS = {
    "mis_wake_noise.wav": "不误唤醒",     # 特例1：预期为不误唤醒
    "cmd_volume_up.wav": "音量调高成功",  # 特例2：预期为音量调高
}
```

## 典型用例示例
| 音频文件 | 预期结果（示例） | 是否需要配置 |
| ---- | ---- | ---- |
| wakeup_normal.wav | 唤醒成功 | 否（命中默认预期） |
| mis_wake_noise.wav | 不误唤醒 | 是（加入 EXPECT_RESULTS） |
| cmd_volume_up.wav | 音量调高成功 | 是（加入 EXPECT_RESULTS） |
| wakeup_noisy.wav | 唤醒成功 | 否（命中默认预期） |

## 前置条件
1. 电视语音助手功能正常，已上电启动、USB 调试已授权（真实硬件模式）
2. 本次要测的 wav 音频已放入 `audio/` 目录
3. ADB 可以正常连接电视设备（真实硬件模式）；本机已安装 platform-tools

## 执行步骤（脚本自动完成）
1. 扫描 `audio/` 目录，确定本次用例
2. 将 wav 音频推送至电视存储目录（失败则该用例记 ERROR，不产生假 PASS）
3. 清空 logcat 缓冲区，避免上一条用例日志串扰本条判定
4. 播放音频，给电视输入语音信号
5. 按 wav 时长轮询抓取 VoiceService 日志，出现结果关键字提前返回；超时且无任何关键字则记 ERROR
6. 解析日志，判断实际结果，与预期结果对比，判定 PASS / FAIL / ERROR
7. 保存日志、输出 CSV 测试报告（含轮次、运行模式、设备序列号、日志文件、备注列），控制台输出通过率汇总

## 压测模式

加 `--loop N` 可让每条用例循环执行 N 次，控制台会输出每条用例的通过率（如 `wakeup_normal.wav: PASS 19/20（95%）`），用于评估唤醒稳定性。多设备时用 `--serial` 指定设备。


> 模拟模式运行结果示例：wakeup_normal/mis_wake_noise/cmd_volume_up PASS，wakeup_noisy FAIL（对应缺陷见 bug_list.md 的 BUG001）。完整报告以 `output/voice_test_report_*.csv` 为准。
