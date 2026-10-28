import re

src = open('main.py', encoding='utf-8').read()
log = open('logs/pipeline.log', encoding='utf-8', errors='replace').read()

# TC14
img_hosted = list(dict.fromkeys(re.findall(r'\[ImageAgent\] Hosted image URL: (.+)', log)))
runs = list(dict.fromkeys(re.findall(r'STARTING PIPELINE RUN ID=(.+)', log)))
print(f'TC14: hosted image URLs in all logs: {len(img_hosted)}')
print(f'TC14: pipeline runs started: {len(runs)}')
print('TC14: (one image per run, not per scene)')

saved_paths = list(dict.fromkeys(re.findall(r'saved to (.+)', log)))
print(f'TC14: temp image files logged: {saved_paths[:3]}')

# TC16
html = open('index.html', encoding='utf-8', errors='replace').read()
has_vid = 'video' in html.lower()
print()
print(f'TC16: index.html contains video element/reference: {has_vid}')
vid_tag = re.search(r'(?i)<video|videoUrl|video_url|video\.src', html)
print(f'TC16: video display code found: {bool(vid_tag)}')

# TC19
print()
print('TC19: Payload script fields present:')
for f in ['narration', 'title', 'description', 'tags']:
    print(f'  {f!r}: {f in src}')

# TC22: EmailAgent YouTube link
ea = open('agents/email_agent.py', encoding='utf-8').read()
has_yt = 'watch_url' in ea and 'youtube.com' in ea
print()
print(f'TC22: success email contains watch_url / youtube.com link: {has_yt}')
idx = ea.find('watch_url')
ctx = ea[idx:idx+120] if idx >= 0 else 'NOT FOUND'
print('  context: ' + ctx.replace('\n', ' '))

# TC20: retry or escalation after YouTube failure
pub_start = src.find('PublishAgent (YouTube) - START')
pub_end = src.find('PublishAgent (YouTube) - COMPLETE')
pub_code = src[pub_start:pub_end] if pub_start > 0 else ''
print()
print(f'TC20: retry keyword in PublishAgent block: {"retry" in pub_code.lower()}')
print(f'TC20: except keyword in PublishAgent block: {"except" in pub_code}')
outer = src[src.find('except Exception as exc'):]
print('TC20: outer except block snippet:')
print(outer[:220].replace('\n', ' | '))
