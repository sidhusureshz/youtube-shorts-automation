src = open('main.py', encoding='utf-8').read()
checks = [
    ('retry_count variable present', 'retry_count' in src),
    ('narration 600-char limit in prompt', '600' in src),
    ('narration length enforcement loop re-gen', 'len(narration)' in src and 'while' in src),
    ('script re-gen on over-limit', 'regenerat' in src.lower()),
    ('TC09 retry limit configurable', 'retry_limit' in src.lower() or 'max_retry' in src.lower()),
    ('TC11 duration stored or checked', 'duration' in src),
    ('TC12 duration tolerance check', 'tolerance' in src.lower()),
    ('TC13 ElevenLabs provider', 'elevenlabs' in src.lower()),
    ('TC16 image retry adjusted prompt', 'adjusted' in src.lower()),
    ('TC17 Leonardo AI provider', 'leonardo' in src.lower()),
    ('TC20 CapCut fallback export', 'capcut' in src.lower()),
    ('TC21 captions burned into video', 'caption' in src.lower()),
    ('TC25 notify_email field exists', 'notify_email' in src),
    ('TC26 email failed_stage tracked', 'failed_stage' in src),
    ('TC28 retry limit escalation', 'escalat' in src.lower()),
    ('TC29 empty topic guard', 'if not topic' in src),
    ('TC30 per-stage retry limit config', 'stage_retry' in src.lower()),
    ('TC31 retry audit trail storage', 'audit' in src.lower()),
    ('TC32 wall clock time logged', 'wallClockSec' in src or 'wall_clock' in src.lower()),
    ('TC33 cost ledger per provider', 'estimated_cost_usd' in src),
    ('TC34 style consistency metric', 'quality' in src.lower() and 'consistency' in src.lower()),
    ('TC35 quality rating stored', 'quality_rating' in src.lower()),
]
for label, result in checks:
    tag = 'YES' if result else 'NO '
    print(tag + ' | ' + label)
