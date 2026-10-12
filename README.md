# tv-voice-press-test 电视语音助手音频自动化压测

[![CI](https://github.com/FuYou-love/tv-voice-press-test/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

对电视语音助手的**语音唤醒 / 语音指令 / 误唤醒**功能做自动化回归与压测。自动扫描 `audio/` 目录下的 wav 用例，通过 ADB 与电视设备交互，解析 VoiceService 日志判定 PASS / FAIL / ERROR，输出 CSV 报告与通过率汇总。无设备时自动降级为模拟日志模式，开箱即可演示。

```
audio/*.wav ──► 扫描用例 ──► ADB 推送/播放 ──► 清空并抓取 logcat ──► 关键字解析
     │                                                            │
     └── 预期配置（默认值 + 特例映射） ──────────────► 比对判定 ──► logs/ + output/*.csv
```

## 功能特性

- **自动扫描用例**：把 wav 放进 `audio/` 即可，无需维护用例列表
- **双模式**：真实硬件模式（ADB）+ 模拟日志兜底模式（本地演示/CI）
- **防误判设计**：每条用例前清空 logcat 防串扰；按 wav 时长轮询日志；链路失败/日志无关键字记 `ERROR`，不产生假 PASS
- **压测模式**：`--loop N` 循环执行并统计每条用例通过率
- **CI 友好**：退出码 `0`/`1`/`2` 分别对应 全通过 / 有 FAIL / 有 ERROR
- **零第三方依赖**：仅 Python 标准库（3.7+）

## 快速开始

```bash
git clone https://github.com/FuYou-love/tv-voice-press-test.git
cd tv-voice-press-test
python scripts/audio_test.py            # 无设备时自动进入模拟模式
```

真实硬件模式需满足：本机安装 [ADB](https://developer.android.com/tools/releases/platform-tools) 并加入 PATH、电视已上电并开启 USB 调试授权。

### 命令行参数

| 参数 | 说明 |
| ---- | ---- |
| （无参数） | 自动检测设备；在线走真实硬件模式，离线走模拟日志模式 |
| `--serial <序列号>` | 多设备时指定某台电视 |
| `--loop <N>` | 每条用例循环执行 N 次（压测模式，输出通过率） |
| `--mock` | 强制模拟日志模式，忽略真实设备 |
| `--audio-dir <目录>` | 指定音频目录（默认 `audio/`） |

### 退出码

`0` = 全部通过；`1` = 存在 FAIL；`2` = 存在 ERROR（链路失败或日志无法判定）。

## 测试报告

- `output/voice_test_report_<时间戳>.csv`：明细结果，列为 `轮次 / 测试用例 / 预期结果 / 实际结果 / 测试结论 / 运行模式 / 设备序列号 / 日志文件 / 备注`（UTF-8-SIG，Excel 可直接打开）
- `logs/<时间戳>_L<轮次>_<用例名>.log`：每条执行一份原始日志，供失败用例回溯

模拟模式演示输出（`wakeup_noisy.wav` 为已知缺陷 BUG001 的复现用例）：

```
📊 汇总：用例 4 条 | 执行 4 次 | PASS 3 | FAIL 1 | ERROR 0 | 通过率 75.0%
```

## 用例与预期配置

- 默认预期：`scripts/audio_test.py` 顶部 `DEFAULT_EXPECT`（默认"唤醒成功"）
- 特例预期：`EXPECT_RESULTS` 按文件名覆盖（如 `mis_wake_noise.wav` → "不误唤醒"）
- 预期值使用脚本顶部 `RES_*` 常量，与日志解析共用，避免拼写不一致导致误判

详见 [references/test_cases.md](references/test_cases.md)。

## 真实硬件模式说明与局限

脚本通过媒体播放器经电视喇叭播放音频，依赖电视麦克风回采触发 VoiceService。若目标设备不支持该链路（如远场拾音 DSP 不接媒体通道），需改用音频注入方式，并对结果做人工确认。已知缺陷记录见 [references/bug_list.md](references/bug_list.md)。

## 仓库结构

```
├── SKILL.md                     # AI Agent skill 说明（触发与使用规则）
├── scripts/
│   ├── audio_test.py            # 压测主脚本
│   └── make_sample_audio.py     # 合成示例音频生成器（无版权风险）
├── audio/                       # 测试音频（真实音频不入库，见 .gitignore）
├── references/                  # 用例机制说明与缺陷清单
├── logs/                        # 运行时原始日志（自动生成）
└── output/                      # 运行时 CSV 报告（自动生成）
```

## License

[MIT](LICENSE)
