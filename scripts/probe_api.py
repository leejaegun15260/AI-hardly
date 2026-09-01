# -*- coding: utf-8 -*-
"""
공공데이터 API 탐색기 — 승인받은 API가 실제로 무엇을 돌려주는지 확인합니다.

이 스크립트가 하는 일
  1. config/endpoints.json 에 적힌 API를 하나씩 호출합니다.
  2. 인증키의 두 가지 형태(Encoding / Decoding)를 자동으로 번갈아 시도합니다.
  3. 응답 원본을 data/raw/probe/ 에 그대로 저장합니다.
  4. 응답에 들어있는 '항목 이름'을 뽑아서 화면에 보여줍니다.

왜 필요한가
  API마다 항목 이름(예: gunGbcd, tgNm ...)이 다릅니다.
  이름을 모르면 수집 스크립트를 만들 수 없습니다.
  이 스크립트의 출력이 곧 수집기 설계도입니다.

실행 방법
  1) cp .env.example .env      (윈도우: .env.example 을 복사해 .env 로 이름 변경)
  2) .env 를 열어 인증키를 붙여넣고 저장
  3) python3 scripts/probe_api.py

파이썬 기본 기능만 씁니다. 따로 설치할 것이 없습니다.
"""
import json, os, pathlib, sys, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET

ROOT   = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "endpoints.json"
OUTDIR = ROOT / "data" / "raw" / "probe"
TIMEOUT = 20


# ---------------------------------------------------------------- 인증키
def load_key():
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        envfile = ROOT / ".env"
        if envfile.exists():
            for line in envfile.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "DATA_GO_KR_KEY":
                    key = v.strip().strip('"').strip("'")
    if not key or key.startswith("여기에"):
        sys.exit(
            "인증키를 찾지 못했습니다.\n"
            "  1) .env.example 을 복사해 .env 를 만드세요\n"
            "  2) .env 안의 DATA_GO_KR_KEY= 뒤에 인증키를 붙여넣으세요\n"
            "  (인증키 위치: 공공데이터포털 → 마이페이지 → 개발계정 → 서비스 클릭 → 일반 인증키)"
        )
    return key


def key_variants(key):
    """
    공공데이터포털 인증키는 Encoding / Decoding 두 형태로 제공됩니다.
    어느 쪽을 받았는지에 따라 요청을 만드는 방법이 달라 자주 실패합니다.
    그래서 두 가지를 모두 준비해 순서대로 시도합니다.
    """
    decoded = urllib.parse.unquote(key)
    variants = [("입력한 키 그대로", key)]
    if decoded != key:
        variants.append(("URL 디코딩한 키", decoded))
    encoded = urllib.parse.quote(decoded, safe="")
    if encoded != key:
        variants.append(("URL 인코딩한 키", encoded))
    return variants


