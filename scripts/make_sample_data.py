# -*- coding: utf-8 -*-
"""
샘플 데이터 생성기 (시제품 시연용)

무엇을 만드나:
  아직 공공데이터를 받지 못한 세 가지를 '가짜로' 채웁니다.
    - specialty_cert.json   특기별 인정 자격/면허
    - specialty_major.json  특기별 인정 전공
    - cutoff.json           연도·회차별 합격 커트라인
    - applicants.json       지원자 수 (경쟁률)

무엇을 만들지 않나:
  specialty.json / interest_map.json 은 실제 자료입니다.
  scripts/import_interest_xlsx.py 가 만들며 이 스크립트는 손대지 않습니다.

어디에만 채우나:
  아래 DEMO 목록에 적은 육군 특기에만 채웁니다.
  나머지 특기는 데이터가 비어 있고, 화면에서 '데이터 준비 중'으로 표시됩니다.
  (전 특기에 가짜 숫자를 채우면 진짜와 구분이 안 되기 때문입니다)

나중에 할 일:
  이 파일을 scripts/collect.py 로 대체하세요.
    - 자격/전공  → 병무청 '모집병 군별 특기별 지원가능 정보' API
    - 커트라인   → 병무청 커트라인 CSV (encoding='cp949')
    - 지원자 수  → 병무청 '모집병 군지원 접수현황' API
  파일 형식만 같으면 화면(web/)은 그대로 동작합니다.
"""
import json, random, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "build"
random.seed(20260901)          # 매번 같은 샘플이 나오도록 고정

ROUNDS = [5, 8, 11]
YEARS  = [2023, 2024, 2025]

# 시연에 쓸 육군 특기 12개  (코드는 실제 자료의 코드)
#   코드 : (커트라인 기준선, 인정 자격/면허, 인정 전공)
DEMO = {
 "육군-162.104": (78, [("전기기사","기사"),("전기공사기사","기사"),("전기산업기사","산업기사"),
                      ("전기공사산업기사","산업기사"),("전기기능사","기능사"),("승강기기능사","기능사")],
                     ["전기과","전기공학과","전기전자공학과","전기제어과"]),
 "육군-175.103": (83, [("정보처리기사","기사"),("정보보안기사","기사"),("정보처리산업기사","산업기사"),
                      ("정보처리기능사","기능사"),("네트워크관리사 2급","공인 일반자격"),
                      ("리눅스마스터 2급","공인 일반자격")],
                     ["컴퓨터공학과","소프트웨어학과","정보통신과","정보보호학과"]),
 "육군-231.107": (72, [("조리산업기사","산업기사"),("한식조리기능사","기능사"),("양식조리기능사","기능사"),
                      ("중식조리기능사","기능사"),("제과기능사","기능사"),("제빵기능사","기능사")],
                     ["조리과","외식조리과","식품영양학과","호텔조리과"]),
 "육군-411.101": (80, [("응급구조사 1급","공인 일반자격"),("응급구조사 2급","공인 일반자격"),
                      ("간호조무사","공인 일반자격"),("임상병리사","공인 일반자격"),("위생사","공인 일반자격")],
                     ["간호학과","응급구조학과","보건행정과","임상병리학과"]),
 "육군-231.103": (74, [("물류관리사","공인 일반자격"),("유통관리사 2급","공인 일반자격"),
                      ("지게차운전기능사","기능사"),("전산회계 2급","비공인 일반자격")],
                     ["물류학과","경영학과","유통경영과","회계학과"]),
 "육군-225.101": (73, [("화약류관리기사","기사"),("화약류관리산업기사","산업기사"),
                      ("위험물산업기사","산업기사"),("위험물기능사","기능사"),("산업안전산업기사","산업기사")],
                     ["화학공학과","산업안전과","소방안전과"]),
 "육군-224.101": (76, [("자동차정비기사","기사"),("자동차정비산업기사","산업기사"),
                      ("자동차정비기능사","기능사"),("건설기계정비기능사","기능사")],
                     ["자동차과","기계공학과","기계설비과"]),
 "육군-171.101": (77, [("정보통신기사","기사"),("정보통신산업기사","산업기사"),
                      ("통신선로산업기사","산업기사"),("전자기능사","기능사"),("통신기기기능사","기능사")],
                     ["정보통신과","전자공학과","통신공학과"]),
 "육군-163.113": (71, [("굴착기운전기능사","기능사"),("건설기계정비산업기사","산업기사"),
                      ("로더운전기능사","기능사")],
                     ["건설기계과","토목과","건축과"]),
 "육군-241.105": (70, [("지게차운전기능사","기능사"),("기중기운전기능사","기능사")],
                     ["건설기계과","물류학과","자동차과"]),
 "육군-331.101": (79, [("전산회계 1급","공인 일반자격"),("재경관리사","공인 일반자격"),
                      ("전산회계운용사 2급","공인 일반자격")],
                     ["회계학과","경영학과","세무회계과"]),
 "육군-241.101": (75, [],  # 운전 특기: 운전면허 별도 배점체계를 씁니다 (rules 의 driving_track)
                     ["자동차과","운송과","기계과"]),
 "육군-311.101": (81, [("컴퓨터활용능력 1급","공인 일반자격"),("워드프로세서","공인 일반자격"),
                      ("사무자동화산업기사","산업기사")],
                     ["행정학과","경영학과","비서사무행정과"]),
}


def main():
    specs = json.loads((OUT/"specialty.json").read_text(encoding="utf-8"))
    known = {s["specialty_code"]: s for s in specs}

    missing = [c for c in DEMO if c not in known]
    if missing:
        raise SystemExit("specialty.json 에 없는 코드입니다: " + ", ".join(missing)
                         + "\n먼저 scripts/import_interest_xlsx.py 를 실행하세요.")

    s_cert, s_major, cutoff, applicants = [], [], [], []

    for code, (base, certs, majors) in DEMO.items():
        name = known[code]["specialty_name"]
        for cname, grade in certs:
            s_cert.append({"specialty_code": code, "cert_name": cname,
                           "cert_grade": grade, "sample": True})
        for m in majors:
            s_major.append({"specialty_code": code, "major_name": m, "sample": True})

        for y in YEARS:
            drift = (y - 2024) * random.uniform(-1.6, 1.6)
            for r in ROUNDS:
                picked = random.randint(8, 46)
                cutoff.append({
                    "year": y, "round": r, "branch": "육군",
                    "specialty_code": code, "specialty_name_raw": name,
                    "cutoff_score": round(base + drift + random.uniform(-2.4, 2.4), 1),
                    "selected_count": picked, "unit": "전군", "sample": True,
                })
                applicants.append({
                    "year": y, "round": r, "specialty_code": code,
                    "planned_count": picked,
                    "applicant_count": int(picked * random.uniform(1.4, 4.2)),
                    "sample": True,
                })

    for fname, payload in {"specialty_cert.json": s_cert, "specialty_major.json": s_major,
                           "cutoff.json": cutoff, "applicants.json": applicants}.items():
        (OUT/fname).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {fname:24s} {len(payload):4d}건")

    print(f"샘플을 채운 특기: {len(DEMO)}개 (전체 {len(specs)}개 중)")
    print("나머지 특기는 화면에서 '데이터 준비 중'으로 표시됩니다.")


if __name__ == "__main__":
    main()
