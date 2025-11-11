# === Full: No-ImageMagick video builder (Pillow-only subtitles) with points-mode ===
import re
import math
import textwrap
import os
import uuid
import tempfile
from typing import List, Tuple
import requests
from bs4 import BeautifulSoup
from IPython.display import Audio, display, HTML, Video

# Optional readability
try:
    from readability import Document
    _HAS_READABILITY = True
except Exception:
    _HAS_READABILITY = False

# Google TTS availability
_HAS_GOOGLE_TTS = False
try:
    from google.cloud import texttospeech
    _HAS_GOOGLE_TTS = True
except Exception:
    _HAS_GOOGLE_TTS = False

# gTTS fallback
try:
    from gtts import gTTS
except Exception:
    gTTS = None

# moviepy + PIL
from moviepy.editor import AudioFileClip, ImageClip, VideoFileClip, CompositeVideoClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont

# -------------------- Fetch & text helpers --------------------
def fetch_url_text(url: str, timeout: int = 12) -> Tuple[str, str]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsSummarizer/1.0)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    if _HAS_READABILITY:
        try:
            doc = Document(html)
            title = doc.short_title() or (soup.title.string if soup.title else "")
            content_html = doc.summary()
            soup_c = BeautifulSoup(content_html, "html.parser")
            text = soup_c.get_text(separator="\\n").strip()
            if len(text) > 100:
                return title.strip(), text
        except Exception:
            pass
    article_tag = soup.find("article") or soup.find("main")
    if article_tag:
        text = article_tag.get_text(separator="\\n").strip()
        title = soup.title.string.strip() if soup.title else ""
        return title, text
    paragraphs = [p.get_text().strip() for p in soup.find_all("p") if p.get_text().strip()]
    if paragraphs:
        return (soup.title.string.strip() if soup.title else ""), "\\n\\n".join(paragraphs)
    return (soup.title.string.strip() if soup.title else "Untitled"), soup.get_text(separator="\\n").strip()

def estimate_read_time(text: str, wpm: int = 220) -> int:
    words = len(re.findall(r"\\w+", text))
    return max(1, math.ceil(words / wpm))

def chunk_text(text: str, max_chars: int = 3000) -> List[str]:
    paragraphs = [p.strip() for p in text.split("\\n\\n") if p.strip()]
    chunks, current, cur_len = [], [], 0
    for p in paragraphs:
        if cur_len + len(p) <= max_chars:
            current.append(p); cur_len += len(p)
        else:
            chunks.append("\\n\\n".join(current))
            current, cur_len = [p], len(p)
    if current: chunks.append("\\n\\n".join(current))
    return chunks if chunks else [text[:max_chars]]

def _clean_text_simple(t: str) -> str:
    if not t: return ""
    t = re.sub(r'\\n+', '\\n', t)
    t = re.sub(r'\\s+', ' ', t)
    t = re.sub(r'\\b(By|by)\\s+[A-Z][\\w\\s,.-]{1,40}', '', t)
    t = re.sub(r'\\b(BBC News|Reuters|AFP|Associated Press|The Guardian)\\b', '', t, flags=re.I)
    return t.strip()

def _split_sentences(text: str):
    return [s.strip() for s in re.split(r'(?<=[.!?])\\s+', text.strip()) if s.strip()]

def call_llm_summary_clean(title: str, chunks: List[str]) -> dict:
    # Simple deterministic summarizer used previously
    text_all = "\\n\\n".join(chunks)
    text_all = _clean_text_simple(text_all)
    sentences = _split_sentences(text_all)
    headline = title.strip() if title else (sentences[0][:80] + "...") if sentences else "Untitled"
    bullets = sentences[:4]  # take first 4 sentences as points
    summary = " ".join(sentences[:6]) if sentences else ""
    takeaway = sentences[0] if sentences else ""
    return {"headline": headline, "bullets": bullets, "summary": summary, "takeaway": takeaway}

