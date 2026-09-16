# -*- coding: utf-8 -*-
"""
요청주소 하나를 바로 확인해 보는 도구

무엇을 하나
  공공데이터포털에서 복사한 '요청주소'가 진짜 되는지 그 자리에서 확인합니다.
  파일을 고칠 필요 없이 주소만 붙여넣으면 됩니다.
  되면 어떤 항목(칸 이름)이 오는지까지 보여줍니다.

실행
  python3 scripts/check_api.py "http://apis.data.go.kr/1300000/XXXX/list"

되는 것을 확인한 뒤에
  config/endpoints.json 의 해당 API 에 url 을 적고 use 를 true 로 바꾸세요.

파이썬 기본 기능만 씁니다. 따로 설치할 것이 없습니다.
"""
import json, os, pathlib, sys, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

ROOT    = pathlib.Path(__file__).resolve().parent.parent
OUTDIR  = ROOT / "data" / "raw" / "probe"
TIMEOUT = 20

# 공공데이터포털이 돌려주는 오류 번호를 쉬운 말로 풀어 놓은 표
WHY = {
    "04": ("자료를 주는 쪽(병무청) 서버가 응답하지 않습니다",
           "주소나 인증키 문제가 아닙니다. 제공기관 쪽 일시 장애입니다.\n"
           "   잠시 뒤, 또는 다음 날 다시 해보세요. 같은 주소가 전에 됐다면 그대로 두면 됩니다."),
    "12": ("주소가 틀렸습니다",
           "'요청주소'를 잘못 옮겼거나 폐기된 API입니다.\n"
           "   포털의 해당 API 페이지 → [활용가이드] 또는 [상세설명] 에 적힌 주소를\n"
           "   끝의 /list 까지 그대로 복사해 주세요."),
    "20": ("이 API를 쓸 권한이 없습니다",
           "활용신청이 승인되지 않았거나, 다른 계정의 인증키입니다.\n"
           "   마이페이지 → 개발계정 에서 이 API가 '승인' 인지 확인하세요."),
    "22": ("오늘 쓸 수 있는 횟수를 다 썼습니다",
           "개발계정은 보통 하루 1만 건입니다. 내일 다시 해보세요."),
    "30": ("인증키가 이 API에 등록되어 있지 않습니다",
           "주소는 맞습니다. 활용신청 승인 직후라면 반영까지 몇 분~1시간 걸립니다.\n"
           "   조금 뒤 다시 해보시고, 계속 이러면 인증키를 다시 복사해 보세요."),
    "31": ("인증키 사용 기간이 끝났습니다", "포털에서 기간을 연장하세요."),
    "32": ("등록되지 않은 IP입니다", "포털에 IP 제한을 걸어 두셨는지 확인하세요."),
    "10": ("요청 항목이 잘못되었습니다", "주소 뒤에 붙는 값(pageNo 등)을 확인하세요."),
}


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
        sys.exit("인증키를 찾지 못했습니다. .env 파일의 DATA_GO_KR_KEY 를 확인하세요.")
    return key


def key_forms(key):
    """포털이 주는 Encoding / Decoding 두 형태를 모두 준비합니다."""
    dec = urllib.parse.unquote(key)
    forms = [("그대로", key)]
    if dec != key:
        forms.append(("Decoding", dec))
    enc = urllib.parse.quote(dec, safe="")
    if enc != key:
        forms.append(("Encoding", enc))
    return forms


