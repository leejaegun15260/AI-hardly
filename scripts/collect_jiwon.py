# -*- coding: utf-8 -*-
"""
'모집병 군별 특기별 지원가능 정보' 수집기  (data.go.kr 3066750)

무엇을 하나
  API를 처음부터 끝까지 나눠 받아서, 우리 화면이 쓸 형태로 정리합니다.
  전체가 137만 건이라 한 번에 못 받습니다. 페이지를 나눠 받고 진행 상황을 저장하므로,
  중간에 끊겨도 다시 실행하면 이어서 받습니다.

실행
  python3 scripts/collect_jiwon.py              # 이어받기 (처음이면 처음부터)
  python3 scripts/collect_jiwon.py --pages 20   # 20페이지만 시험 삼아
  python3 scripts/collect_jiwon.py --rebuild    # 이미 받은 것으로 결과 파일만 다시 만들기
  python3 scripts/collect_jiwon.py --reset      # 처음부터 다시 받기

받은 자료는 어디에
  data/build/jiwon.sqlite     받은 원본을 담는 창고 (중복은 자동으로 걸러집니다)
  data/build/major_index.json 학과명 → 이 학과를 인정하는 특기 목록
  data/build/cert_index.json  자격명 → 이 자격을 인정하는 특기 목록·등급
  data/build/jiwon_stats.json 특기별 인정 전공/자격 개수
  data/build/web_index.json   화면이 읽는 압축 색인 (위 두 색인을 부피를 줄여 다시 적은 것)
  data/build/_jiwon_report.json 등급·군·지침 등 실제로 들어있는 값 목록

파이썬 기본 기능만 씁니다. 따로 설치할 것이 없습니다.
"""
import argparse, json, pathlib, sqlite3, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "data" / "build"
DB    = BUILD / "jiwon.sqlite"
URL   = "http://apis.data.go.kr/1300000/mjbJiWon/list"

PAGE_SIZE = 1000     # 한 번에 받을 건수. API가 더 적게 주면 자동으로 낮춥니다.
PAUSE     = 0.2      # 호출 사이 쉬는 시간(초). 서버에 무리를 주지 않기 위함입니다.
TIMEOUT   = 30
RETRY     = 3

# 엑셀 특기 목록의 군 이름과 맞추기 위한 표
BRANCH_ALIAS = {"해병대": "해병", "해병대사령부": "해병"}


# ------------------------------------------------------------------ 인증키
def load_key():
    import os
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        envfile = ROOT / ".env"
        if envfile.exists():
            for line in envfile.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line.startswith("#") and line.startswith("DATA_GO_KR_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key or key.startswith("여기에"):
        sys.exit("인증키가 없습니다. .env.example 을 복사해 .env 를 만들고 키를 넣어주세요.")
    return key


def key_forms(key):
    dec = urllib.parse.unquote(key)
    forms = [key]
    if dec != key: forms.append(dec)
    enc = urllib.parse.quote(dec, safe="")
    if enc not in forms: forms.append(enc)
    return forms


# ------------------------------------------------------------------ 호출
def fetch(key, page, rows):
    """한 페이지를 받아 (전체건수, 행목록) 을 돌려줍니다."""
    q = f"serviceKey={key}&pageNo={page}&numOfRows={rows}&_type=json"
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "byeongyeok-tool/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read().decode("utf-8", errors="replace")

    if not body.lstrip().startswith("{"):
        raise RuntimeError("JSON 이 아닌 응답: " + body.strip()[:160].replace("\n", " "))

    # parse_float=str : 특기코드 121.102 가 소수점 오차로 망가지지 않도록
    #                   숫자를 '글자 그대로' 읽습니다. (매우 중요)
    data = json.loads(body, parse_float=str)
    head = data.get("response", {}).get("header", {})
    if head.get("resultCode") not in ("00", "0", None):
        raise RuntimeError(f"{head.get('resultCode')} {head.get('resultMsg')}")

    b = data["response"]["body"]
    items = b.get("items", {})
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return int(b.get("totalCount", 0)), (items or [])


def fetch_retry(key_list, page, rows):
    last = None
    for attempt in range(RETRY):
        for k in key_list:
            try:
                return fetch(k, page, rows)
            except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, TimeoutError) as e:
                last = e
        wait = 2 ** attempt
        print(f"    실패({last}) — {wait}초 뒤 재시도")
        time.sleep(wait)
    raise SystemExit(f"{page}페이지에서 계속 실패했습니다: {last}")


