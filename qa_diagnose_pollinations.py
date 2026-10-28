"""
Probe the correct Pollinations unauthenticated endpoint.
"""
import requests, time

PROMPT_ENCODED = (
    "A%20dramatic%20cinematic%20illustration%20of%20a%20human%20silhouette%20being%20stretched%20"
    "and%20pulled%20into%20the%20glowing%20accretion%20disk%20of%20a%20massive%20black%20hole%20"
    "in%20deep%20space%2C%20hyper-realistic%2C%208k%20resolution%2C%20vibrant%20cosmic%20colors"
)

# The public unauthenticated endpoint
URL = f"https://image.pollinations.ai/prompt/{PROMPT_ENCODED}?model=flux&width=1080&height=1920&nologo=true"
print(f"Probing: {URL}\n")
t0 = time.time()
resp = requests.get(URL, allow_redirects=True, timeout=60)
elapsed = time.time() - t0

print(f"Final status code : {resp.status_code}")
print(f"Elapsed           : {elapsed:.2f}s")
print(f"Final URL         : {resp.url}")
print(f"Redirect chain    : {[r.url for r in resp.history]}")
print(f"Content-Type      : {resp.headers.get('Content-Type','MISSING')}")
print(f"Content-Length hdr: {resp.headers.get('Content-Length','not set')}")
print(f"Actual byte size  : {len(resp.content):,} bytes")
print(f"First 4 bytes     : {resp.content[:4]}  (b'\\x89PNG' or b'\\xff\\xd8' = valid image)")
print(f"Is image?         : {resp.headers.get('Content-Type','').startswith('image/')}")
