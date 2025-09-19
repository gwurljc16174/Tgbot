# WebDev Tutor Bot (Render Deployment)

An interactive Telegram bot that teaches HTML, CSS, and JavaScript step by step.

## Features
- Lessons with examples and quizzes
- Premium lessons locked behind contact link (manual upgrade)
- SQLite database to track progress
- Runs with polling (no webhook needed)

## Setup

1. Copy `.env.example` → `.env` and set your bot token.

## Deploy to Render

1. Push this project to GitHub.
2. In Render dashboard, click "New +" → "Blueprint" → select your repo.
3. Render will detect `render.yaml` and auto-deploy as a Worker.
4. In Render → Environment → Add Variable:
   ```
   BOT_TOKEN=123456789:ABC-your-telegram-bot-token
   ```
5. Deploy → Bot will run in polling mode.

Enjoy your WebDev Tutor Bot 🚀
