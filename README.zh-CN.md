# SteerOnce

[English](README.md) | 简体中文

**同一个错误，别让我纠正第二次。**

SteerOnce 把你批准过的纠正变成 Codex 可复用的本地规则。正在回答当前回合的 Codex 模型理解你是否在纠正它；SteerOnce 只保存分类和不含原文的事件元数据，并在后续会话中加载你批准的抽象规则。

无账号、无服务端、无额外模型调用、无运行时依赖。数据库不保存对话原文，也不保存原文指纹。

```text
你纠正 Codex
      ↓
当前 Codex 语义判断 → 分类 → 待确认事件 → 人工审核 → 可选规则
                                          ↓
                               后续会话纠错率
```

## 安装

前提：Codex CLI 或带 Codex 的 ChatGPT 桌面端，以及 Python 3.9 以上版本。

从 GitHub 安装：

```bash
codex plugin marketplace add sophialeeee/steeronce --ref main
codex plugin add steeronce@steeronce
```

重启 ChatGPT 桌面端或新建 Codex 会话。需要审核变更后的 Hook 时，在终端启动 `codex`，输入 `/hooks`，检查并信任两个 SteerOnce Hook 的确切定义。

若希望直接使用命令行：

```bash
python3 -m pip install .
steeronce doctor
```

## 常用命令

```bash
steeronce list
steeronce show 1
steeronce confirm 1 --rule "推断字段前先读取用户给出的接口定义。"
steeronce dismiss 2
steeronce report
steeronce report --json
steeronce rules
```

`UserPromptSubmit` Hook 给每个用户回合生成匿名本地事件编号。正在处理本轮对话的 Codex 模型根据完整语义判断是否属于明确纠错，而不是查短语表；它只把事件编号和六类之一交给本地脚本，不会再发起一次模型或网络请求。`SessionStart` Hook 只加载用户批准的抽象规则，而且当前请求始终优先。

## 为什么故意做小

SteerOnce 不是又一个 Agent Memory 框架。它只闭合一个回路：发现纠正、人工批准、复用本地规则，再观察后续纠错负担。

| 项目 | SteerOnce |
|---|---|
| 运行时 | 一个 Python 标准库文件 |
| 采集 | Codex Hook + 当前回合语义分类 |
| 保存对话原文 | 不保存 |
| 保存原文指纹 | 不保存 |
| 规则生效 | 必须人工批准 |
| 额外模型/网络请求 | 没有 |
| 输出 | 审核队列、终端报告、聚合 JSON |

完整边界见 [PRIVACY.md](PRIVACY.md)。

## 六类纠错

- `intent_mismatch`：理解错目标。
- `unsupported_assumption`：没有依据地猜测。
- `ignored_context`：忽略已提供的信息。
- `scope_overreach`：越权执行。
- `incomplete_verification`：未充分验证就宣称完成。
- `implementation_error`：实现仍然不能工作。

## 历史统计

安装后，新回合会进行语义判断。旧 Codex 会话只在本地统计回合数，不再用关键词猜测哪些话是纠错：

```bash
steeronce scan ~/.codex/sessions
```

旧版候选仍可用 `show <id>` 从原始本地会话临时查看；新语义候选不保存会话路径，也没有原文预览。

## 局限

- 语义判断仍可能出错，因此候选必须经人工审核才能成为规则。
- 若不把旧对话交给模型，就无法可靠地语义回填；SteerOnce 因隐私边界只统计旧回合，不分类旧原文。
- 前后对比只是个人观察指标，不能证明规则导致了变化。
- 目前只支持 Codex。
- 规则是指令，不保证 Agent 一定遵守。

## 排障

- 没有候选事件：在终端启动 `codex`，输入 `/hooks` 检查并信任 Hook，然后新建会话。
- 误报：运行 `steeronce dismiss <id>`。
- 规则未加载：先用 `steeronce rules` 确认存在已批准规则，再新建会话。

## 开发

```bash
python3 -m unittest discover -s tests -v
```

数据库默认位于 `~/.local/share/steeronce/corrections.db`。首次运行时会复制已有的 CorrectionKit 数据库，不删除旧文件。

## 参与贡献

请用不含私人上下文的方式报告误报、漏报或分类歧义，不要提交私人对话、代码或密钥。每个 Pull Request 至少包含一个聚焦测试。

## 许可证

[MIT](LICENSE)
