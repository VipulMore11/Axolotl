import codecs
import os

req_path = r'e:\FastAPI\Axolotl\requirements.txt'

try:
    with codecs.open(req_path, 'a', encoding='utf-16') as f:
        f.write('\npython-jose[cryptography]==3.3.0\nhttpx==0.27.0\n')
    print("Successfully appended to requirements.txt")
except Exception as e:
    print(f"Failed to append: {e}")
