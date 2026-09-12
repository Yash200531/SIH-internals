from app.ocr.fast_paddle_provider import FastPaddleOCRProvider
import asyncio, pathlib, sys

IMG_PATH = sys.argv[1] if len(sys.argv) > 1 else '/images/rx.jpg'

async def run():
    provider = FastPaddleOCRProvider(language='en')
    await provider.warmup()
    img = pathlib.Path(IMG_PATH).read_bytes()
    result = await provider.recognize(img, 'image/jpeg')
    print()
    print('=== OCR RESULT ===')
    print('Provider  :', result.provider)
    print('Model     :', result.model_version)
    print('Duration  :', result.duration_ms, 'ms')
    print('Regions   :', len(result.regions))
    print()
    print('--- Full extracted text ---')
    print(result.text)
    print()
    print('--- Top regions by confidence ---')
    for r in sorted(result.regions, key=lambda x: x.confidence, reverse=True)[:15]:
        print(f'  [{r.confidence:.2f}] {r.text}')

asyncio.run(run())
