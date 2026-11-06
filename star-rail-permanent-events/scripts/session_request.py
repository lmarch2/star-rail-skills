"""Submit one batch, or read a result without replaying the batch."""
import argparse
import json
import msvcrt
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument("--session", required=True)
source = parser.add_mutually_exclusive_group(required=True)
source.add_argument("--hex")
source.add_argument("--file")
source.add_argument("--result", help="Read/wait for a previously submitted request ID")
parser.add_argument("--owner", help="Control owner used for claim, input and release")
parser.add_argument("--timeout", type=float, default=25)
parser.add_argument("--compact", action="store_true", help="Omit OCR boxes from terminal output")
args = parser.parse_args()
session = Path(args.session).resolve()
requests = session / "requests"
responses = session / "responses"
requests.mkdir(exist_ok=True)
responses.mkdir(exist_ok=True)
if args.result:
    request_id = args.result
else:
    request = json.loads(bytes.fromhex(args.hex).decode("utf-8") if args.hex else Path(args.file).read_text(encoding="utf-8-sig"))
    if isinstance(request, list):
        request = {"actions": request}
    if args.owner:
        request["owner"] = args.owner
    # Number allocation and publication share a short lock so two clients never overwrite a batch.
    with (session / "submit.lock").open("a+b") as submission:
        submission.seek(0)
        msvcrt.locking(submission.fileno(), msvcrt.LK_LOCK, 1)
        try:
            sequence = max((int(p.stem) for p in requests.glob("*.json")), default=0) + 1
            request_id = f"{sequence:04d}"
            target = requests / f"{request_id}.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
        finally:
            submission.seek(0)
            msvcrt.locking(submission.fileno(), msvcrt.LK_UNLCK, 1)
response = responses / request_id / "result.json"
deadline = time.monotonic() + args.timeout
result = None
while True:
    if response.exists():
        try:
            result = json.loads(response.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass  # Older workers write in place; wait for the write to finish.
    if result is not None or time.monotonic() >= deadline:
        break
    time.sleep(.1)
if result is not None:
    if args.compact:
        result.pop("records", None)
    print(json.dumps(result, ensure_ascii=True))
else:
    print(json.dumps({"status": "pending", "request": request_id, "result": str(response)}))
