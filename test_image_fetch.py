import time
import requests

URL = (
    "https://image.pollinations.ai/prompt/"
    "A%20dramatic%20cinematic%20view%20of%20a%20human%20silhouette%20falling%20toward%20a%20glowing%2C%20swirling%20black%20hole"
    "?model=flux&width=1080&height=1920&nologo=true"
)

def is_valid_image(content: bytes) -> tuple[bool, str]:
    if content.startswith(b"\xff\xd8"):
        return True, "JPEG (starts with FF D8)"
    if content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\x89PNG"):
        return True, "PNG (starts with 89 50 4E 47)"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return True, "GIF"
    if content.startswith(b"RIFF") and len(content) > 12 and content[8:12] == b"WEBP":
        return True, "WEBP"
    return False, "Not recognized image binary"

def inspect_request(run_label: str):
    print(f"=== {run_label} ===")
    start_time = time.time()
    try:
        resp = requests.get(URL, allow_redirects=True, timeout=90)
        elapsed = time.time() - start_time
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"Request failed with exception after {elapsed:.2f}s: {e}")
        return None, elapsed

    print(f"Elapsed Time: {elapsed:.2f}s")
    print(f"Final Status Code: {resp.status_code}")
    print(f"Final URL: {resp.url}")

    # Redirect hops
    if resp.history:
        print(f"Redirect hops ({len(resp.history)}):")
        for i, hop in enumerate(resp.history, 1):
            loc = hop.headers.get("Location", "<No Location Header>")
            print(f"  Hop {i}: Status {hop.status_code} -> Location: {loc}")
    else:
        print("Redirect hops: None (Direct response)")

    # Headers
    content_type = resp.headers.get("Content-Type", "<None>")
    content_length = resp.headers.get("Content-Length", "<None>")
    print(f"Content-Type: {content_type}")
    print(f"Content-Length Header: {content_length}")
    print(f"Actual Body Length (bytes): {len(resp.content)}")

    # Check image signature
    is_img, img_type = is_valid_image(resp.content)
    print(f"Valid Image Signature: {is_img} ({img_type})")

    if not is_img:
        print("First 200 bytes (raw / decoded representation):")
        try:
            print(resp.content[:200].decode("utf-8", errors="replace"))
        except Exception:
            print(resp.content[:200])

    return resp, elapsed

def main():
    print(f"Testing URL:\n{URL}\n")
    
    # Request 1
    resp1, elapsed1 = inspect_request("Request 1")
    print()

    # Request 2
    resp2, elapsed2 = inspect_request("Request 2")
    print()

    # Timing comparison
    print("=== Timing & Cache Comparison ===")
    print(f"Run 1 Elapsed: {elapsed1:.2f}s")
    print(f"Run 2 Elapsed: {elapsed2:.2f}s")
    if elapsed2 < elapsed1:
        print(f"Elapsed time dropped by {elapsed1 - elapsed2:.2f}s (Likely cached after first generation)")
    else:
        print(f"Elapsed time did not drop (Run 1: {elapsed1:.2f}s vs Run 2: {elapsed2:.2f}s)")
    print()

    # Verdict
    print("=== Verdict ===")
    # Verdict options specified in prompt:
    # "direct image", "redirect to image", "slow generation (>7s)", "auth/rate-limit error (status)", or "not an image"
    if resp1 is None:
        verdict = f"request exception"
    elif resp1.status_code in (401, 403, 429):
        verdict = f"auth/rate-limit error ({resp1.status_code})"
    else:
        is_img, _ = is_valid_image(resp1.content)
        if not is_img:
            verdict = "not an image"
        elif elapsed1 > 7.0:
            verdict = "slow generation (>7s)"
        elif len(resp1.history) > 0:
            verdict = "redirect to image"
        else:
            verdict = "direct image"

    print(f"Verdict: {verdict}")

if __name__ == "__main__":
    main()
