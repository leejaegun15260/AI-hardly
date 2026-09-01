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
  data/build/_jiwon_report.json 등급·군·지침 등 실제로 들어있는 값 목록

파이썬 기본 기능만 씁니다. 따로 설치할 것이 없습니다.
"""
import argparse, concurrent.futures, json, pathlib, sqlite3, sys, threading, time
import urllib.error, urllib.parse, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "data" / "build"
DB    = BUILD / "jiwon.sqlite"
URL   = "https://apis.data.go.kr/1300000/mjbJiWon/list"

PAGE_SIZE = 1000     # 한 번에 받을 건수. API가 더 적게 주면 자동으로 낮춥니다.
PAUSE     = 0.2      # 호출 사이 쉬는 시간(초). 서버에 무리를 주지 않기 위함입니다.
WORKERS   = 4        # 한 번에 함께 부를 개수. 한 번 부르는 데 2~3초 걸려
                     # 하나씩 부르면 137만 건에 두 시간이 넘습니다.
                     # 서버에 무리가 가지 않도록 넉넉히 낮춰 잡은 값입니다.
TIMEOUT   = 30
RETRY     = 5      # 연결이 끊기는 일이 잦아 넉넉히 다시 시도합니다

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


# 한 번 통한 인증키 형태를 기억해 둡니다. 형태를 매번 다 시도하면
# 그만큼 호출 한도(하루 1만 건)를 헛되이 씁니다.
_GOOD_KEY = None
_KEY_LOCK = threading.Lock()


def fetch_retry(key_list, page, rows):
    """한 페이지를 받되, 끊기면 잠시 쉬었다 다시 시도합니다."""
    global _GOOD_KEY
    last = None
    for attempt in range(RETRY):
        # 통했던 키 형태를 먼저, 아직 모르면 목록 순서대로
        with _KEY_LOCK:
            good = _GOOD_KEY
        forms = [good] if good else list(key_list)
        for k in forms:
            try:
                out = fetch(k, page, rows)
                with _KEY_LOCK:
                    _GOOD_KEY = k
                return out
            # HTTPError 는 URLError 의 한 종류이므로 반드시 먼저 잡아야 합니다
            except (urllib.error.HTTPError, RuntimeError) as e:
                # 서버가 대답은 했는데 거절한 것 — 키 형태 문제일 수 있으니 다음 형태를 시도
                last = e
                with _KEY_LOCK:
                    _GOOD_KEY = None
            except (urllib.error.URLError, TimeoutError) as e:
                # 연결 자체가 끊긴 것 — 키 문제가 아니므로 다른 형태는 시도하지 않습니다
                last = e
                break
        wait = 2 ** attempt
        print(f"    실패({last}) — {wait}초 뒤 재시도")
        time.sleep(wait)
    # 여기까지 왔으면 이 페이지는 이번에 포기합니다. 프로그램을 끝내지는 않습니다.
    # 받은 페이지만 기록해 두므로, 다시 실행하면 빠진 페이지부터 이어서 받습니다.
    print(f"  {page}페이지는 이번에 건너뜁니다: {last}")
    return None


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


def norm_code(text):
    """특기코드를 한 가지 모양으로 맞춥니다.

    엑셀 특기 목록은 코드가 숫자로 저장돼 있어 끝의 0 이 떨어져 나갑니다
    (163.110 → 163.11). API 는 163.110 을 그대로 줍니다. 그대로 두면
    같은 특기인데 서로 다른 것으로 보여 자격·전공이 하나도 연결되지 않습니다.
    그래서 양쪽 모두 '소수점 뒤 끝의 0 을 뗀' 모양으로 맞춥니다.
    (실제 코드 469개로 확인한 결과 이렇게 맞춰도 겹치는 코드는 없습니다)
    """
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def rows_of(items):
    for it in items:
        branch = clean(it.get("gtcdNm1"))
        branch = BRANCH_ALIAS.get(branch, branch)
        raw    = clean(it.get("gsteukgiCd"))
        code   = norm_code(raw)
        if not code or not branch:
            continue
        yield (f"{branch}-{code}", branch, raw, clean(it.get("gsteukgiNm")),
               clean(it.get("gubun")), clean(it.get("gtcdNm2")),
               clean(it.get("jgmyeonheoDg")), clean(it.get("jjganjeopGbcd")),
               clean(it.get("gsjichimId")), clean(it.get("gsjichimNm")))


# ------------------------------------------------------------------ 결과 파일 만들기
def renorm(con):
    """예전에 받아둔 자료의 특기코드를 norm_code 모양으로 맞춥니다.

    코드 맞추는 규칙이 생기기 전에 받아둔 자료가 있어도 다시 받을 필요가 없도록,
    결과 파일을 만들기 전에 한 번 훑어 고칩니다. 이미 맞으면 아무 일도 하지 않습니다.
    """
    cur = con.cursor()
    fix = [(f"{b}-{norm_code(c)}", old) for old, b, c
           in cur.execute("SELECT DISTINCT specialty_code, branch, code FROM jiwon")
           if old != f"{b}-{norm_code(c)}"]
    if not fix:
        return
    cur.executemany("UPDATE OR IGNORE jiwon SET specialty_code=? WHERE specialty_code=?", fix)
    con.commit()
    print(f"특기코드 {len(fix)}개를 맞춰 고쳤습니다 (예: {fix[0][1]} → {fix[0][0]})")

    # OR IGNORE 는 이미 같은 행이 있으면 그냥 넘어갑니다. 넘어간 것이 있으면
    # 옛 코드로 남아 별개의 특기처럼 보이므로, 남았는지 확인해 알려줍니다.
    left = [old for old, b, c in cur.execute("SELECT DISTINCT specialty_code, branch, code FROM jiwon")
            if old != f"{b}-{norm_code(c)}"]
    if left:
        print(f"  주의: {len(left)}개가 옛 코드로 남았습니다 ({left[:3]}). "
              f"--reset 으로 다시 받으면 깨끗해집니다.")


def build_outputs(con):
    print("\n결과 파일을 만듭니다…")
    renorm(con)
    cur = con.cursor()

    total = cur.execute("SELECT COUNT(*) FROM jiwon").fetchone()[0]
    if not total:
        print("  받은 자료가 없습니다."); return

    # 학과명 → 이 학과를 인정하는 특기 목록
    major = {}
    for name, code in cur.execute(
            "SELECT name, specialty_code FROM jiwon WHERE gubun='전공' "
            "GROUP BY name, specialty_code"):
        major.setdefault(name, []).append(code)

    # 자격명 → [{특기, 등급, 직접간접}]
    # '자격'과 '면허'를 함께 담습니다. 둘 다 자격/면허 배점에 쓰이는 항목입니다.
    cert = {}
    for name, gubun, code, grade, direct in cur.execute(
            "SELECT name, gubun, specialty_code, grade, direct FROM jiwon "
            "WHERE gubun IN ('자격','면허') GROUP BY name, gubun, specialty_code, grade, direct"):
        cert.setdefault(name, []).append(
            {"specialty_code": code, "grade": grade, "gubun": gubun, "direct": direct})

    # 특기 → 이 특기가 인정하는 자격/면허 목록 (반대 방향 색인)
    # 화면에서 '다음에 딸 만한 자격'을 안내할 때 씁니다.
    # 전공은 특기 하나에 수백 개씩 붙어 너무 커지므로 아래 stats 에 개수와 예시만 담습니다.
    spec_cert = {}
    for code, name, grade, gubun in cur.execute(
            "SELECT specialty_code, name, grade, gubun FROM jiwon "
            "WHERE gubun IN ('자격','면허') GROUP BY specialty_code, name, grade, gubun"):
        spec_cert.setdefault(code, []).append({"name": name, "grade": grade, "gubun": gubun})

    # 특기별 개수와 인정 전공 예시
    stats = {}
    for code, sname, gubun, n in cur.execute(
            "SELECT specialty_code, specialty_name, gubun, COUNT(DISTINCT name) "
            "FROM jiwon GROUP BY specialty_code, gubun"):
        s = stats.setdefault(code, {"specialty_name": sname, "major_count": 0,
                                    "cert_count": 0, "major_sample": []})
        if gubun == "전공":   s["major_count"] = n
        else:                 s["cert_count"] += n      # 자격 + 면허
    for code, names in cur.execute(
            "SELECT specialty_code, GROUP_CONCAT(name, '\x1f') FROM "
            "(SELECT DISTINCT specialty_code, name FROM jiwon WHERE gubun='전공' ORDER BY name) "
            "GROUP BY specialty_code"):
        if code in stats:
            stats[code]["major_sample"] = (names or "").split("\x1f")[:12]

    def dump(fname, obj):
        p = BUILD / fname
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {fname:26s} {len(obj):7,d}개  ({p.stat().st_size/1024/1024:.1f} MB)")

    dump("major_index.json", major)
    dump("cert_index.json",  cert)
    dump("spec_cert_index.json", spec_cert)
    dump("jiwon_stats.json", stats)

    # 실제로 어떤 값들이 들어있는지 — 배점표와 맞출 때 필요합니다
    report = {
        "총_행수": total,
        "특기수": cur.execute("SELECT COUNT(DISTINCT specialty_code) FROM jiwon").fetchone()[0],
        "군별": dict(cur.execute("SELECT branch, COUNT(*) FROM jiwon GROUP BY branch").fetchall()),
        "구분별": dict(cur.execute("SELECT gubun, COUNT(*) FROM jiwon GROUP BY gubun").fetchall()),
        "자격등급_목록": dict(cur.execute(
            "SELECT grade, COUNT(*) FROM jiwon WHERE gubun IN ('자격','면허') "
            "GROUP BY grade ORDER BY 2 DESC").fetchall()),
        "직접간접": dict(cur.execute("SELECT direct, COUNT(*) FROM jiwon GROUP BY direct").fetchall()),
        "지침수": cur.execute("SELECT COUNT(DISTINCT guide_id) FROM jiwon").fetchone()[0],
        "받은_페이지수": cur.execute("SELECT COUNT(*) FROM progress").fetchone()[0],
    }
    (BUILD/"_jiwon_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n" + "="*60)
    print(f"총 {total:,}건 · 특기 {report['특기수']}개")
    print("군별:", report["군별"])
    print("구분별:", report["구분별"])
    print("자격 등급 종류:")
    for g, n in report["자격등급_목록"].items():
        print(f"   '{g}'  {n:,}건")
    print("="*60)
    print("→ 위 '자격 등급 종류' 목록을 알려주시면 배점표와 연결해 드립니다.")


# ------------------------------------------------------------------ 본체
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=0, help="이번에 받을 페이지 수 (0=끝까지)")
    ap.add_argument("--rebuild", action="store_true", help="새로 받지 않고 결과 파일만 다시 만들기")
    ap.add_argument("--reset", action="store_true", help="처음부터 다시 받기")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"한 번에 함께 부를 개수 (기본 {WORKERS}). 늘리면 빨라지지만 서버에 부담이 됩니다")
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

    # 받아오기는 여러 갈래로 함께, 창고에 넣는 일은 한 갈래로만 합니다.
    # (sqlite 는 한 곳에서만 쓰는 편이 안전합니다)
    def get(page):
        if page == 1:
            return page, first
        time.sleep(PAUSE)
        got = fetch_retry(key_list, page, per)
        return page, (got[1] if got else None)

    def sweep(pages, label):
        """페이지 목록을 받아 창고에 넣고, 끝내 못 받은 페이지를 돌려줍니다."""
        started = time.time()
        workers = max(1, min(args.workers, len(pages)))
        print(f"{label} — {len(pages):,}페이지, 한 번에 {workers}개씩", flush=True)
        failed = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for i, (page, items) in enumerate(pool.map(get, pages), 1):
                if items is None:
                    failed.append(page)
                    continue
                con.executemany(
                    "INSERT OR IGNORE INTO jiwon VALUES (?,?,?,?,?,?,?,?,?,?)", list(rows_of(items)))
                con.execute("INSERT OR REPLACE INTO progress VALUES (?,?)", (page, len(items)))
                con.commit()

                if i % 50 == 0 or i == len(pages):
                    el = time.time() - started
                    left = el / i * (len(pages) - i)
                    got = con.execute("SELECT COUNT(*) FROM jiwon").fetchone()[0]
                    print(f"  {i:,}/{len(pages):,}페이지 · 누적 {got:,}건 · "
                          f"남은 시간 약 {left/60:.0f}분", flush=True)
        return failed

    # 연결이 끊겨 못 받은 페이지는 잠시 쉬었다가 다시 훑습니다.
    left = sweep(todo, "받는 중")
    for round_no in range(1, 4):
        if not left:
            break
        print(f"\n못 받은 {len(left):,}페이지를 30초 뒤 다시 받습니다 ({round_no}/3)", flush=True)
        time.sleep(30)
        left = sweep(left, f"다시 받는 중 {round_no}/3")
    if left:
        print(f"\n끝내 못 받은 페이지 {len(left):,}개: {left[:10]}{' …' if len(left) > 10 else ''}")
        print("다시 실행하면 이 페이지부터 이어서 받습니다.")

    build_outputs(con)


if __name__ == "__main__":
    main()