def call(url, key, fmt):
    q = f"serviceKey={key}&pageNo=1&numOfRows=3"
    if fmt == "json":
        q += "&_type=json"
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "byeongyeok-tool/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.getcode(), r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def result_code(body):
    """응답에서 오류 번호와 메시지를 꺼냅니다. (JSON / XML 둘 다)"""
    t = body.strip()
    if t.startswith("{"):
        try:
            d = json.loads(t)
        except Exception:
            return None, None
        h = (d.get("response", {}) or {}).get("header", {}) or {}
        if h:
            return str(h.get("resultCode", "")), h.get("resultMsg", "")
        c = (d.get("OpenAPI_ServiceResponse", {}) or {}).get("cmmMsgHeader", {}) or {}
        return str(c.get("returnReasonCode", "")), c.get("returnAuthMsg", "")
    if t.startswith("<"):
        try:
            root = ET.fromstring(t)
        except Exception:
            return None, None
        code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
        msg  = root.findtext(".//resultMsg")  or root.findtext(".//returnAuthMsg")
        return (str(code) if code is not None else None), msg
    return None, None


def show_items(body):
    """응답에 들어 있는 항목(칸 이름)과 값 하나를 보여줍니다."""
    t = body.strip()
    rows, total = [], None
    if t.startswith("{"):
        d = json.loads(t, parse_float=str)     # 특기코드가 망가지지 않도록 글자 그대로
        b = ((d.get("response", {}) or {}).get("body", {}) or {})
        total = b.get("totalCount")
        items = b.get("items", {})
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        rows = items or []
    elif t.startswith("<"):
        root = ET.fromstring(t)
        total = root.findtext(".//totalCount")
        for it in root.iter("item"):
            rows.append({c.tag: (c.text or "") for c in it})

    print(f"\n   전체 건수: {total}")
    if not rows:
        print("   자료가 한 건도 오지 않았습니다. (신청은 됐지만 아직 자료가 없을 수 있습니다)")
        return
    print(f"   받은 줄: {len(rows)}개\n")
    print(f"   {'항목 이름':22s} {'값 (첫 줄)'}")
    print("   " + "-" * 60)
    for k, v in rows[0].items():
        s = str(v)
        print(f"   {k:22s} {s[:36]}")
    if len(rows) > 1:
        print(f"\n   두 번째 줄 미리보기: "
              + json.dumps(rows[1], ensure_ascii=False)[:160])


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip() + "\n\n주소를 함께 적어 주세요.")
    url = sys.argv[1].strip().strip('"').strip("'")

    if "data.go.kr/data/" in url or "openapi.do" in url:
        sys.exit("이것은 포털 '화면 주소'입니다. API '요청주소'가 필요합니다.\n"
                 "  그 페이지의 [활용가이드] 문서나 [상세설명] 에 적힌\n"
                 "  http://apis.data.go.kr/... 로 시작하는 주소를 넣어 주세요.")
    if not url.startswith("http"):
        sys.exit("http:// 또는 https:// 로 시작하는 주소를 넣어 주세요.")

    key = load_key()
    print(f"주소  : {url}")
    print(f"인증키: …{key[-6:]} (화면에 전체를 찍지 않습니다)\n")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    last = None
    for fmt in ("json", "xml"):
        for name, k in key_forms(key):
            status, body = call(url, k, fmt)
            code, msg = result_code(body)
            ok = status == 200 and (code in ("00", "0", None) or not code)
            tag = f"[{fmt.upper()} · 인증키 {name}]"
            if ok:
                print(f"{tag} 성공 ✅")
                out = OUTDIR / ("check_" + url.rstrip("/").split("/")[-2] + f".{fmt}")
                out.write_text(body, encoding="utf-8")
                show_items(body)
                print(f"\n   응답 원본을 저장했습니다: {out}")
                print("\n다음으로 할 일")
                print("   config/endpoints.json 에서 이 API 의")
                print(f'     "url": "{url}"  로 적고')
                print('     "use": true     로 바꾸세요.')
                return 0
            print(f"{tag} 실패 — HTTP {status}"
                  + (f" · 번호 {code} · {msg}" if code else ""))
            last = code

    print()
    if last in WHY:
        title, how = WHY[last]
        print(f"원인: {title}")
        print(f"   {how}")
    else:
        print("원인을 알 수 없습니다. 위 메시지를 그대로 알려주세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
