# Brand in AI

[English](README.md) | 简体中文

Brand in AI 是一个用于衡量品牌或产品在 AI 模型回答中曝光情况的技能包。它将用户提供的多语言问题发送到模型提供商的官方 API，对回答进行独立采样，并汇总品牌提及、推荐排名和引用链接。

## 环境要求

- Linux、macOS 或 Windows，Python 3.10 或更高版本；无需第三方 Python 依赖。
- 运行实际采样时，需要对应提供商的 API 凭据。请求可能产生费用。

## 快速开始

支持技能的 Agent 可按照其安装说明，将 `skills/brand-in-ai` 安装或复制到技能目录。其他 Agent 可将 [SKILL.md](skills/brand-in-ai/SKILL.md) 作为指令，并提供对仓库和 Python 的访问权限。安装方式和工具权限取决于所用 Agent。

1. 复制示例配置并填写品牌、已确认的别名和问题：

   ```sh
   cp skills/brand-in-ai/references/example.json config.json
   ```

2. 编辑 `config.json`，选择提供商和模型。每个问题需要唯一的 `id`、语言标签 `language` 和原文 `text`。`samples` 默认为每个问题、每个模型 5 次；`report_language` 可设为 `zh` 或 `en`。省略 `models` 会选择所有注册的提供商。
3. 设置所选提供商的环境变量，例如 `export OPENAI_API_KEY="你的密钥"`。凭据名称、模型、搜索模式和地域要求见[提供商配置](skills/brand-in-ai/references/providers.md)。豆包需要显式指定模型或推理端点 ID。
4. 在项目根目录预览并运行：

   ```sh
   python3 skills/brand-in-ai/scripts/run.py config.json --preview
   python3 skills/brand-in-ai/scripts/run.py config.json --run-dir results/run-001
   ```

预览不会调用提供商。要继续同一次运行，请保留运行目录并使用原配置：

Windows PowerShell 中可使用 `Copy-Item` 代替 `cp`，使用 `$env:OPENAI_API_KEY = "你的密钥"` 设置凭据，并将命令中的 `python3` 换成 `python`（或 `py`）。

```sh
python3 skills/brand-in-ai/scripts/run.py config.json --resume results/run-001
```

## 结果与解读

运行目录包含 `report.md`（摘要）、`report.json`（统计）和 `samples.jsonl`（原始回答）。比较结果时应使用相同的问题集和搜索模式，并关注缺失覆盖。问题本身提到目标品牌时，应与无提示的品牌提及区分。搜索是否实际发生取决于提供商返回的证据，不能仅凭请求了搜索模式判断。

完整工作流程见 [Skill 说明](skills/brand-in-ai/SKILL.md)。截至 2026-11-18，十二个提供商的实时 API 验证仍待完成；离线测试使用手写样例，生产运行前请核对提供商文档并先发送测试请求。

## 测试

```sh
python3 -m unittest discover -s tests -v
```
