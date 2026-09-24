# 墨尔本 MMI 面试练习工具 · Melbourne MMI Trainer

[English](README.md) | **简体中文**

这是一个给准备墨尔本 MMI 面试的同学使用的免费开源工具。安装在自己的电脑上，填入 API key 后，就可以按倒计时回答问题、录音，并查看文字转录和 AI 反馈。

**软件免费，不限练习次数，无需注册或订阅。** 使用 DeepSeek 和 Deepgram 时，API 费用由你自己的账户承担。代码和内置题库采用 MIT 开源许可。

## 作者使用的两个 API

本项目作者实际使用的配置是：

| 服务 | 用途 | 配置变量 |
| --- | --- | --- |
| **DeepSeek** | 根据文字回答提供 AI 评价、简洁答题结构和英文参考答案 | `DEEPSEEK_API_KEY` |
| **Deepgram** | 把每道题的回答录音转换为英文文字 | `DEEPGRAM_API_KEY` |

默认评价模型为 `deepseek-v4-pro`；默认转录模型为 `nova-3`，语言为 `en-AU`。两个 key 分别在 [DeepSeek 平台](https://platform.deepseek.com/) 和 [Deepgram 控制台](https://console.deepgram.com/) 创建。网页聊天会员与 API 账户额度不一定相通。

目前程序接入的是这两个服务。要换成其他厂商，可能需要修改 `services/evaluation.py` 或 `services/transcription.py`，仅替换 key 不一定能用。DeepSeek 使用的是 [Responses API](https://api-docs.deepseek.com/guides/responses_api/)，不是 Chat Completions。

## 功能

- **30 组原创练习题（station），共 120 道问题**，涵盖团队合作、伦理、沟通、动机与反思、公共与乡村健康、专业素养、文化敏感性、决策八类主题。
- 不同主题交替安排，数量尽量均衡。选题时只显示 Station 1、Station 2 等编号，不提前透露主题。
- 先读 **60 秒 Scenario**，再依次回答四道相关问题，每题 **15 秒准备 + 60 秒回答**。
- Scenario 阅读结束后消失；当前 Question 在准备和回答期间一直显示。
- 浏览器录音、语音转文字、可编辑转录、保存在本机的练习历史。
- 练习界面为英文。答题思路主要用中文解释，保留实用的英文关键词，另附英文参考答案。
- 无 API 时可以手动输入转录，使用基础本地反馈与题库参考答案。

本项目由个人开发，与墨尔本大学无隶属关系。内置题目由 AI 辅助编写，用于模拟练习，并非保密真题或商业题库中的题目。实际面试的计时和流程请以你的面试邀请为准，AI 评分仅供练习参考。

## 安装

需要 **Python 3.10 或更新版本**，建议从 Python 3.11 开始，并使用支持麦克风录音的浏览器。

### macOS / Linux

在终端中运行：

```bash
git clone https://github.com/booksiyideEdward/melbourne-mmi-trainer.git
cd melbourne-mmi-trainer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### Windows PowerShell

```powershell
git clone https://github.com/booksiyideEdward/melbourne-mmi-trainer.git
cd melbourne-mmi-trainer
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

如果 PowerShell 不允许激活虚拟环境，可以直接使用 `.venv\Scripts\python.exe -m pip install -r requirements.txt` 安装依赖，之后用 `.venv\Scripts\python.exe app.py` 启动。

## 配置和启动

用文本编辑器打开 `.env`，填入自己的 key：

```dotenv
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPGRAM_API_KEY=你的Deepgram密钥
```

不要把真实密钥写进前端脚本或上传到 GitHub。其他模型与服务地址配置保留在 `.env.example` 中，可按需要调整。

启动：

```bash
python app.py
```

打开 **http://127.0.0.1:8765/**，允许麦克风访问，并保持终端运行。不要双击 `templates/index.html`：页面需要 Python 服务加载样式、处理录音和调用 API。

## 如何练习

1. 选择 station，检查麦克风。
2. 阅读 Scenario，依次完成四道问题。
3. 在复盘页面（Review）检查语音转文字有没有出错，修改后再请求 AI 评价。
4. 学习简洁的答题结构，再做一次口头练习。

没有 Deepgram key 时，可以手动输入文字回答；没有 DeepSeek key 时，程序会根据简单规则给出反馈，并显示题库中已有的参考答案。这种反馈比较基础，不能替代模型对回答内容的分析。

## 拍照看题与手机端提示词

打开 **http://127.0.0.1:8765/scan**，还可以上传题目图片。先发送 Scenario，让它记住背景，再发送想分析的 Question，题数不限。这项功能需要能识图的模型，可以使用同一个 DeepSeek key，模型由 `SCAN_COACH_*` 配置。只做计时练习的话，无需使用它。

如果更习惯手机上的多模态聊天应用，也可以把 [MMI 提示词文档](DeepSeek_MMI_Image_Coach_Harness.md) 作为新对话的第一条消息，再上传题目图片，让模型输出简洁结构与参考答案。

## 数据保存在哪里

录音、转录与练习历史保存在自己电脑的 `instance/` 目录。转录时，音频发送给 Deepgram；评价时，背景、问题与文字回答发送给 DeepSeek。拍照看题功能会把上传图片和相关背景发送给 DeepSeek。服务商的数据保留规则由其各自条款决定。

程序默认只能通过本机地址 `127.0.0.1` 访问。它没有多用户登录功能，如需部署到公网，还要另外处理访问权限。`.env`、录音和本地数据库已加入 Git 忽略规则，不会在正常提交代码时一并上传。

## 扩充题库与贡献

首版保留 30 个 station。可以逐步扩充到 100 个，但更重要的是避免重复、确保四问各有重点，并让参考答案能够在一分钟内自然说完。

你可以把 [题库扩充指南](docs/ADDING_STATIONS.md) 交给 Codex，按现有 JSON 格式分批添加题目。指南里有可复制的提示词，以及检查题目和答案的具体要求。八类主题的数量应尽量均衡。已有题目的标题与背景尽量保持不变，因为程序会用它们生成 station ID。

欢迎提交原创题目、安装改进与问题修复。请勿提交保密面试回忆、付费题库导出、私人回答转录或 API 密钥。

## 开发验证

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

测试会模拟 API 返回结果，不产生 API 费用。检查内容包括题库是否完整、主题分布是否均衡、转录和历史记录接口是否正常，以及拍照看题是否影响练习记录。有 Node.js 时还可运行：

```bash
node --check static/app.js
node --check static/scan/scan.js
```

自动测试能检查数据格式、字数和主题分布；题目与答案的教学质量仍需人工审阅。

## 常见问题

- **页面只有文字、没有排版：** 打开 localhost 地址，不要直接打开 HTML 文件。
- **麦克风不可用：** 检查浏览器和系统的麦克风权限，也可以选择手动转录模式。
- **API 未就绪：** 检查 `.env`、API 额度和模型权限，修改后重启 Python。
- **无法连接网站：** 运行 `python app.py` 并保持终端开启。
- **端口被占用：** 在 `.env` 中设置 `PORT=8766`，重启后使用对应地址。
- **更新后仍显示旧页面：** Mac 按 Command–Shift–R，Windows 按 Ctrl–Shift–R。

## 开源许可

[MIT License](LICENSE)：允许使用、修改和再分发，也允许商业再利用。本项目自身免费提供。
