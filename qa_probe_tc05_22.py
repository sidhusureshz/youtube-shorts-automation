import re

src = open('main.py', encoding='utf-8').read()
log = open('logs/pipeline.log', encoding='utf-8', errors='replace').read()

# TC05: Narrations in log
narrations = list(dict.fromkeys(re.findall(r'Generated Narration: (.+)', log)))
titles     = list(dict.fromkeys(re.findall(r'Generated Title: (.+)', log)))
print('=== TC05: Narrations logged (unique, first 6) ===')
for i, n in enumerate(narrations[:6], 1):
    wc = len(n.split())
    cc = len(n)
    print(f'  Run {i}: {cc} chars / {wc} words - {n[:70]}')

print()
print('=== TC06: version/word-count/approval fields in payload? ===')
for kw in ['version', 'wordCount', 'word_count', 'readability', 'approved']:
    print(f'  {kw!r} in main.py: {kw in src}')

print()
print('=== TC07: re-generation loop present? ===')
for kw in ['regenerat', 'len(narration)', 'script.*retry', 'retry.*script']:
    hits = len(re.findall(kw, src, re.IGNORECASE))
    print(f'  pattern {kw!r}: {hits} hit(s)')

print()
print('=== TC08: configurable retry limit? ===')
for kw in ['retry_limit', 'max_retry', 'retryLimit', 'maxRetry']:
    print(f'  {kw!r}: {kw.lower() in src.lower()}')

print()
print('=== TC10/TC11: duration / tolerance checks? ===')
for kw in ['TimestampsUri', 'duration', 'tolerance', 'pacing', 'adjust']:
    hits = len(re.findall(kw, src, re.IGNORECASE))
    print(f'  {kw!r}: {hits} hit(s) in main.py')

print()
print('=== TC12: premium voice provider? ===')
for kw in ['elevenlabs', 'eleven_labs', 'playht', 'polly', 'azure.*speech']:
    hits = len(re.findall(kw, src, re.IGNORECASE))
    print(f'  {kw!r}: {hits} hit(s)')

print()
print('=== TC13: scene decomposition? ===')
for kw in ['scene', 'scene_prompt', 'per.scene', 'image_prompt.*list']:
    hits = len(re.findall(kw, src, re.IGNORECASE))
    print(f'  {kw!r}: {hits} hit(s)')

print()
print('=== TC15: image retry with adjusted prompt? ===')
for kw in ['adjusted', 'alternate.*prompt', 'fallback.*prompt']:
    hits = len(re.findall(kw, src, re.IGNORECASE))
    print(f'  {kw!r}: {hits} hit(s)')

print()
print('=== TC17: captions? ===')
for kw in ['caption', 'subtitle', 'burned', 'SRT', 'VTT']:
    hits = len(re.findall(kw, src, re.IGNORECASE))
    print(f'  {kw!r}: {hits} hit(s)')

print()
print('=== TC20: YouTube error / retry / escalation? ===')
for kw in ['RefreshError', 'invalid_grant', 'credential.*retry', 'reauth', 'escalat']:
    hits = len(re.findall(kw, src, re.IGNORECASE))
    print(f'  {kw!r}: {hits} hit(s) in main.py')

# TTS
tts_urls  = list(dict.fromkeys(re.findall(r'TTS Audio URL: (.+)', log)))
tts_codes = list(dict.fromkeys(re.findall(r'TTSAgent Raw Response Code: (\d+)', log)))
print()
print('=== TC09: TTS HTTP codes ===')
print(f'  codes: {tts_codes}')
print(f'  URLs (first 3): {tts_urls[:3]}')

# TC14
img_hosted = list(dict.fromkeys(re.findall(r'\[ImageAgent\] Hosted image URL: (.+)', log)))
print()
print(f'=== TC14: Hosted images found: {len(img_hosted)} ===')
if img_hosted:
    print(f'  First: {img_hosted[0]}')

# TC16
done_urls = list(dict.fromkeys(re.findall(r'"url":"(https://shotstack[^"]+\.mp4)"', log)))
print()
print(f'=== TC16: Shotstack done MP4 URLs: {len(done_urls)} ===')
for u in done_urls[:3]:
    print(f'  {u}')

# TC18
yt_ids = list(dict.fromkeys(re.findall(r'YouTube Upload Success! Video ID=(.+)', log)))
print()
print(f'=== TC18: YouTube Video IDs: {len(yt_ids)} ===')
for v in yt_ids:
    print(f'  https://youtu.be/{v}')

# TC20
ig = list(dict.fromkeys(re.findall(r'invalid_grant[^\n]*', log)))
print()
print(f'=== TC20: invalid_grant in logs: {len(ig)} ===')
for g in ig[:2]:
    print(f'  {g}')

# TC21/TC22
smtp_err = re.findall(r'STEP 7 SMTP ERROR[^\n]*', log)
step8_lines = re.findall(r'STEP 8[^\n]*', log)
print()
print(f'=== TC21: Step7 SMTP errors: {len(smtp_err)} ===')
if smtp_err:
    print(f'  {smtp_err[0]}')
print(f'  Step8 notify lines: {len(step8_lines)}')
for ln in step8_lines[:4]:
    print(f'  {ln}')
