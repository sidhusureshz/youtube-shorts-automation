import os
from dotenv import load_dotenv
load_dotenv(r'c:\Users\user\Desktop\Autso1\.env', override=True)

for k in ['YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REFRESH_TOKEN']:
    v = os.getenv(k, '')
    status = 'SET' if v else 'MISSING'
    print(f'{k}: {status}')

token = os.getenv('YOUTUBE_REFRESH_TOKEN', '')
if token:
    print(f'YOUTUBE_REFRESH_TOKEN OLD_TAIL (last 4): ...{token[-4:]}')
    print(f'YOUTUBE_REFRESH_TOKEN length: {len(token)}')
