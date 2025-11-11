## 🗞️ News To Text Video Builder

A Python-based tool that converts any news article into a narrated video.This project automatically extracts text from URLs, summarizes key points, generates natural-sounding speech using TTS, and builds clean MP4 news-style videos using MoviePy and Pillow — all without ImageMagick.Perfect for automated news content, social media updates, and AI-driven media workflows.

## 🚀 Features

- 🌐 Fetches article text from any URL

- 🧠 Generates headline, bullet points, summary, and takeaway

- 🗣️ Text-to-Speech using Google Cloud TTS or gTTS

- 🎬 Video rendering via MoviePy + Pillow

- 📝 Clean banner, slides, subtitles

- 🎞️ Two video modes:
    - 📌 Points Mode (slide per bullet point)
    - 🎚️ Scrolling Mode (scrolling text + subtitles)



## 📂 Project Structure
```
News-To-Text-Video-Builder/
├── README.md
├── requirements.txt
├── .gitignore
└── src/
    └── main.py
```

## 🔧 Requirements
- 🐍 Python 3.9 or above

- 🎬 MoviePy

- 🖼️ Pillow

- 🌐 Requests

- 🍜 BeautifulSoup4

- 🔊 gTTS (fallback TTS engine)

- 🎤 Google Cloud Text-to-Speech (optional, high-quality voices)

## 📦 Installation Guide

### 1️⃣ Clone the repository
```git clone https://github.com/yourusername/News-To-Text-Video-Builder.git```
```cd News-To-Text-Video-Builder```
### 2️⃣ Install dependencies
```pip install -r requirements.txt```
3️⃣ (Optional) Enable Google Cloud TTS
Set your Google service account JSON:
```export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"```

## ▶️ Usage
Run the script:
```python -m src.main```
You will be prompted to enter a news/article URL.

### The tool will:

- 📥 Fetch the article

- ✂️ Extract main content

- 🧠 Summarize

- 🗣️ Generate narration

- 🖼️ Render slides

- 🎬 Produce MP4 + MP3

## 🧠 How It Works

- 🌐 You provide a news/article URL through the script or Colab input

- 📝 Content Extractor fetches and cleans the article text

- 🧩 Summarizer Engine generates the headline, bullet points, summary, and takeaway

- 🎤 TTS Generator (Google TTS or gTTS) converts the script into an MP3 narration

- 🖼️ Video Builder renders slides or scrolling text using Pillow and MoviePy

- 🎬 Final Composer merges audio + visuals into a polished MP4 video

- 📁 Output includes both MP3 narration and MP4 video, stored in the project folder

The entire workflow runs automatically in sequence — no ImageMagick required.

## 💡 Use Cases

- 📰 Automated news video generation for channels or websites

- 🔍 Quick breakdowns of long articles into short video summaries

- 🎞️ YouTube Shorts, Reels, and TikTok content creation

- 🤖 AI-driven media automation pipelines

- 📚 Educational tool for learning TTS, NLP, and video rendering

-🚀 Daily news digest automation for creators and analysts

## 📜 License
This project is licensed under the MIT License.