def build_news_reader_script(headline: str, bullets: list, summary: str, takeaway: str,
                             anchor_name: str = "Anchor", lead_in: str = "Here is the latest") -> str:
    def clean(s): return re.sub(r'\\s+', ' ', (s or "").strip())
    h = clean(headline); bullets = [clean(b) for b in (bullets or [])]; summary = clean(summary); takeaway = clean(takeaway)
    lines = []
    lines.append(f"{anchor_name}: {lead_in}. {h}.")
    lines.append("<break time='400ms'/>")
    if bullets:
        lines.append(f"{anchor_name}: In brief — {bullets[0]}.")
        lines.append("<break time='350ms'/>")
    if bullets:
        lines.append(f"{anchor_name}: Key facts follow.")
        for b in bullets:
            lines.append(f"{anchor_name}: {b}.")
            lines.append("<break time='250ms'/>")
    if summary:
        lines.append(f"{anchor_name}: Details.")
        for s in re.split(r'(?<=[.!?])\\s+', summary):
            if s.strip():
                lines.append(f"{anchor_name}: {s.strip()}")
                lines.append("<break time='200ms'/>")
    if takeaway:
        lines.append(f"{anchor_name}: Bottom line — {takeaway}.")
        lines.append("<break time='300ms'/>")
    lines.append(f"{anchor_name}: That's the latest. Stay tuned.")
    return "\\n".join(lines)

# -------------------- Script cleaning / TTS helpers --------------------
def _strip_role_labels(script: str) -> str:
    out_lines = []
    for line in script.splitlines():
        cleaned = re.sub(r'^\\s*[A-Za-z][A-Za-z0-9 _-]{0,24}[:\\-]\\s*', '', line)
        out_lines.append(cleaned)
    return "\\n".join(out_lines)

def script_to_plaintext_for_gtts(script: str) -> str:
    script_no_roles = _strip_role_labels(script)
    txt = re.sub(r"<break\\s+time='(\\d+)ms'\\s*/>", ". ", script_no_roles)
    txt = re.sub(r'<[^>]+>', '', txt)
    return re.sub(r'\\s+', ' ', txt).strip()

def tts_with_gtts(script: str, out_path: str, lang='en', tld='com'):
    if gTTS is None:
        raise RuntimeError("gTTS not installed. Run `pip install gTTS` first.")
    text = script_to_plaintext_for_gtts(script)
    tts = gTTS(text=text, lang=lang, tld=tld)
    tts.save(out_path)
    return out_path

def script_to_ssml(script: str, voice_speed: float = 1.0) -> str:
    script_no_roles = _strip_role_labels(script)
    parts = []
    for line in script_no_roles.splitlines():
        line = line.strip()
        if not line: continue
        escaped = line.replace("&", "and")
        parts.append(f"<p><s><prosody rate='{int(voice_speed*100)}%'>{escaped}</prosody></s></p>")
    return f"<speak>{'\\n'.join(parts)}</speak>"

def tts_with_google_ssml(ssml: str, out_path: str, voice_name: str = "en-GB-Wavenet-A",
                         speaking_rate: float = 0.98, pitch: float = 0.0):
    if not _HAS_GOOGLE_TTS:
        raise RuntimeError("google-cloud-texttospeech not available in this runtime.")
    client = texttospeech.TextToSpeechClient()
    input_ssml = texttospeech.SynthesisInput(ssml=ssml)
    lang_code = "-".join(voice_name.split("-")[:2])
    voice = texttospeech.VoiceSelectionParams(name=voice_name, language_code=lang_code)
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3,
                                            speaking_rate=speaking_rate, pitch=pitch)
    response = client.synthesize_speech(input=input_ssml, voice=voice, audio_config=audio_config)
    with open(out_path, "wb") as out:
        out.write(response.audio_content)
    return out_path

# -------------------- Fonts & text metrics --------------------
def _load_font(size=36):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _text_size(draw, text, font):
    if hasattr(draw, "textbbox"):
        box = draw.textbbox((0,0), text, font=font)
        return box[2]-box[0], box[3]-box[1]
    return draw.textsize(text, font=font)