# ------------------------------------------------------------------ 창고
def open_db():
    BUILD.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("""
      CREATE TABLE IF NOT EXISTS jiwon(
        specialty_code TEXT, branch TEXT, code TEXT, specialty_name TEXT,
        gubun TEXT, name TEXT, grade TEXT, direct TEXT,
        guide_id TEXT, guide_name TEXT,
        UNIQUE(specialty_code, gubun, name, grade, direct, guide_id)
      );
      CREATE TABLE IF NOT EXISTS progress(page INTEGER PRIMARY KEY, rows INTEGER);
      CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
      CREATE INDEX IF NOT EXISTS ix_name  ON jiwon(gubun, name);
      CREATE INDEX IF NOT EXISTS ix_spec  ON jiwon(specialty_code);
    """)
    return con


def clean(v):
    return (str(v).strip() if v is not None else "")


def rows_of(items):
    for it in items:
        branch = clean(it.get("gtcdNm1"))
        branch = BRANCH_ALIAS.get(branch, branch)
        code   = clean(it.get("gsteukgiCd"))
        if not code or not branch:
            continue
        yield (f"{branch}-{code}", branch, code, clean(it.get("gsteukgiNm")),
               clean(it.get("gubun")), clean(it.get("gtcdNm2")),
               clean(it.get("jgmyeonheoDg")), clean(it.get("jjganjeopGbcd")),
               clean(it.get("gsjichimId")), clean(it.get("gsjichimNm")))


# ------------------------------------------------------------------ 특기코드 맞추기
# API 가 주는 특기코드와 엑셀 특기목록의 특기코드는 표기가 조금씩 다릅니다.
#   예)  엑셀 '163.11'  ↔  API '163.110'  ↔  API '163.110.'  (끝에 점이 붙는 경우도 있음)
# 소수점 아래를 세 자리로 맞춰서 같은 것끼리 이어 줍니다.
def norm3(code):
    code = str(code).strip().rstrip(".")
    if "." in code:
        a, d = code.split(".", 1)
        code = a + "." + (d + "000")[:3]
    return code


def load_specialty_map():
    """엑셀 특기목록(data/build/specialty.json)의 특기코드로 맞춰 주는 표를 만듭니다."""
    f = BUILD / "specialty.json"
    if not f.exists():
        return {}, {}
    spec = json.loads(f.read_text(encoding="utf-8"))
    canon, names = {}, {}
    for s in spec:
        branch = s.get("branch", "")
        key = f"{branch}-{norm3(s.get('code',''))}"
        canon[key] = s["specialty_code"]
        names[s["specialty_code"]] = s.get("specialty_name", "")
    return canon, names


# ------------------------------------------------------------------ 등급이 빈칸일 때
# 병무청 자료에는 등급이 비어 있는 자격이 일부 있습니다(주로 해군).
# 상담 담당자 결정: "자격 이름 끝에 국가기술자격 등급(기술사·기능장·기사·산업기사·기능사)이
#                   분명히 붙어 있으면 그 등급으로 보고, 그 밖의 것은 등급을 정하지 않는다."
# 예)  '가스기능사'      → 기능사급
#      '공조냉동기계산업기사' → 산업기사급
#      '무선인터넷관리사'  → 그대로 둠 (공인 민간자격일 수 있어 임의로 정하지 않음)
#      '고무제품제조기능사보' → 그대로 둠 ('기능사보'는 기능사가 아님)
GRADE_BY_NAME = [
    ("기능사보", None),          # 기능사가 아니므로 제외 (기능사보다 먼저 확인)
    ("기술사",   "기사급이상(이름추정)"),
    ("기능장",   "기사급이상(이름추정)"),
    ("산업기사", "산업기사급(이름추정)"),
    ("기사",     "기사급이상(이름추정)"),
    ("기능사",   "기능사급(이름추정)"),
]

