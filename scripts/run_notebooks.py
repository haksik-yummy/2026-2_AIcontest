"""노트북을 번호 순서로 실행합니다. 앞 노트북이 저장한 자료를 뒤 노트북이 읽습니다.

실행: python scripts/run_notebooks.py               # 01-2부터 05-2까지
      python scripts/run_notebooks.py --start 04-1  # 04-1부터 끝까지
      python scripts/run_notebooks.py --only 05-2   # 하나만
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", help="이 번호부터 실행합니다 (예: 04-1)")
    parser.add_argument("--only", help="이 번호만 실행합니다 (예: 05-2)")
    args = parser.parse_args()

    notebooks = sorted((ROOT / "notebooks").glob("*/*.ipynb"), key=lambda p: p.name)
    if args.only:
        notebooks = [p for p in notebooks if p.name.startswith(args.only)]
    elif args.start:
        notebooks = [p for p in notebooks if p.name[:4] >= args.start]
    if not notebooks:
        print("실행할 노트북이 없습니다.", file=sys.stderr)
        return 1

    for path in notebooks:
        t0 = time.time()
        print(f"실행 {path.name}", flush=True)
        # 노트북은 자기 폴더를 작업 폴더로 삼습니다
        done = subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
                               "--ExecutePreprocessor.timeout=-1", path.name], cwd=path.parent)
        if done.returncode != 0:
            print(f"{path.name}에서 멈췄습니다.", file=sys.stderr)
            return done.returncode
        print(f"  {time.time() - t0:.0f}초", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
