# SteerOnce

[English](README.md) | 简体中文

**让 AI 记住你怎么做事。**

SteerOnce 把你的纠正提炼成可跨 Session 使用的私人工作偏好。正在回答当前回合的 Codex 模型总结“下次应该怎么做”，你决定这条偏好全局生效、只在当前项目生效，还是忽略。

它是透明可控的个人偏好层，不是真正修改模型权重的微调：无账号、无服务端、无额外模型调用、无运行时依赖，也不保存对话原文、Embedding 或原文指纹。

```text
你纠正 Codex → 当前模型提炼工作偏好
                         ↓
              全局保存 / 当前项目 / 忽略
                         ↓
               下个 Session 加载相关偏好
```

## 安装

前提：Codex CLI 或带 Codex 的 ChatGPT 桌面端，以及 Python 3.9 以上版本。

从 GitHub 安装：

```bash
codex plugin marketplace add sophialeeee/steeronce --ref main
codex plugin add steeronce@steeronce
```

重启 ChatGPT 桌面端或新建 Codex 会话。需要审核变更后的 Hook 时，在终端启动 `codex`，输入 `/hooks`，检查并信任三个 SteerOnce Hook 的确切定义。

若希望直接使用命令行：

```bash
python3 -m pip install .
steeronce doctor
```

## 常用命令

```bash
steeronce list
steeronce show 1
steeronce confirm 1 --scope project
steeronce dismiss 2
steeronce report
steeronce report --json
steeronce preferences
```

`UserPromptSubmit` Hook 给每个用户回合生成匿名本地事件编号。当前 Codex 模型根据完整上下文判断这是长期工作偏好还是一次性要求，并向用户展示抽象建议。回答结束后，`Stop` Hook 把建议保存为未生效候选；`SessionStart` Hook 只加载已批准的全局偏好，以及与当前工作目录哈希匹配的项目偏好。当前请求始终优先。

例如：

```text
你：我只是让你诊断，没让你直接改代码。
Codex：……
SteerOnce 建议记住：
“诊断时先给原因和证据，未明确要求时不要修改文件。”
全局保存 / 仅当前项目 / 忽略？
```

## 为什么故意做小

SteerOnce 不试图保存所有个人事实或对话。它只闭合一个可审计回路：纠正、抽象工作偏好、人工选择范围、跨 Session 加载，再观察同类纠正是否减少。

| 项目 | SteerOnce |
|---|---|
| 运行时 | 一个 Python 标准库文件 |
| 学习信号 | 用户明确纠正和批准 |
| 保存的语义内容 | 抽象工作偏好 |
| 项目标识 | 本地工作目录的单向哈希 |
| 保存对话原文 | 不保存 |
| 保存原文指纹 | 不保存 |
| 偏好生效 | 必须人工批准 |
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

每条偏好还有作用范围（`global` 或 `project`）和触发场景，例如诊断、实现或研究。项目偏好只会在相同工作目录启动的新 Session 中加载。

## 历史统计

安装后，新回合会进行语义判断。旧 Codex 会话只在本地统计回合数，不再用关键词猜测哪些话是纠错：

```bash
steeronce scan ~/.codex/sessions
```

旧版候选仍可用 `show <id>` 从原始本地会话临时查看；新语义候选不保存会话路径，也没有原文预览。

旧短语识别器产生的未审核候选不会被删除，但默认列表和报表会排除它们。如需检查，可显式运行 `steeronce list --include-legacy`。

## 局限

- 语义提炼仍可能出错，因此候选必须经人工审核才能成为生效偏好。
- 若不把旧对话交给模型，就无法可靠地语义回填；SteerOnce 因隐私边界只统计旧回合，不分类旧原文。
- 前后对比只是个人观察指标，不能证明规则导致了变化。
- 目前只支持 Codex。
- 它改变的是模型上下文，不是模型权重；偏好能加强引导，但不能保证模型一定遵守。

## 排障

- 没有候选事件：在终端启动 `codex`，输入 `/hooks` 检查并信任三个 Hook，然后新建会话。
- 误报：运行 `steeronce dismiss <id>`。
- 偏好未加载：先用 `steeronce preferences` 确认存在已批准偏好，再新建会话。

## 开发

```bash
python3 -m unittest discover -s tests -v
```

数据库默认位于 `~/.local/share/steeronce/corrections.db`。首次运行时会复制已有的 CorrectionKit 数据库，不删除旧文件。

## 参与贡献

请用不含私人上下文的方式报告误报、漏报或分类歧义，不要提交私人对话、代码或密钥。每个 Pull Request 至少包含一个聚焦测试。

## 许可证

[MIT](LICENSE)