def grade_from_name(name):
    """등급이 비어 있을 때 자격 이름으로 국가기술자격 등급을 알아냅니다. 모르면 빈 문자열."""
    base = name.strip()
    # 이름 뒤에 붙은 괄호는 떼고 봅니다
    #   '광산보안기능사(화약분야)'            → '광산보안기능사'
    #   '프로그래밍기능사[(전)정보처리기능사]'  → '프로그래밍기능사'
    for open_, close in (("[", "]"), ("(", ")")):
        if base.endswith(close) and open_ in base:
            base = base[:base.rindex(open_)].strip()
    for tail, grade in GRADE_BY_NAME:
        if base.endswith(tail):
            return grade or ""
    return ""


# ------------------------------------------------------------------ 결과 파일 만들기
MAJOR_SAMPLE = 40      # 특기 하나당 화면에 보여줄 인정 학과 표본 개수

def build_outputs(con):
    print("\n결과 파일을 만듭니다…")
    cur = con.cursor()

    total = cur.execute("SELECT COUNT(*) FROM jiwon").fetchone()[0]
    if not total:
        print("  받은 자료가 없습니다."); return

    canon, canon_names = load_specialty_map()

    def cc(branch, code):
        """API 특기코드 → 엑셀 특기목록의 특기코드 (없으면 정규화한 값 그대로)"""
        k = f"{branch}-{norm3(code)}"
        return canon.get(k, k)

    # ---------- 학과명 → 특기 목록 ----------
    major = {}
    for name, branch, code in cur.execute(
            "SELECT name, branch, code FROM jiwon WHERE gubun='전공' GROUP BY name, branch, code"):
        if not name: continue
        major.setdefault(name, set()).add(cc(branch, code))
    major = {k: sorted(v) for k, v in sorted(major.items())}

    # ---------- 자격·면허명 → [{특기, 등급}] ----------
    # '자격' 과 '면허' 를 함께 담습니다. 배점표의 항목 이름이 '자격/면허' 이기 때문입니다.
    cert = {}
    guessed = {}
    for name, branch, code, grade, gubun, direct in cur.execute(
            "SELECT name, branch, code, grade, gubun, direct FROM jiwon "
            "WHERE gubun IN ('자격','면허') GROUP BY name, branch, code, grade, gubun, direct"):
        if not name: continue
        if not grade:                              # 등급이 빈칸이면 이름으로 알아봅니다
            g2 = grade_from_name(name)
            if g2:
                grade = g2
                guessed[name] = g2
        cert.setdefault(name, []).append(
            {"specialty_code": cc(branch, code), "grade": grade, "kind": gubun, "direct": direct})
    cert = dict(sorted(cert.items()))

    # ---------- 특기별 개수 ----------
    stats = {}
    for branch, code, sname, gubun, n in cur.execute(
            "SELECT branch, code, specialty_name, gubun, COUNT(DISTINCT name) "
            "FROM jiwon GROUP BY branch, code, gubun"):
        sc = cc(branch, code)
        s = stats.setdefault(sc, {"specialty_name": canon_names.get(sc) or sname,
                                  "major_count": 0, "cert_count": 0})
        if gubun == "전공":            s["major_count"] += n
        elif gubun in ("자격", "면허"): s["cert_count"] += n
    stats = dict(sorted(stats.items()))

    def dump(fname, obj):
        p = BUILD / fname
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {fname:26s} {len(obj):7,d}개  ({p.stat().st_size/1024/1024:.1f} MB)")

    dump("major_index.json", major)
    dump("cert_index.json",  cert)
    dump("jiwon_stats.json", stats)

    # ---------- 화면용 압축 색인 ----------
    build_web_index(major, cert, stats, total)

    # ---------- 실제로 어떤 값들이 들어있는지 ----------
    report = {
        "총_행수": total,
        "특기수": len(stats),
        "엑셀_특기목록과_일치": sum(1 for k in stats if k in canon_names),
        "군별": dict(cur.execute("SELECT branch, COUNT(*) FROM jiwon GROUP BY branch").fetchall()),
        "구분별": dict(cur.execute("SELECT gubun, COUNT(*) FROM jiwon GROUP BY gubun").fetchall()),
        "자격등급_목록": dict(cur.execute(
            "SELECT grade, COUNT(*) FROM jiwon WHERE gubun IN ('자격','면허') "
            "GROUP BY grade ORDER BY 2 DESC").fetchall()),
        "구분별_등급": {f"{g}/{gr}": n for g, gr, n in cur.execute(
            "SELECT gubun, grade, COUNT(*) FROM jiwon WHERE gubun IN ('자격','면허') "
            "GROUP BY gubun, grade ORDER BY 3 DESC")},
        "직접간접": dict(cur.execute("SELECT direct, COUNT(*) FROM jiwon GROUP BY direct").fetchall()),
        "지침수": cur.execute("SELECT COUNT(DISTINCT guide_id) FROM jiwon").fetchone()[0],
        "받은_페이지수": cur.execute("SELECT COUNT(*) FROM progress").fetchone()[0],
        "이름으로_등급추정": dict(sorted(guessed.items())),
        "등급을_정하지_못한_자격": sorted({n for n, v in cert.items()
                                           if any(e["grade"] == "" for e in v)}),
    }
    (BUILD/"_jiwon_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n" + "="*60)
    print(f"총 {total:,}건 · 특기 {report['특기수']}개 (엑셀 목록과 일치 {report['엑셀_특기목록과_일치']}개)")
    print("군별:", report["군별"])
    print("구분별:", report["구분별"])
    print("자격 등급 종류:")
    for g, n in report["자격등급_목록"].items():
        print(f"   '{g}'  {n:,}건")
    print("="*60)


