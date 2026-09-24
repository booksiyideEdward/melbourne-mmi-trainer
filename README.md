# Melbourne MMI Trainer · 墨尔本 MMI 面试练习工具

Free, open-source interview practice that runs on your own computer. Bring your own speech-to-text and language-model API keys, practise a timed station, then review your transcript and coaching.

**No subscription, no trial quota, no account required by this app.** API providers may charge for usage. The software and included practice bank are released under the MIT license.

[English](README.md) | [完整中文版](README.zh-CN.md) · [Adding stations with Codex](docs/ADDING_STATIONS.md)

## What you get

- **30 original practice stations / 120 questions**, across 8 themes: teamwork, ethics, communication, motivation and reflection, public and rural health, professionalism, cultural sensitivity, and decision-making.
- A balanced station order. The selection screen shows Station 1, Station 2, etc., without revealing the topic.
- **60 seconds to read a scenario**, followed by four connected questions with **15 seconds preparation + 60 seconds answering** each. The scenario disappears after reading; the current question remains visible while preparing and answering.
- Browser microphone recording, English transcription, editable transcripts, and local practice history.
- AI coaching with a concise Chinese-led bilingual answer structure and an English reference answer. Scores are practice feedback, not an admissions prediction.
- A transcript-only option and basic local feedback when API keys are unavailable.
- An optional image coach at `/scan`, and a [reusable chat prompt](DeepSeek_MMI_Image_Coach_Harness.md) for studying questions in a multimodal chat app.

This is an independent practice tool, not an official University of Melbourne product. The included questions are synthetic practice material, not recalled or extracted confidential interview questions. The timing is a practice profile; check your own invitation for the format that applies to you.

## Install and run

Requires **Python 3.10+** and a browser with microphone support. Python 3.11 is a good starting point.

```bash
git clone https://github.com/booksiyideEdward/melbourne-mmi-trainer.git
cd melbourne-mmi-trainer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell, use `py -m venv .venv`, then `.venv\Scripts\Activate.ps1`, and replace the copy command with `Copy-Item .env.example .env`.

Open `.env` in a text editor and fill in:

```dotenv
DEEPSEEK_API_KEY=your_deepseek_key
DEEPGRAM_API_KEY=your_deepgram_key
```

Then start the app:

```bash
python app.py
```

Open **http://127.0.0.1:8765/** and allow microphone access. Keep the terminal running. Do not double-click `templates/index.html`: this app needs its Python server for assets, recordings, and API calls.

## The two APIs

The author's working setup uses **DeepSeek for AI coaching and Deepgram for speech-to-text**. The instructions below follow that setup.

| Provider | Used for | Configuration |
| --- | --- | --- |
| Deepgram | Converting each recorded answer to English text | `DEEPGRAM_API_KEY`; default model `nova-3`, language `en-AU` |
| DeepSeek | Feedback, answer structures, and reference answers from transcripts | `DEEPSEEK_API_KEY`; default model `deepseek-v4-pro` |

Create your own keys in the providers' consoles: [DeepSeek](https://platform.deepseek.com/) and [Deepgram](https://console.deepgram.com/). Keep keys in `.env`; the browser never needs to receive them.

The current adapters are provider-specific. The DeepSeek adapter uses its [Responses API](https://api-docs.deepseek.com/guides/responses_api/), not Chat Completions. A different provider may require changes to `services/evaluation.py` or `services/transcription.py`; changing a model name alone does not guarantee compatibility. Endpoint and model settings are listed in `.env.example`.

The optional `/scan` feature needs a vision-capable model. It can reuse the DeepSeek key, with separate `SCAN_COACH_*` model settings. It is not required for timed practice.

## Practise

1. Choose a station and check your microphone.
2. Read the scenario, then answer the four questions in sequence.
3. Review and correct the transcript before requesting coaching.
4. Use the short answer structure to practise again. Treat the numeric score as a rough coaching signal.

Without Deepgram, enter your transcript manually. Without DeepSeek, the app provides basic heuristic feedback and the bank's authored reference answers. These fallbacks are not equivalent to the full AI workflow.

## Your data

Recordings, transcripts, and history are stored locally under `instance/`. Transcription sends audio to Deepgram; AI evaluation sends the scenario, questions, and transcripts to DeepSeek. The optional image coach sends uploaded images and relevant context to DeepSeek. Provider retention is governed by each provider's terms.

The app binds to `127.0.0.1` and is intended for a single user's computer. It has no multi-user authentication and should not be exposed as a public server without additional work. `.env`, recordings, and the local database are excluded from Git.

## Question bank and contributions

Thirty stations are included so the starting bank stays manageable. More stations are welcome when they add variety and have been reviewed for clarity, fairness, and realistic one-minute answers. No promise is made that a larger bank predicts actual interview coverage.

See [Adding stations with Codex](docs/ADDING_STATIONS.md) for the schema, an authoring prompt, and review criteria. Contribute original scenarios; do not upload private interview recalls, paywalled question-bank exports, personal transcripts, or API keys.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The tests cover timing-related data contracts, station completeness and balanced ordering, provider request handling, transcript/history routes, and isolation of the image coach. They use mocked providers and do not require paid API calls. If Node.js is installed, check frontend syntax with `node --check static/app.js` and `node --check static/scan/scan.js`.

## Troubleshooting

- **Unstyled page:** open the localhost URL, not an HTML file.
- **Microphone unavailable:** allow microphone access for localhost and check browser/system permissions. Transcript-only mode is available.
- **Provider not ready:** check `.env`, API credit/model access, then restart Python. A web-chat subscription is not necessarily API access.
- **Connection refused:** start `python app.py` and keep the terminal running.
- **Port occupied:** set `PORT=8766` in `.env`, restart, then use the new port.
- **Old interface after an update:** hard refresh with Command–Shift–R or Ctrl–Shift–R.

## 中文说明

这是一个免费开源、在自己电脑上运行的墨尔本风格 MMI 练习工具。软件没有订阅费或试用次数限制；DeepSeek 和 Deepgram 的 API 用量费用由你自己的账户承担。

内置 **30 个 station、120 道原创练习题、8 类主题**。先读 60 秒 Scenario，再逐题进行 15 秒准备和 60 秒回答。Scenario 读完消失，Question 在准备和回答期间持续显示。主题在后台均衡排列，选题时只显示 station 编号。

安装步骤见上方：安装 Python，下载仓库，安装 `requirements.txt`，把 `.env.example` 复制为 `.env`，填入两个 API key，运行 `python app.py`，然后打开 http://127.0.0.1:8765/ 。不要直接打开 HTML 文件。

当前完整自动流程接入的是 **DeepSeek（评价）+ Deepgram（语音转文字）**，不是任意厂商的 key 都能直接替换。没有 key 时也可以计时练习、手动填入文字并查看基础反馈。

除了英文参考答案，还会提供**以中文为主的简洁答题思路**，帮助你组织一分钟的回答。可以让 Codex 协助扩充题库，具体提示词与检查要求见[题库扩充指南](docs/ADDING_STATIONS.md)。

## License

[MIT](LICENSE). Free to use, modify, and share; the license also permits commercial reuse. This project's own distribution is free.