# ---------------------------------------------------------------- 호출
def call(url, key, params):
    q = "&".join([f"serviceKey={key}"] +
                 [f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()])
    full = f"{url}?{q}"
    req = urllib.request.Request(full, headers={"User-Agent": "byeongyeok-tool/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return full, r.read().decode("utf-8", errors="replace")


FAIL_WORDS = ["SERVICE_KEY_IS_NOT_REGISTERED", "SERVICE KEY IS NOT REGISTERED",
              "APPLICATION_ERROR", "LIMITED_NUMBER_OF_SERVICE_REQUESTS",
              "UNKNOWN_ERROR", "NO_OPENAPI_SERVICE_ERROR", "HTTP_ERROR",
              "SERVICE_ACCESS_DENIED", "인증키"]


def looks_failed(body):
    head = body[:1500].upper()
    return any(w.upper() in head for w in FAIL_WORDS)


# ---------------------------------------------------------------- 항목 이름 뽑기
def fields_from_json(body):
    try:
        data = json.loads(body)
    except Exception:
        return None, None
    # 응답 구조가 제각각이라, 딕셔너리가 여러 개 담긴 리스트를 찾아 그것을 '자료'로 봅니다.
    best = []
    def walk(node):
        nonlocal best
        if isinstance(node, list):
            rows = [x for x in node if isinstance(x, dict)]
            if len(rows) > len(best):
                best = rows
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
    walk(data)
    if not best:
        # 항목이 1건이면 리스트가 아니라 딕셔너리로 오는 경우가 있습니다.
        def find_item(node):
            if isinstance(node, dict):
                if "item" in node and isinstance(node["item"], dict):
                    return [node["item"]]
                for v in node.values():
                    r = find_item(v)
                    if r: return r
            elif isinstance(node, list):
                for v in node:
                    r = find_item(v)
                    if r: return r
            return None
        best = find_item(data) or []
    if not best:
        return None, None
    keys = list(best[0].keys())
    return keys, best[0]


def fields_from_xml(body):
    try:
        root = ET.fromstring(body)
    except Exception:
        return None, None
    items = root.findall(".//item")
    if not items:
        # item 이 아닌 다른 이름일 수 있어, 같은 태그가 여러 번 반복되는 곳을 찾습니다.
        from collections import Counter
        parents = {}
        for parent in root.iter():
            names = Counter(c.tag for c in parent)
            for tag, n in names.items():
                if n >= 2:
                    parents.setdefault((parent, tag), n)
        if parents:
            (parent, tag), _ = max(parents.items(), key=lambda kv: kv[1])
            items = parent.findall(tag)
    if not items:
        return None, None
    first = items[0]
    keys = [c.tag for c in first]
    sample = {c.tag: (c.text or "").strip() for c in first}
    return keys, sample


# ---------------------------------------------------------------- 본체
def probe(ep, key):
    name, url = ep["name"], ep.get("url", "").strip()
    print(f"\n{'='*66}\n[{name}] {ep['설명']}")
    if not url:
        print("  요청주소가 비어 있습니다 — 건너뜁니다.")
        print(f"  포털에서 '요청주소'를 찾아 config/endpoints.json 에 넣어주세요:")
        print(f"    {ep['portal']}")
        return {"name": name, "status": "주소없음"}

    print(f"  {url}")
    last_err = None
    for how, k in key_variants(key):
        for params in ({"pageNo": 1, "numOfRows": 3, "_type": "json"},
                       {"pageNo": 1, "numOfRows": 3}):
            try:
                full, body = call(url, k, params)
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
                continue
            except Exception as e:
                last_err = str(e)
                continue

            if looks_failed(body):
                last_err = body.strip()[:200].replace("\n", " ")
                continue

            OUTDIR.mkdir(parents=True, exist_ok=True)
            ext = "json" if body.lstrip().startswith(("{", "[")) else "xml"
            path = OUTDIR / f"{name}.{ext}"
            path.write_text(body, encoding="utf-8")

            keys, sample = (fields_from_json(body) if ext == "json"
                            else fields_from_xml(body))
            print(f"  성공 ({how}, 형식 {ext})  → 저장: {path.relative_to(ROOT)}")
            if keys:
                print(f"  응답 항목 {len(keys)}개:")
                for kk in keys:
                    v = str(sample.get(kk, ""))
                    if len(v) > 40: v = v[:40] + "…"
                    print(f"     - {kk:24s} 예: {v}")
            else:
                print("  응답은 받았지만 항목을 자동으로 못 읽었습니다. 저장된 파일을 열어 확인하세요.")
                print("  앞부분:", body.strip()[:300].replace("\n", " "))
            return {"name": name, "status": "성공", "format": ext,
                    "fields": keys or [], "sample": sample or {}, "file": str(path)}

    print(f"  실패 — {last_err}")
    print("  확인할 것: ① 인증키가 맞는지 ② 이 API를 실제로 신청했는지"
          " ③ 요청주소가 맞는지 ④ 하루 요청 한도(개발계정 1만건)를 넘지 않았는지")
    return {"name": name, "status": "실패", "error": str(last_err)[:300]}


def main():
    key = load_key()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    eps = [e for e in cfg["endpoints"] if e.get("use", True)]

    print(f"인증키 확인됨 (앞 6자리: {key[:6]}…)  —  {len(eps)}개 API를 확인합니다.")
    results = [probe(e, key) for e in eps]

    print("\n" + "="*66)
    print("결과 요약")
    for r in results:
        mark = {"성공":"O", "실패":"X", "주소없음":"-"}[r["status"]]
        extra = f"항목 {len(r.get('fields',[]))}개" if r["status"]=="성공" else r.get("error","")
        print(f"  [{mark}] {r['name']:16s} {r['status']:6s} {extra[:60]}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    summary = OUTDIR / "_요약.json"
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n요약 저장: {summary.relative_to(ROOT)}")
    print("\n다음 단계: 위 '응답 항목' 목록을 그대로 복사해서 알려주시면")
    print("          그 이름에 맞춘 수집 스크립트(collect.py)를 만들어 드립니다.")


if __name__ == "__main__":
    main()