# 특기 번호를 36진법 두 글자로 적습니다. ("0"~"zz" = 0~1295번)
# 왜: 137만 건을 그대로 보내면 파일이 너무 커집니다. 두 글자로 적으면 부피가 절반이 됩니다.
B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
def e36(n):
    return B36[n // 36] + B36[n % 36]


def build_web_index(major, cert, stats, total):
    """브라우저가 읽을 파일 하나(web_index.json)를 만듭니다.

    조회는 '이름'(학과명·자격명)으로 합니다.  이름 → 특기 번호 목록.
      major : {"전기과": "0a0f1z"}        두 글자씩 끊어 읽으면 특기 번호
      cert  : {"전기기사": "0a10f2"}      세 글자씩 — 앞 두 글자 특기 번호, 뒤 한 글자 등급 번호
    """
    specs  = sorted(stats.keys())
    si     = {c: i for i, c in enumerate(specs)}
    grades = sorted({e["grade"] for v in cert.values() for e in v})
    gi     = {g: i for i, g in enumerate(grades)}
    if len(specs) > 36 * 36:
        raise SystemExit("특기가 1296개를 넘습니다. 표기 방식을 늘려야 합니다.")
    if len(grades) > 36:
        raise SystemExit("등급이 36개를 넘습니다. 표기 방식을 늘려야 합니다.")

    w_major, spec_major = {}, {}
    for name, codes in major.items():
        idxs = sorted({si[c] for c in codes if c in si})
        if not idxs:
            continue
        w_major[name] = "".join(e36(i) for i in idxs)
        for i in idxs:
            lst = spec_major.setdefault(i, [])
            if len(lst) < MAJOR_SAMPLE:
                lst.append(name)

    w_cert, w_kind = {}, {}
    for name, entries in cert.items():
        seen, parts = set(), []
        for e in entries:
            c = e["specialty_code"]
            if c not in si:
                continue
            k = (si[c], gi[e["grade"]])
            if k in seen:
                continue
            seen.add(k)
            parts.append(e36(k[0]) + B36[k[1]])
        if parts:
            w_cert[name] = "".join(sorted(parts))
            w_kind[name] = entries[0]["kind"]

    obj = {
        "meta": {"row_count": total, "spec_count": len(specs),
                 "major_name_count": len(w_major), "cert_name_count": len(w_cert),
                 "major_sample_limit": MAJOR_SAMPLE},
        "specs": specs,
        "spec_names":  [stats[c]["specialty_name"] for c in specs],
        "major_count": [stats[c]["major_count"] for c in specs],
        "cert_count":  [stats[c]["cert_count"]  for c in specs],
        "grades": grades,
        "major": w_major,
        "cert": w_cert,
        "cert_kind": w_kind,
        "spec_major_sample": {str(k): v for k, v in sorted(spec_major.items())},
    }
    p = BUILD / "web_index.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {'web_index.json':26s} 학과 {len(w_major):,}개 · 자격 {len(w_cert):,}개"
          f"  ({p.stat().st_size/1024/1024:.1f} MB)")


