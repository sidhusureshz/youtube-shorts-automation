# Agentic AI-Driven YouTube Shorts Automation

A multi-agent pipeline that turns a channel niche into a published YouTube Short. Type a niche in the dashboard, and the system picks a topic, writes a script, records the voiceover, generates an image, renders the video and uploads it to YouTube. No manual editing between steps.

Final-year MCA project, KMCT College of Engineering.

**Pages:** [Home](https://sidhusureshz.github.io/youtube-shorts-automation/) · [Privacy Policy](https://sidhusureshz.github.io/youtube-shorts-automation/privacy.html) · [Terms of Service](https://sidhusureshz.github.io/youtube-shorts-automation/terms.html)

## How it works

```
Niche
  -> TopicAgent    (Gemini)         picks one video topic
  -> ScriptAgent   (Gemini)         narration, title, description, tags, image prompt
  -> TTSAgent      (UnrealSpeech)   narration -> mp3
  -> ImageAgent    (Pollinations)   image prompt -> 1080x1920 image
  -> RenderAgent   (Shotstack)      audio + image -> mp4, polled until done
  -> PublishAgent  (YouTube API)    resumable upload via OAuth 2.0
  -> EmailAgent    (Gmail SMTP)     optional report
```

Each agent has one job and logs `START` / `COMPLETE` in the server terminal. A failure names the stage, for example `FAILED at ImageAgent`.

The dashboard (`dashboard.html`) sends a POST request with the niche to the FastAPI endpoint `/webhook/youtube-automation-run`. The backend runs the pipeline and returns the result as JSON. The `webhook` name is inherited from the earlier n8n prototype of this workflow.

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Python, FastAPI, uvicorn |
| Frontend | HTML, CSS, JavaScript (`dashboard.html`) |
| Text generation | Google Gemini (with model fallback on 429/503) |
| Voice | UnrealSpeech |
| Images | Pollinations (flux) |
| Video render | Shotstack |
| Publishing | YouTube Data API v3, OAuth 2.0 |
| Storage | SQLite |
| Tests | pytest |

## Project structure

```
main.py                  FastAPI app and run_pipeline
dashboard.html           Dashboard UI
agents/                  Agent modules (email agent)
tests/                   Endpoint and email stage tests
youtube_auth.py          One-time OAuth flow, produces a refresh token
youtube_upload.py        Standalone upload script for testing
requirements.txt         Python dependencies
.env.example             Template for API keys
```

## Setup

**1. Install**

```bash
git clone https://github.com/sidhusureshz/youtube-shorts-automation.git
cd youtube-shorts-automation
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

**2. Configure keys**

Copy `.env.example` to `.env` and fill in your values. Never commit `.env`.

```
GEMINI_API_KEY=
UNREALSPEECH_API_KEY=
POLLINATIONS_API_KEY=
SHOTSTACK_API_KEY=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
GMAIL_ADDRESS=
GMAIL_APP_PASSWORD=
```

**3. YouTube credentials**

1. In Google Cloud Console, create a project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen and set it to **In production**. A token made in Testing mode expires after 7 days.
3. Create an OAuth client of type **Desktop app**. Download the JSON as `client_secret.json`.
4. Run `python youtube_auth.py`, sign in, and allow access. Put the printed values in `.env`.

**4. Run**

```bash
python -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8000` to check the health response, and `http://127.0.0.1:8000/docs` for the API docs. Then open `dashboard.html` in a browser, enter a niche and click **Launch Autonomous Run**. A full run takes several minutes.

## Known limitations

- **Uploads are Private.** YouTube locks videos from unaudited API projects to Private. Switch each video to Public in YouTube Studio, or pass the YouTube API compliance audit.
- **Quota.** The YouTube API allows about 6 uploads per day on the default quota.
- **Free tier limits.** Pollinations allows 1 image per 45 seconds per IP, so the image stage waits and retries.
- **Email stage.** Built, but Gmail SMTP delivery is still being debugged.
- **Single user.** SQLite and blocking HTTP calls suit one run at a time.

## Roadmap

- Paid image provider for stable generation
- Retry audit panel for failed stages
- Scheduled runs
- Analytics feedback into topic selection
- YouTube API audit for public auto-publish

## Security

API keys live in `.env`, which is git-ignored. If a key is ever shown in a log, screenshot or commit, rotate it.

## Author

Sidhu, MCA (Data Science), KMCT College of Engineering.