# -------------------- Subtitle / point image helpers --------------------
def _make_subtitle_image(text, width, font, padding=20, bg=(0,0,0,160), text_color="white"):
    img_tmp = Image.new("RGBA", (width, 2000), (0,0,0,0))
    d = ImageDraw.Draw(img_tmp)
    words = text.split()
    lines = []
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        w_test, _ = _text_size(d, test, font)
        if w_test <= width - 2*padding:
            line = test
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    _, h0 = _text_size(d, "Ay", font)
    h = (h0 + 6) * len(lines) + 2*padding
    im = Image.new("RGBA", (width, h), bg)
    draw = ImageDraw.Draw(im)
    y = padding
    for ln in lines:
        w_ln, _ = _text_size(draw, ln, font)
        draw.text(((width-w_ln)//2, y), ln, font=font, fill=text_color)
        y += h0 + 6
    return im

def _make_point_image(text, size, font, padding=60, bg=(10,10,40), text_color="white", headline=None, headline_font=None):
    W, H = size
    im = Image.new("RGB", (W, H), color=bg)
    draw = ImageDraw.Draw(im)

    # headline at top (optional)
    y = padding // 2
    if headline and headline_font:
        headline_lines = textwrap.wrap(headline, width=30)
        for hl in headline_lines:
            w_h, h_h = _text_size(draw, hl, headline_font)
            draw.text(((W-w_h)//2, y), hl, font=headline_font, fill="#FFD700")
            y += h_h + 8
        y += 8

    # main text centered block
    main_font = font
    wrap_width = 40
    lines = textwrap.wrap(text, width=wrap_width)
    h_line = _text_size(draw, "Ay", main_font)[1] + 6
    block_h = len(lines) * h_line
    start_y = max(y + 20, (H - block_h)//2)
    for ln in lines:
        w_ln, h_ln = _text_size(draw, ln, main_font)
        draw.text(((W-w_ln)//2, start_y), ln, font=main_font, fill=text_color)
        start_y += h_line
    return im

# -------------------- Safe remove & dedupe --------------------
def _safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def _dedupe_keep_order(items):
    seen = set()
    out = []
    for it in items:
        key = it.strip()
        if not key:
            continue
        if key.lower() in seen:
            continue
        seen.add(key.lower())
        out.append(it)
    return out

# -------------------- Video generator (points_mode & alignment) --------------------
def create_ai_news_video_no_imagemagick(audio_path, headline, script_text, output_path="/mnt/data/ai_news_video.mp4",
                         resolution=(1280,720), bg_color=(10,10,40), text_color="white",
                         headline_color="#FFD700", font_size=36, headline_font_size=50,
                         add_subtitles=True, background_video=None, points_mode=False, points=None, takeaway=None,
                         tts_plaintext: str = None):
    \"\"\"
    tts_plaintext: the exact plain text used to generate the audio (gTTS/plaintext or SSML-stripped).
    If points_mode=True, 'points' should be a list of strings (bullet points).
    \"\"\"
    if not os.path.exists(audio_path):
        raise FileNotFoundError("Audio not found: " + audio_path)
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration
    W, H = resolution

    font = _load_font(size=font_size)
    headline_font = _load_font(size=headline_font_size)

    tmpdir = tempfile.gettempdir()
    created_files = []

    # Background clip
    bg = None
    if background_video and os.path.exists(background_video):
        try:
            bg_video = VideoFileClip(background_video)
            bg = bg_video.subclip(0, min(duration, bg_video.duration))
            if bg.duration < duration:
                repeats = int(math.ceil(duration / bg.duration))
                bg = concatenate_videoclips([bg] * repeats).subclip(0, duration)
            bg = bg.resize(newsize=resolution)
        except Exception:
            bg = None

    if bg is None:
        bg_img = Image.new("RGB", resolution, color=bg_color)
        bg_img_path = os.path.join(tmpdir, f"bg_{uuid.uuid4().hex[:8]}.png")
        bg_img.save(bg_img_path)
        created_files.append(bg_img_path)
        bg = ImageClip(bg_img_path).set_duration(duration)

    # Banner
    banner_h = 120
    banner_img = Image.new("RGBA", (W, banner_h), (0,0,0,180))
    d = ImageDraw.Draw(banner_img)
    banner_text = (headline or "").strip()
    try:
        d.text((30, 30), "🗞️ " + banner_text, font=headline_font, fill=headline_color)
    except Exception:
        d.text((30, 30), banner_text or "News", font=headline_font, fill=headline_color)
    banner_path = os.path.join(tmpdir, f"banner_{uuid.uuid4().hex[:8]}.png")
    banner_img.save(banner_path)
    created_files.append(banner_path)
    banner_clip = ImageClip(banner_path).set_duration(duration).set_position(("center","top"))

    clips = [bg]

    # Points mode - one slide per point (timing aligned to TTS plaintext when possible)
    if points_mode:
        pts = points or []
        pts = _dedupe_keep_order(pts)

        all_texts = []
        if headline:
            all_texts.append(("Headline", headline))
        for p in pts:
            all_texts.append(("Point", p))
        if takeaway:
            all_texts.append(("Takeaway", takeaway))
        if not all_texts:
            all_texts = [("Headline", headline or "Summary")]

        # word counts calculation (prefer tts_plaintext info)
        if tts_plaintext:
            # fallback: use word counts from slide text (keeps simple and deterministic)
            word_counts = [max(1, len(re.findall(r"\\w+", t[1]))) for t in all_texts]
            total_words = sum(word_counts) or 1
        else:
            word_counts = [max(1, len(re.findall(r"\\w+", t[1]))) for t in all_texts]
            total_words = sum(word_counts) or 1

        # allocate durations proportional to word counts, with a minimum per slide
        min_slide = 0.9
        slide_durations = [max(min_slide, duration * (wc / total_words)) for wc in word_counts]

        # scale durations so they sum exactly to duration
        ssum = sum(slide_durations)
        if ssum > 0:
            scale = duration / ssum
            slide_durations = [max(min_slide, d * scale) for d in slide_durations]

        slides = []
        for (role, text), dur in zip(all_texts, slide_durations):
            if role == "Headline":
                img = _make_point_image(text, (W, H), _load_font(int(font_size*1.1)), padding=40, bg=bg_color,
                                        text_color=text_color, headline=None, headline_font=headline_font)
            elif role == "Takeaway":
                img = _make_point_image(text, (W, H), _load_font(int(font_size*0.95)), padding=40, bg=bg_color,
                                        text_color=text_color, headline="Bottom line", headline_font=headline_font)
            else:
                img = _make_point_image(text, (W, H), _load_font(int(font_size*0.95)), padding=40, bg=bg_color,
                                        text_color=text_color, headline=None, headline_font=headline_font)
            img_path = os.path.join(tmpdir, f"slide_{uuid.uuid4().hex[:8]}.png")
            img.save(img_path)
            created_files.append(img_path)
            slide_clip = ImageClip(img_path).set_duration(dur).set_position(("center","center")).set_fps(24)
            slides.append(slide_clip)

        if slides:
            sequence_clip = concatenate_videoclips(slides, method="compose")
            seq_dur = sequence_clip.duration
            # trim or pad last slide to match duration exactly
            if seq_dur < duration:
                extra = duration - seq_dur
                last = slides[-1]
                slides[-1] = last.set_duration(last.duration + extra)
                sequence_clip = concatenate_videoclips(slides, method="compose")
            elif seq_dur > duration:
                sequence_clip = sequence_clip.subclip(0, duration)
            clips.append(sequence_clip.set_position(("center","center")))
            clips.append(banner_clip)
    else:
        # Original scrolling + subtitles behavior
        margin = 40
        scroll_w = W - 2*margin
        tmp_img = Image.new("RGB", (W, H))
        draw_tmp = ImageDraw.Draw(tmp_img)
        words = script_text.split()
        lines = []
        line = ""
        for w in words:
            test = (line + " " + w).strip()
            w_test, _ = _text_size(draw_tmp, test, font)
            if w_test <= scroll_w - 20:
                line = test
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)
        _, line_h = _text_size(draw_tmp, "Ay", font)
        line_h += 8
        total_h = line_h * max(1, len(lines)) + 2*margin
        total_h = max(total_h, H)
        big_img = Image.new("RGB", (scroll_w, int(total_h)), color=bg_color)
        draw = ImageDraw.Draw(big_img)
        y = margin
        for ln in lines:
            draw.text((10, y), ln, font=font, fill=text_color)
            y += line_h
        big_img_path = os.path.join(tmpdir, f"scroll_{uuid.uuid4().hex[:8]}.png")
        big_img.save(big_img_path)
        created_files.append(big_img_path)
        big_clip = ImageClip(big_img_path).set_duration(duration).set_fps(24)
        # scrolling movement
        scroll_start_y = banner_h + 20
        scroll_distance = max(0, big_clip.h - (H - banner_h - 40))
        def y_pos(t):
            return int(- scroll_distance * (t / max(1e-6, duration))) + scroll_start_y
        scrolling_clip = big_clip.set_pos(lambda t: ((W - scroll_w)//2, y_pos(t)))
        clips.append(scrolling_clip)
        clips.append(banner_clip)

        # subtitles
        if add_subtitles:
            subtitle_clips = []
            sents = [s.strip() for s in re.split(r'(?<=[.!?])\\s+', script_text) if s.strip()]
            words_per_sent = [len(s.split()) for s in sents]
            total_words = sum(words_per_sent) or 1
            cur = 0.0
            for i, s in enumerate(sents):
                dur = max(0.6, duration * (words_per_sent[i] / total_words))
                start = cur
                end = min(duration, cur + dur)
                cur = end
                sub_img = _make_subtitle_image(s, width=W-120, font=_load_font(int(font_size*0.9)))
                sub_path = os.path.join(tmpdir, f"sub_{uuid.uuid4().hex[:8]}.png")
                sub_img.save(sub_path)
                created_files.append(sub_path)
                img_clip = ImageClip(sub_path).set_start(start).set_duration(end-start).set_position(("center", H-120))
                subtitle_clips.append(img_clip)
            clips.extend(subtitle_clips)

    final = CompositeVideoClip(clips, size=resolution).set_duration(duration)
    final = final.set_audio(audio_clip)

    out_path = output_path
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    final.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", threads=2, preset="medium")

    for f in created_files:
        _safe_remove(f)

    return out_path

# -------------------- Runner (builds TTS plaintext & calls create) --------------------
def run_full_pipeline_and_make_video(
        url: str,
        tts_backend: str = "auto",
        voice_name: str = "en-GB-Wavenet-A",
        speaking_rate: float = 0.96,
        pitch: float = -0.2,
        audio_lang: str = "en",
        anchor_name: str = "Anchor",
        make_video: bool = True,
        points_mode: bool = True
    ):
    print("Fetching article and summarizing...")
    title, text = fetch_url_text(url)
    chunks = chunk_text(text)
    read_time = estimate_read_time(text)
    result = call_llm_summary_clean(title, chunks)

    headline = result["headline"]
    bullets = result["bullets"]
    bullets = _dedupe_keep_order(bullets)
    summary = result["summary"]
    takeaway = result["takeaway"]

    script = build_news_reader_script(headline, bullets, summary, takeaway, anchor_name=anchor_name)
    print("\\n=== Broadcast Script ===\\n")
    print(script)
    print("\\n=======================\\n")

    backend = tts_backend
    if tts_backend == "auto":
        if _HAS_GOOGLE_TTS and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            backend = "google"
        else:
            backend = "gtts"

    out_dir = "/mnt/data"
    os.makedirs(out_dir, exist_ok=True)
    audio_path = os.path.join(out_dir, f"news_{uuid.uuid4().hex[:8]}.mp3")

    try:
        if backend == "google":
            ssml = script_to_ssml(script, voice_speed=speaking_rate)
            tts_with_google_ssml(ssml, audio_path, voice_name=voice_name, speaking_rate=speaking_rate, pitch=pitch)
            # build plaintext that matches the audio (SSML-stripped)
            tts_plaintext = _strip_role_labels(script)
            tts_plaintext = re.sub(r"<[^>]+>", " ", tts_plaintext)
            tts_plaintext = re.sub(r'\\s+', ' ', tts_plaintext).strip()
            print("Google TTS produced audio:", audio_path)
        else:
            # gTTS uses script_to_plaintext_for_gtts internally; replicate it here
            tts_plaintext = script_to_plaintext_for_gtts(script)
            tts_with_gtts(script, audio_path, lang=audio_lang)
            print("gTTS produced audio:", audio_path)
        try:
            from IPython.display import Audio, HTML, display, Video
            display(Audio(audio_path, autoplay=False))
            display(HTML(f'<p><a href="files/{audio_path}" download>Download MP3</a></p>'))
        except Exception:
            pass
    except Exception as e:
        print("TTS failed:", e)
        return None

    video_path = None
    if make_video:
        print("Rendering video from audio and script... (this may take a few minutes)")
        video_path = os.path.join(out_dir, f"news_video_{uuid.uuid4().hex[:8]}.mp4")

        # Clean script for on-screen text (remove Anchor: and SSML tags)
        script_clean = _strip_role_labels(script)
        script_clean = re.sub(r"<break\\s+time='(\\d+)ms'\\s*/>", " ", script_clean)
        script_clean = re.sub(r"<[^>]+>", "", script_clean)
        script_clean = re.sub(r'\\s+', ' ', script_clean).strip()

        try:
            video_path = create_ai_news_video_no_imagemagick(
                audio_path,
                headline,
                script_clean,
                output_path=video_path,
                points_mode=points_mode,
                points=bullets,
                takeaway=takeaway,
                tts_plaintext=tts_plaintext
            )
            try:
                from IPython.display import Video, HTML, display
                display(Video(video_path, embed=True, width=800))
                display(HTML(f'<p><a href="files/{video_path}" download>Download MP4</a></p>'))
            except Exception:
                pass
            print("Video saved to:", video_path)
        except Exception as e:
            print("Video creation failed:", e)

    return {
        "headline": headline, "bullets": bullets,
        "summary": summary, "takeaway": takeaway,
        "script": script, "audio_path": audio_path,
        "video_path": video_path, "tts_backend_used": backend, "read_time_min": read_time
    }

# -------------------- CLI entry --------------------
if __name__ == "__main__":
    print("Ready — paste a news/article URL and this will summarize, speak and make a video (no ImageMagick).")
    url = input("Article URL: ").strip()
    if url:
        meta = run_full_pipeline_and_make_video(url, tts_backend="auto", anchor_name="Anchor", make_video=True, points_mode=True)
        print("\\nMetadata:", meta)
    else:
        print("No URL provided. Exiting.")