# ------------------------------------------------------------------ 본체
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=0, help="이번에 받을 페이지 수 (0=끝까지)")
    ap.add_argument("--rebuild", action="store_true", help="새로 받지 않고 결과 파일만 다시 만들기")
    ap.add_argument("--reset", action="store_true", help="처음부터 다시 받기")
    args = ap.parse_args()

    con = open_db()
    if args.reset:
        con.executescript("DELETE FROM jiwon; DELETE FROM progress; DELETE FROM meta;")
        con.commit(); print("이전 진행 기록을 지웠습니다.")
    if args.rebuild:
        build_outputs(con); return

    key_list = key_forms(load_key())

    # 1페이지를 받아 전체 건수와 한 번에 받을 수 있는 건수를 확인합니다
    total, first = fetch_retry(key_list, 1, PAGE_SIZE)
    per = len(first) or PAGE_SIZE
    pages = (total + per - 1) // per
    print(f"전체 {total:,}건 · 한 번에 {per}건 · 총 {pages:,}페이지")
    if per < PAGE_SIZE:
        print(f"  (요청한 {PAGE_SIZE}건보다 적게 옵니다. API 상한이 {per}건인 것 같습니다)")
    if pages > 9000:
        print(f"  주의: 개발계정 하루 한도(1만 건)에 가깝습니다. 며칠에 나눠 받으세요.")

    done = {p for (p,) in con.execute("SELECT page FROM progress")}
    todo = [p for p in range(1, pages + 1) if p not in done]
    if args.pages:
        todo = todo[:args.pages]
    if not todo:
        print("이미 다 받았습니다."); build_outputs(con); return
    print(f"이번에 받을 페이지: {len(todo):,}개 (이미 받은 것 {len(done):,}개)")

    started = time.time()
    for i, page in enumerate(todo, 1):
        items = first if page == 1 else fetch_retry(key_list, page, per)[1]
        con.executemany(
            "INSERT OR IGNORE INTO jiwon VALUES (?,?,?,?,?,?,?,?,?,?)", list(rows_of(items)))
        con.execute("INSERT OR REPLACE INTO progress VALUES (?,?)", (page, len(items)))
        con.commit()

        if i % 20 == 0 or i == len(todo):
            el = time.time() - started
            left = el / i * (len(todo) - i)
            got = con.execute("SELECT COUNT(*) FROM jiwon").fetchone()[0]
            print(f"  {i:,}/{len(todo):,}페이지 · 누적 {got:,}건 · 남은 시간 약 {left/60:.0f}분")
        if page != 1:
            time.sleep(PAUSE)

    build_outputs(con)


if __name__ == "__main__":
    main()
