# CorrectionKit

[English](README.md) | 简体中文

**你到底多久需要纠正一次 Codex？**

CorrectionKit 是一个极小的、本地优先的 Codex 纠错计数器。原生 Hook 会识别“不要猜”“不是这个意思”等明确纠错，只保存分类和不含原文的事件元数据；你还可以观察批准一条规则后，纠错负担是否发生变化。

无账号、无服务端、无后台模型、无运行时依赖。数据库不保存对话原文，也不保存原文指纹。

```text
你纠正 Codex
      ↓
本地短语识别 → 待确认事件 → 人工审核 → 可选规则
                                          ↓
                               后续会话纠错率
```

## 安装

前提：Codex CLI 或带 Codex 的 ChatGPT 桌面端，以及 Python 3.9 以上版本。

从 GitHub 安装：

```bash
codex plugin marketplace add sophialeeee/correction-kit --ref main
codex plugin add correction-kit@correction-kit
```

重启 ChatGPT 桌面端或新建 Codex 会话，然后打开 `/hooks`，检查并信任两个 CorrectionKit Hook。Codex 默认不会执行未经本人确认的新 Hook。

若希望直接使用命令行：

```bash
python3 -m pip install .
correction-kit doctor
```

## 常用命令

```bash
correction-kit list
correction-kit show 1
correction-kit confirm 1 --rule "推断字段前先读取用户给出的接口定义。"
correction-kit dismiss 2
correction-kit report
correction-kit report --json
correction-kit rules
```

`UserPromptSubmit` Hook 自动统计用户回合并识别中英文明确纠错。`SessionStart` Hook 只加载用户批准的抽象规则，而且当前请求始终优先。

## 为什么故意做小

CorrectionKit 不是又一个 Agent Memory 框架。它只做一件事：用最小且可检查的本地机制，让你的纠错负担变得可见。

| 项目 | CorrectionKit |
|---|---|
| 运行时 | 一个 Python 标准库文件 |
| 采集 | Codex 原生生命周期 Hook |
| 保存对话原文 | 不保存 |
| 保存原文指纹 | 不保存 |
| 规则生效 | 必须人工批准 |
| 网络请求 | 没有 |
| 输出 | 审核队列、终端报告、聚合 JSON |

完整边界见 [PRIVACY.md](PRIVACY.md)。

## 六类纠错

- `intent_mismatch`：理解错目标。
- `unsupported_assumption`：没有依据地猜测。
- `ignored_context`：忽略已提供的信息。
- `scope_overreach`：越权执行。
- `incomplete_verification`：未充分验证就宣称完成。
- `implementation_error`：实现仍然不能工作。

## 局限

- v0.1 使用小规模确定性短语表，候选事件必须人工审核。
- 前后对比只是个人观察指标，不能证明规则导致了变化。
- 目前只支持 Codex。
- 规则是指令，不保证 Agent 一定遵守。

## 排障

- 没有候选事件：打开 `/hooks` 检查并信任 Hook，然后新建会话。
- 误报：运行 `correction-kit dismiss <id>`。
- 规则未加载：先用 `correction-kit rules` 确认存在已批准规则，再新建会话。

## 开发

```bash
python3 -m unittest discover -s tests -v
```

数据库默认位于 `~/.local/share/correction-kit/corrections.db`。

## 参与贡献

增加短语前，请先说明真实的漏报或误报类别，但不要提交私人对话、代码或密钥。每个 Pull Request 至少包含一个聚焦测试。

## 许可证

[MIT](LICENSE)
